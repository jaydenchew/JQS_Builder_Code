# 代码审计报告（2026-04-14）

## A. 项目结构与核心流程理解

- 单进程 FastAPI 同时承载：Builder 页面、提现执行 API、监控 API/WebSocket、多臂 Worker 管理。入口在 `app/main.py`，通过 `include_router` 组合业务路由。  
- 核心执行链路：`/process-withdrawal` 入队交易（`transactions.status='queued'`）→ `ArmWorker.run` 轮询绑定 arm 的队列 → 读取 `flow_templates + flow_steps` 数据驱动执行 → 成功/失败回调 PAS。  
- 执行步骤由 `app/actions.py` 的 `ACTION_MAP` 映射；坐标、键盘、滑动等均来自 DB 配置（不是硬编码），且包含 bank 级与 station 级 fallback。  
- 硬件调用通过每个 worker 独立 `ThreadPoolExecutor(max_workers=1)` 运行，避免阻塞事件循环。  
- camera/arm 模块保留“类实例 + 模块级默认实例”双轨，以兼容旧调用入口（尤其 recorder/stream）。

## B. 不确定但需要人工确认的区域

1. **未显式引用但可能存在外部入口的方法**  
   - `pas_client.update_account_status` / `send_alert` 当前在 app 内无直接调用；可能由未来任务、脚本、运维命令或未纳入仓库的入口触发。建议标记“需人工确认是否有外部调用方”，不要直接删。  
2. **Flow 步骤类型与来源**  
   - `flow_steps.action_type` 理论受 DB ENUM 限制，但系统允许通过脚本/SQL/历史数据导入写入异常值的可能性。`execute_step` 对未知 action 选择“告警并跳过成功”，需确认是否属于历史兼容策略。  
3. **无鉴权路由是否为内网假设**  
   - 目前仅提现入口和状态查询强制 `verify_api_key`，其余管理/监控接口未统一鉴权。需人工确认部署是否始终在可信内网。

## C. 高/中/低风险问题清单（附证据与影响）

### 高风险

1. **PAS 客户端鉴权头使用不一致，可能导致“部分回调成功、部分接口失败”**  
   - 证据：`callback_result` 明确带 `headers=_auth_headers/_json_headers`；但 `update_account_status`、`send_alert` 调用未传 headers。  
   - 影响：在 PAS 开启鉴权时，会出现提现回调可用，但账户状态更新/告警请求 401 或被拒，形成“功能局部失效且不易第一时间发现”。

2. **Pause 语义与真实执行状态可能不一致（DB 显示 idle，但任务可能仍在跑）**  
   - 证据：`monitor.pause_arm` 调用 `manager.pause()` 后立即把 `arms.status` 写成 `idle`；而 worker 仅在循环开头检查 `_paused`，不能中断当前 `_process_task`。  
   - 影响：监控/UI 或外部系统可能误判 arm 已空闲，触发误操作或人工误判故障时序。

### 中风险

1. **鉴权边界不一致（仅 withdrawal 受 API key 保护）**  
   - 证据：`Depends(verify_api_key)` 仅在 `/process-withdrawal` 与 `/status/{process_id}`；`main.py` 注册了 monitor/stations/banks/flows/coords 等路由但未见统一依赖。  
   - 影响：如果暴露到非完全可信网络，可能发生未授权读取日志、查看截图、修改流程配置甚至操作设备。

2. **坐标读取存在 fallback，但管理接口不对称，易造成“配置可执行但不可见”**  
   - 证据：执行侧 `lookup_ui_element` 支持 `bank_code IS NULL` fallback；而 `GET /api/coords/ui/{bank_code}/{station_id}` 仅查等值 bank_code。  
   - 影响：共享坐标可能在 UI 中看不到，导致“线上能跑、后台看不到配置”的维护困惑，增加误改风险。

3. **reorder 缺少完整性校验，可能生成非连续或冲突 step_number**  
   - 证据：`reorder_steps` 仅按传入列表逐条 UPDATE，不校验是否覆盖模板全部 step、是否重复 ID。  
   - 影响：流程顺序可能进入不一致状态，难复盘；后续编辑/执行依赖 `ORDER BY step_number`，存在行为偏差风险。

4. **回调时间格式在两个路径使用不同时区语义**  
   - 证据：主任务回调时间使用 `datetime.now(datetime.timezone.utc)`；批量拒绝 queued 任务用 `datetime.now()`（本地时区、naive）。  
   - 影响：PAS/日志侧时间线可能出现偏移，尤其跨时区部署时影响排障。

### 低风险

1. **文档中的表数量描述不一致（14 vs 15）**  
   - 证据：README 写“15 tables”，架构文档与 schema 注释都写“14”。  
   - 影响：认知负担与沟通成本上升，但不直接影响运行。

2. **未知 action_type 默认“跳过并判定成功”可读性风险**  
   - 证据：`execute_step` 对未知 action 仅 warning 并 return True。  
   - 影响：问题暴露延后，可能把配置错误隐藏成“偶发行为异常”。

## D. 冗余代码清单（分类）

### 1) 真正冗余（当前证据不足，暂未判定）
- 本轮未发现可直接定性为“可安全删除”的冗余代码。

### 2) 疑似冗余（需人工确认）
- `pas_client.update_account_status`、`pas_client.send_alert`：仓库内无引用，疑似预留接口或历史残留；需确认外部调用后再处理。  

### 3) 可能有意重复（兼容/隔离保留）
- `arm_client.py` 与 `camera.py` 的“类方法 + 模块级同名函数包装”属于兼容层重复，代码注释已声明用于 backward compatibility，不建议直接合并删除。  

## E. 一致性问题清单

1. **接口鉴权一致性**：withdrawal 有鉴权，monitor/stations/banks/flows/coords 默认无鉴权。  
2. **配置来源一致性**：执行侧支持 `ui_elements.bank_code IS NULL` fallback；管理 API 无对应读取维度。  
3. **返回结构一致性**：不同路由混用 `{error: ...}`、`{success: bool}`、Pydantic response model，前端统一处理成本高。  
4. **异常处理一致性**：部分路径“捕获并吞掉异常继续”（如 unknown action skip），部分路径“抛异常导致 stall”；策略差异应文档化。  
5. **时间字段一致性**：UTC 与本地时间混用。

## F. 最小改动优先级建议（先做什么最安全）

1. **先补 PAS headers 一致性（低侵入、高收益）**  
   - 给 `update_account_status` / `send_alert` 增加与 `callback_result` 一致的鉴权头。  
2. **再做状态语义对齐（小改动）**  
   - `pause` 时避免无条件写 `idle`；至少增加“busy 时仅标记 paused_pending”或保持原状态直到当前任务结束。  
3. **补接口边界保护（可配置开关）**  
   - 为 monitor 与配置管理路由增加可选鉴权（先通过配置开关灰度）。  
4. **补 reorder 参数校验**  
   - 校验 `order` 覆盖全集、无重复、只包含当前模板 step。  
5. **最后处理文档和观测性**  
   - 统一“14/15 表”描述；对 unknown action 改为可观测的“可配置失败策略”。
