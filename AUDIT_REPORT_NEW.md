# 代码审计报告（2026-04-14，二次复核）

> 审计范围：当前仓库代码（本次复核基于 `ac47be0` 之后的本地工作区）  
> 审计方法：仅做证据驱动审计，不做大规模重构建议；对不确定项标记“需人工确认”。

## A. 项目结构与核心流程理解

1. **单进程聚合架构**：`app/main.py` 将 Builder 配置、提现执行、监控与静态页面全部挂在一个 FastAPI 进程中。  
   - 证据：`app/main.py` 中多组 `include_router(...)`。
2. **核心执行主链路**：PAS 调 `/process-withdrawal` 入队 -> `ArmWorker.run()` 轮询并执行 flow -> `pas_client.callback_result` 回传结果。  
   - 证据：`app/routers/withdrawal.py::process_withdrawal`、`app/arm_worker.py::run/_process_task`、`app/pas_client.py::callback_result`。
3. **执行逻辑是“数据库驱动”而非硬编码**：`flow_templates/flow_steps/ui_elements/keymaps/swipe_actions` 决定动作。  
   - 证据：`app/arm_worker.py::_execute_task`、`app/actions.py`。
4. **多级 fallback 是兼容策略**：flow 与坐标读取存在 bank/station 通用回退。  
   - 证据：`app/arm_worker.py::_execute_task` 多段查询，`app/actions.py::lookup_ui_element/lookup_swipe` 的 `bank_code IS NULL` 回退。

## B. 不确定但需要人工确认的区域

1. **monitor/builder 路由是否完全依赖网络隔离**（Tunnel + localhost 绑定）而非应用层鉴权。  
   - 证据：提现入口有 `Depends(verify_api_key)`，monitor/coords/flows 等无统一鉴权依赖。
2. **未知 action_type “warning 后成功跳过”是否为历史兼容策略**。  
   - 证据：`app/actions.py::execute_step` 在 `handler is None` 时 `return True`。
3. **`app/models.py` 的部分模型是否保留给仓库外调用**。  
   - 证据：`WithdrawalCallback` / `AccountStatusUpdate` / `AlertMessage` 在仓库内无使用点（需结合脚本/外部服务确认）。

## C. 高/中/低风险问题清单（每条附证据和影响分析）

### 高风险

1. **并发下 `process_id` 判重存在竞态，可能返回 500 而不是业务可预期响应**  
   - 证据：`withdrawal.process_withdrawal` 先 `SELECT` 再 `INSERT`；`transactions.process_id` 为 UNIQUE；`database.execute` 未做唯一键异常转译。  
   - 影响：重复请求高并发冲突时，PAS 侧可能观察到接口异常（500），而不是稳定的 `Duplicate process_id` 业务语义。

### 中风险

1. **运行态支持共享 fallback，但管理态查询不对称**  
   - 证据：执行读取允许 `bank_code IS NULL` 回退；管理 API 仅精确 `bank_code=%s` 查询。  
   - 影响：会出现“系统能跑、后台看不到配置”的认知错位，增加误改与排障成本。

2. **`reorder_steps` 缺少输入完整性校验**  
   - 证据：`app/routers/flows.py::reorder_steps` 仅按传入列表逐条更新，不校验重复/遗漏/归属一致性。  
   - 影响：step 顺序可能被污染，导致执行行为与配置预期不一致。

3. **响应结构风格混用**（Pydantic response_model 与裸 dict 混杂）  
   - 证据：`withdrawal.py` 使用 response_model；monitor/flows/coordinates 大量返回 `{success/error}`。  
   - 影响：调用方解析成本增加，后续接口演进难统一。

### 低风险

1. **文档内数据库表数描述不一致（14 vs 15）**  
   - 证据：`README.md` 与 `db/schema.sql` / `ARCHITECTURE_PLAN.md` 不一致。  
   - 影响：主要是沟通成本，不直接触发线上故障。

2. **日志时间语义与业务时间语义不完全一致**  
   - 证据：业务回调使用 UTC；worker 日志缓冲 `ts` 为本地 `HH:MM:SS`。  
   - 影响：跨系统排障需额外对时。

## D. 冗余代码清单（区分真冗余/疑似冗余/可能有意重复）

1. **真正冗余**：本轮无足够证据判定“可直接删除”的代码。  
2. **疑似冗余（需人工确认）**：`app/models.py` 中 `WithdrawalCallback` / `AccountStatusUpdate` / `AlertMessage` 目前仓库内无引用。  
3. **可能有意重复**：flow 与坐标读取的多级 fallback 查询链，更像兼容策略实现，不建议按普通重复代码处理。

## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）

1. **接口鉴权一致性**：提现入口有强制鉴权，配置与监控路由无统一鉴权策略。  
2. **返回结构一致性**：同服务内并存强类型响应与裸字典返回。  
3. **配置来源一致性**：runtime 支持 fallback，管理接口默认不可见 fallback 数据。  
4. **异常处理一致性**：有的错误转业务返回，有的直接冒泡为 500（例如并发唯一键冲突）。

## F. 最小改动优先级建议（先做什么最安全）

1. **先修并发判重竞态（最小改动、高收益）**：在插入事务时捕获唯一键冲突并返回稳定业务响应。  
2. **再给 reorder 加参数守卫**：校验 step 集合完整性（数量、重复、归属）。  
3. **补“共享配置可见性提示”**：先通过 UI/接口提示说明 fallback 来源，避免误判。  
4. **逐步统一响应结构**：新改动优先统一，旧接口渐进迁移。  
5. **最后收口文档一致性**：统一数据库表数与关键约束描述。

---

## 复核备注（对你上一轮关心点）

- `pause -> idle` 误状态：当前 `pause_arm` 已不再立即写 DB `idle`，该问题在当前代码未复现。  
- `_fail_queued_tasks` 时间：当前实现已使用 UTC（`datetime.now(timezone.utc)`）。
