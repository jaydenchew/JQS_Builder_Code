# AUDIT REPORT

Date: 2026-04-14
Scope: WA Unified System (`app/`, `app/routers/`, `db/schema.sql`, architecture docs)

## A. 项目结构与核心流程理解

### 1) 系统结构（单进程 + 多 worker）
- 服务是单个 FastAPI 进程，启动时加载 DB 连接池并按 `arms.active=1` 启动多臂 worker。核心入口在 `app/main.py`，路由分为：Builder/设置/监控、执行 API（PAS 入口）、静态页面。  
- `WorkerManager` 维护 `arm_id -> ArmWorker` 的内存映射，并负责动态 add/remove、暂停/恢复、offline 切换。  
- `ArmWorker` 串行处理该 arm 的队列任务（单 arm 单 worker），执行 flow steps（CLICK/TYPE/SWIPE/PHOTO/OCR/CHECK_SCREEN），并回调 PAS。  

### 2) 核心业务链路
1. PAS 调 `POST /process-withdrawal`，系统按 `bank_apps -> stations -> arms` 选定 arm，写入 `transactions`（queued）。
2. 对应 `ArmWorker` 轮询 queued 任务，置为 running，选择 flow（优先 arm + transfer_type，再回退 legacy flow）。
3. `actions.execute_step()` 按步骤执行并写 `transaction_logs`；OCR/CHECK_SCREEN 有专门日志路径。
4. 任务完成后由 `pas_client.callback_result()` 回调 PAS（含重试）；写 `callback_sent_at`。
5. 失败路径进入 stall：写 `transactions.status='stall'`、截图、回调 status=4、arm 置 offline 并暂停，同时批量拒绝该 arm 下 queued 任务。

### 3) 关键“看起来不一致但有历史原因”的点（按 ADR）
- 仅 withdrawal/status 做 API key 鉴权；其余管理接口依赖本机/隧道边界。  
- pause 不写 DB 状态（避免运行中任务被误显示为 idle）。  
- SAME/INTER 用 `_inter` 后缀隔离坐标；handler flow 使用独立 bank_code。

---

## B. 不确定但需要人工确认的区域

1) **Pause 期间是否允许继续入队**（需产品/运维确认）  
- 现状：`pause` 仅改内存态，`/process-withdrawal` 只看 DB 的 `active/status`，因此 paused arm 仍可接单入队。  
- 风险取决于运营预期：若 pause 用于短时调试可接受；若用于“停止接单”，则会造成队列堆积误判。  

2) **`health` 暴露策略是否符合对外探活约定**（需与 PAS/网关约定确认）  
- 现状：`/health` 无鉴权并包含 arm 状态摘要。若 tunnel 暴露此路径属设计，但需要确认是否允许外部获取这类运行信息。

3) **共享坐标（`bank_code IS NULL` fallback）是否仍需保留**（需看历史数据）  
- 执行路径保留 fallback，但管理 API 不直接展示 fallback 条目。若未来恢复共享坐标能力，前后端可见性可能不一致。

---

## C. 高/中/低风险问题清单（附证据与影响）

### 高风险

#### HR-1：`create_arm` 启动 worker 失败后，DB 仍保留 active+idle，可能“接单但无人消费”
- 证据：`create_arm` 先插入 `arms(active,status='idle')`，再尝试 `manager.add_worker()`；失败只返回错误，不回滚 `active/status`。  
- 调用链：新增 arm -> 后台 worker 启动失败 -> `/process-withdrawal` 仅检查 `arms.active` 与 `status!='offline'` -> 交易进入 queued，但无 worker 消费。  
- 影响：线上请求被“成功受理”但长期不执行，产生隐性积压与对账风险。

#### HR-2：PAS 回调地址缺失时仍执行 5/15/30s 重试，单笔任务被额外阻塞约 50s
- 证据：`validate_config()` 仅 warning `PAS_API_URL` 未配置；`callback_result()` 无 URL 空值短路，失败后固定重试。  
- 调用链：任务完成 -> callback -> URL 无效失败 -> 50s backoff -> worker 才继续下一笔。  
- 影响：吞吐量急剧下降，队列堆积，且问题在日志层面可能被误认为外部 PAS 抖动。

### 中风险

#### MR-1：`/api/monitor/reset/{arm_id}` 在 async 路由内直接执行阻塞硬件调用
- 证据：`reset_arm` 直接调用 `worker.arm_client.reset_to_origin()` / `close_port()`，未使用 executor。  
- 影响：可能阻塞事件循环；同时与 worker 执行线程并发访问同一硬件实例时，可能触发端口状态竞态（尤其误操作时）。

