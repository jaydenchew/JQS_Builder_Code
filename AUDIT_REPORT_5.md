     1	# 代码审计报告（2026-04-14，第五次复核）
     2	
     3	> 基线代码：`origin/main` @ `b0473c4`（已重新 fetch + reset 后复核）  
     4	> 审计原则：证据优先；不把历史兼容实现直接判错；无充分证据前不建议删除代码，仅标记“疑似冗余/需人工确认”。
     5	
     6	## A. 项目结构与核心流程理解
     7	
     8	1. **单 FastAPI 进程聚合多域能力**：Builder 配置、提现执行 API、监控 API/WebSocket 在同一进程内。  
     9	   - 证据：`app/main.py` 中统一 `include_router(...)` 挂载 stations/banks/flows/coordinates/withdrawal/monitor。
    10	
    11	2. **核心业务主链路仍是“入队 -> Worker 执行 -> PAS 回调”**。  
    12	   - 入队：`POST /process-withdrawal` 做业务校验并写 `transactions`（queued/failed）。  
    13	   - 执行：`ArmWorker.run()` 轮询 `queued`，逐 step 执行。  
    14	   - 回调：`pas_client.callback_result()` 上报结果并按返回更新 `callback_sent_at`。  
    15	   - 证据：`app/routers/withdrawal.py`、`app/arm_worker.py`、`app/pas_client.py`。
    16	
    17	3. **流程执行是 DB 驱动 + fallback 兼容策略**。  
    18	   - `flow_templates` 支持 bank/arm/transfer_type 多级回退；  
    19	   - `ui_elements/swipe_actions` 支持 `bank_code IS NULL` 共享配置回退。  
    20	   - 证据：`app/arm_worker.py::_execute_task`、`app/actions.py::lookup_ui_element/lookup_swipe`。
    21	
    22	4. **第四次审计相关修复已落地并复核通过**。  
    23	   - PAS 回调已检查 HTTP 状态码（非 2xx 返回 None）；  
    24	   - `reorder_steps` 已加事务；  
    25	   - `process_id` 三个 INSERT 分支已加 `IntegrityError(1062)` 兜底。  
    26	   - 证据：`app/pas_client.py`、`app/routers/flows.py`、`app/routers/withdrawal.py`。
    27	
    28	## B. 不确定但需要人工确认的区域
    29	
    30	1. **监控/配置路由是否永久依赖“网络边界隔离”而非应用鉴权**。  
    31	   - 证据：`withdrawal` 路由有 `Depends(verify_api_key)`；`monitor/flows/coordinates/stations/banks` 未统一加鉴权依赖。  
    32	   - 需确认：生产是否始终保证 `localhost/Tunnel allowlist`，并可防局域网侧直连。
    33	
    34	2. **未知 action_type 跳过并判成功是否为既定业务策略**。  
    35	   - 证据：`app/actions.py::execute_step` 在 `handler is None` 时 `warning + return True`。  
    36	   - 需确认：这是历史兼容（允许灰度配置）还是会掩盖配置错误。
    37	
    38	3. **审计文档多版本共存是否有流程要求**。  
    39	   - 证据：仓库根目录已有 `AUDIT_REPORT_4.md` 与本次新增 `AUDIT_REPORT_5.md`。  
    40	   - 需确认：是否需要保留全量审计历史，或转移到归档目录。
    41	
    42	## C. 高/中/低风险问题清单（每条附证据和影响分析）
    43	
    44	### 高风险
    45	
    46	1. **`resume` 后 DB 仍可能保持 `offline`，导致“Worker 已恢复但新请求仍被拒绝”**  
    47	   - 证据链：  
    48	     - 任务失败时，worker 会把 `arms.status` 写成 `offline` 且 `_paused=True`：`app/arm_worker.py`。  
    49	     - `/api/monitor/resume/{arm_id}` 只执行 `manager.resume()` 后 `UPDATE arms SET active=1`，未把 `status` 从 `offline` 改回 `idle/busy`：`app/routers/monitor.py`。  
    50	     - 新提现请求在入队前会检查 `arms.status == 'offline'` 并直接失败：`app/routers/withdrawal.py`。  
    51	   - 影响：监控面显示“已 resume”，但业务面仍持续返回“Assigned arm is offline or inactive”，属于线上行为不一致。
    52	
    53	2. **批量拒绝 queued 任务时，`callback_sent_at` 仍可能被误记为已发送**  
    54	   - 证据链：  
    55	     - `_fail_queued_tasks` 中调用 `pas_client.callback_result(...)` 后无返回值判断，直接更新 `callback_sent_at`：`app/arm_worker.py`。  
    56	     - `callback_result` 对非 2xx 或异常会返回 `None`：`app/pas_client.py`。  
    57	   - 影响：PAS 实际未收到回调时，数据库仍显示“已回调”，会影响补偿、对账和故障定位。
    58	
    59	### 中风险
    60	
    61	1. **鉴权边界不一致，安全前提高度依赖部署约束**  
    62	   - 证据：仅 `process-withdrawal/status` 强制 API key，monitor + 配置管理接口无统一鉴权。  
    63	   - 影响：若部署策略漂移（例如服务绑定 `0.0.0.0` 且在共享网络），可能暴露交易日志、截图和控制接口。
    64	
    65	2. **运行态 fallback 与管理态查询不对称**  
    66	   - 证据：执行侧支持 `bank_code IS NULL` fallback（actions）；管理侧 `coordinates` 多为 bank+station 精确查询。  
    67	   - 影响：出现“线上可执行、后台查不到”的认知偏差，维护时易误改。
    68	
    69	3. **Unknown action 默认成功跳过降低错误显性化**  
    70	   - 证据：`app/actions.py::execute_step` 的 unknown action 直接返回成功。  
    71	   - 影响：配置错误可能延迟暴露为后续步骤异常，增加排障成本。
    72	
    73	### 低风险
    74	
    75	1. **README 与实际部署基线描述不一致**  
    76	   - 证据：README 手动启动示例仍是 `--host 0.0.0.0`；服务脚本也默认 `0.0.0.0`。  
    77	   - 影响：在“共享局域网 + 无统一接口鉴权”场景下，误导性较高，增加运维误配置概率。
    78	
    79	2. **文档中的数据库表数量描述存在噪音**  
    80	   - 证据：`README.md` 写 15 tables；`db/schema.sql` 注释写 14 tables。  
    81	   - 影响：认知成本问题，不直接造成运行故障。
    82	
    83	## D. 冗余代码清单（区分真冗余/疑似冗余/可能有意重复）
    84	
    85	1. **真正冗余**：本轮未发现有充分证据可“直接安全删除”的代码。  
    86	
    87	2. **疑似冗余（需人工确认）**：
    88	   - 根目录多份审计报告（`AUDIT_REPORT_4.md`、`AUDIT_REPORT_5.md`）可能是历史留档，也可能是重复产物；需按团队文档策略确认。
    89	
    90	3. **可能有意重复（兼容/隔离保留）**：
    91	   - `arm_client.py`、`camera.py` 的类实现 + 模块级默认实例包装明确标注 backward compatibility；
    92	   - flow/template 与坐标读取中的多段 fallback 查询链是兼容策略，不建议直接去重。
    93	
    94	## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）
    95	
    96	1. **接口鉴权一致性**：提现入口强鉴权，管理/监控入口默认无鉴权。  
    97	2. **返回结构一致性**：`response_model` 与裸字典 `{success/error}` 混用。  
    98	3. **配置来源一致性**：运行态存在 fallback，管理态默认不可见 fallback 层。  
    99	4. **异常处理一致性**：主流程 callback 已按 HTTP 语义判定；但 `_fail_queued_tasks` 分支仍“未判定即记回调成功”。  
   100	5. **运行状态一致性**：`resume` 的内存状态与 DB `arms.status` 可能不同步。
   101	
   102	## F. 最小改动优先级建议（先做什么最安全）
   103	
   104	1. **先修高风险 1（resume 状态同步）**：  
   105	   - 在 `resume_arm` 成功后，除 `active=1` 外同步更新 `arms.status='idle'`（或按 worker 当前态写入）。
   106	
   107	2. **再修高风险 2（queued 批量回调的 sent_at 语义）**：  
   108	   - `_fail_queued_tasks` 中仿照主流程：仅 `callback_result` 返回非空时更新 `callback_sent_at`。
   109	
   110	3. **中风险收口（低侵入）**：  
   111	   - 保持当前网络隔离方案不变的前提下，为 monitor/配置路由提供“可配置鉴权开关”；
   112	   - 给管理界面增加“当前数据来自 fallback”提示，降低误判。
   113	
   114	4. **最后做低风险文档对齐**：  
   115	   - README 与部署脚本默认 host 策略统一；
   116	   - 统一表数量描述（14/15）。