#### MR-2：`list_transactions` 的 `limit/offset/date_*` 未做边界校验，存在重查询成本风险
- 证据：接口直接拼 where 并使用调用方提供的 `limit/offset`。  
- 影响：大分页或宽日期窗查询可能对生产 DB 造成压力，影响监控页面与任务处理共享资源。

### 低风险

#### LR-1：返回结构长期混用（`status/message` vs `success/error`）
- 证据：withdrawal 路由使用 Pydantic `StandardResponse`；monitor/stations/coords 等大量路由返回裸 dict 且 key 不统一。  
- 影响：前端与调用方需写分支解析，增加维护成本；但属已记录的渐进迁移策略。

#### LR-2：部分 endpoint 异常处理风格不一致（返回 error dict 而非 HTTP 状态码）
- 证据：多个 CRUD 路由在失败时返回 `{"error": ...}` 200 响应。  
- 影响：上层自动化监控难基于 HTTP code 做统一告警。

---

## D. 冗余代码清单（真冗余 / 疑似冗余 / 可能有意重复）

### 1) 真冗余（当前证据下可判定）
- **未发现可直接判定且可安全删除的“真冗余”**。当前代码中多数“重复”与兼容回退链路有关。

### 2) 疑似冗余（需人工确认后再动）
- `monitor.py` 导出的部分查询/日志接口与 `transactions` 页面数据聚合存在能力重叠；是否有外部脚本依赖这些 endpoint 需先确认。  
- `flow_templates` 查询链中 `transfer_type` + `arm_id` 的多级 fallback 逻辑较长，可能存在历史兼容层叠；在缺少线上模板分布统计前不建议收敛。

### 3) 可能有意重复（兼容/隔离）
- SAME/INTER step 名称后缀策略（`_inter`）与 handler flow bank_code 分离属于明确隔离设计，不应视为重复坏味道。  
- `lookup_ui_element/lookup_swipe` 的 `bank_code IS NULL` fallback 为历史兼容入口，尽管 UI 层不突出展示，仍可能被旧数据使用。

---

## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）

1) **接口返回结构不一致**：
- 外部 API（withdrawal/status/health）是 Pydantic 模型；内部 API 多为 `{success}` / `{error}` / 直接数组。  
- 建议：先给管理 API 增加统一 envelope（不破坏旧字段），逐步迁移。

2) **状态语义分层不一致**：
- DB `arms.status` 与 worker memory status（paused/busy/idle/offline）并存。Dashboard 合并展示是正确方向，但 API 消费方容易误读。  
- 建议：为外部调用方定义“可接单状态”派生字段，避免直接拼装判断。

3) **配置缺失的 fail-fast 策略不一致**：
- `WA_API_KEY` 缺失会 503（fail-fast）；`PAS_API_URL` 缺失仅 warning（fail-late + 重试阻塞）。  
- 建议：对回调关键配置增加启动时硬失败开关（生产默认开启）。

4) **异常表达不一致**：
- 同类错误在不同路由中分别用 200+error body、401/503、或抛异常。  
- 建议：为“业务失败”和“系统失败”建立统一约定（至少内部 API 先做一层标准化）。

---

## F. 最小改动优先级建议（先做什么最安全）

1) **P0（最安全、收益高）**：修复 HR-1  
- `create_arm` worker 启动失败时自动把该 arm 标为 `active=0,status='offline'`（或事务回滚创建）。
- 这是局部改动，不触碰执行主流程，能直接避免“接单无人处理”。

2) **P0（最安全、收益高）**：修复 HR-2  
- 在 `callback_result()` 前增加 `PAS_API_URL` 空值短路（立即失败，不进入 backoff）并打明确告警。  
- 可避免每笔额外 50s 阻塞。

3) **P1**：修复 MR-1  
- `reset_arm` 改为通过 worker executor 执行，或要求 arm 必须 paused/offline 才允许 reset。  
- 降低事件循环阻塞与并发硬件调用风险。

4) **P2**：修复 MR-2  
- 给 `limit/offset/date` 加硬阈值与默认上限，避免监控查询拖垮 DB。

5) **P3（渐进治理）**：统一内部 API envelope 与错误码语义  
- 不做“全面重构”，先新增兼容字段并在前端逐页切换。