AUDIT_REPORT_2026-04-14.md
     1	# 代码审计报告（2026-04-14，第三次复核）
     2	
     3	> 基线代码：`origin/main` @ `517e2ed`（已先 fetch + checkout）
     4	> 
     5	> 审计原则：证据优先；不把历史兼容实现直接判错；无足够证据不建议删除，仅标记“疑似冗余/需人工确认”。
     6	
     7	## A. 项目结构与核心流程理解
     8	
     9	1. **单 FastAPI 进程聚合多域能力**：Builder（stations/banks/flows/coords/calibration/stream/recorder/opencv）、提现执行、monitor 全部在一个进程中挂载。  
    10	   证据：`app/main.py` 的多组 `include_router(...)`。
    11	
    12	2. **核心交易链路是“入队 + worker 消费 + 回调”**：
    13	   - `POST /process-withdrawal` 完成校验并写 `transactions`；
    14	   - `ArmWorker.run()` 轮询并执行 `flow_steps`；
    15	   - 执行结果通过 `pas_client.callback_result` 回传 PAS。  
    16	   证据：`app/routers/withdrawal.py`、`app/arm_worker.py`、`app/pas_client.py`。
    17	
    18	3. **运行行为强依赖数据库配置**：流程模板、动作步骤、坐标、键盘、滑动均由 DB 驱动，且存在 bank/station 维度 fallback。  
    19	   证据：`app/arm_worker.py::_execute_task`、`app/actions.py::lookup_ui_element/lookup_swipe`。
    20	
    21	4. **近期修复已生效**：
    22	   - `process_id` 并发重复兜底（3 个 INSERT 都有 1062 捕获）；
    23	   - `reorder_steps` 已加入基本完整性校验；
    24	   - `_fail_queued_tasks` 已统一 UTC。  
    25	   证据：`app/routers/withdrawal.py`、`app/routers/flows.py`、`app/arm_worker.py`。
    26	
    27	## B. 不确定但需要人工确认的区域
    28	
    29	1. **monitor/builder 接口是否长期依赖网络隔离而非应用鉴权**  
    30	   - 提现入口有 `verify_api_key`，但多数管理/监控路由无鉴权。  
    31	   - 若部署始终是 `127.0.0.1 + Tunnel path allowlist`，可接受；若偶发回到 `0.0.0.0` 或共享局域网，风险显著上升。  
    32	   证据：`app/routers/withdrawal.py` 对比 `app/routers/monitor.py`/`app/routers/coordinates.py`/`app/routers/flows.py`。
    33	
    34	2. **Unknown action 跳过是否是明确兼容策略**  
    35	   - 当前未知 `action_type` 仅告警并返回成功。  
    36	   - 这可能是“容错兼容”，也可能隐藏模板配置错误。需产品/运维确认策略。  
    37	   证据：`app/actions.py::execute_step`。
    38	
    39	3. **外部入口可能性（隐式调用）仍需人工确认**  
    40	   - 仓库内未发现某些“看似预留”路径的调用，不代表外部脚本/运维任务/Webhook 不会触发。  
    41	   - 此项按“需人工确认”处理，不建议据此直接删代码。
    42	
    43	## C. 高/中/低风险问题清单（每条附证据和影响分析）
    44	
    45	### 高风险
    46	
    47	1. **PAS 回调失败与 `callback_sent_at` 标记可能不一致**  
    48	   - 行为：`pas_client.callback_result` 失败时仅 `return None`；`arm_worker` 在未检查回调结果的情况下仍更新 `callback_sent_at = NOW()`。  
    49	   - 证据：`app/pas_client.py`（失败返回 None） + `app/arm_worker.py`（三条路径均“先 callback，再无条件写 callback_sent_at”）。  
    50	   - 影响：DB 显示“已回调”，但 PAS 实际未收到，导致对账/重试策略失真，属于真实线上一致性风险。
    51	
    52	### 中风险
    53	
    54	1. **鉴权边界不统一（依赖部署假设）**  
    55	   - 证据：仅提现相关路由挂 `verify_api_key`，监控和配置接口无统一鉴权依赖。  
    56	   - 影响：一旦网络边界配置漂移，存在读取交易日志/截图、修改流程配置等未授权访问面。
    57	
    58	2. **执行侧 fallback 与管理侧展示不对称**  
    59	   - 证据：运行时支持 `bank_code IS NULL` 回退；管理查询默认按 `bank_code=%s` 精确过滤。  
    60	   - 影响：出现“能执行但后台看不到”的运维认知差，增加误改概率与排障时间。
    61	
    62	3. **`resume` 状态写库可能与真实运行态短暂偏离**  
    63	   - 证据：`resume_arm` 成功后直接写 `arms.status='idle'`；但 worker 可能刚恢复即取到任务进入 busy。  
    64	   - 影响：监控上短时间状态闪烁/误判，虽然通常可自愈，但会影响人工判断。
    65	
    66	### 低风险
    67	
    68	1. **文档数据库表数描述不一致（14 vs 15）**  
    69	   - 证据：`README.md` 为 15，`schema/ARCHITECTURE_PLAN` 为 14。  
    70	   - 影响：认知噪音，不直接影响运行。
    71	
    72	2. **响应结构风格混用**  
    73	   - 证据：withdrawal 使用 response_model；多数管理路由返回裸 `{success/error}`。  
    74	   - 影响：调用方处理分支增多，扩展成本偏高。
    75	
    76	## D. 冗余代码清单（区分真冗余/疑似冗余/可能有意重复）
    77	
    78	1. **真正冗余**：本轮无足够证据判定“可直接安全删除”的代码。  
    79	
    80	2. **疑似冗余（需人工确认）**：
    81	   - 暂未新增可直接定性的疑似冗余项；上一轮已删除的未引用 Pydantic 模型在当前代码中已不存在。  
    82	   - 对“仓库内无引用”的任何项，仍需结合部署脚本/定时任务/外部调用再判断。
    83	
    84	3. **可能有意重复（兼容/隔离）**：
    85	   - flow/坐标多级 fallback 查询链；
    86	   - 硬件执行层的适配写法。  
    87	   这些更像兼容与隔离策略，不建议按“重复代码”直接清理。
    88	
    89	## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）
    90	
    91	1. **接口鉴权一致性**：提现入口强鉴权，配置/监控入口默认弱鉴权（依赖网络边界）。  
    92	2. **返回结构一致性**：response_model 与裸字典混用。  
    93	3. **配置来源一致性**：runtime fallback 与管理端可见性不一致。  
    94	4. **异常处理一致性**：回调失败与 DB 标记“已发送”不一致；unknown action 默认成功需策略确认。  
    95	5. **状态一致性**：`resume` 时 DB 状态写入与 worker 实时状态可能短暂偏离。
    96	
    97	## F. 最小改动优先级建议（先做什么最安全）
    98	
    99	1. **先修高风险：回调结果与 `callback_sent_at` 一致性**  
   100	   - 仅在 PAS 回调成功（或状态码可接受）后写 `callback_sent_at`；失败时保留未发送状态并记录错误。  
   101	   - 这是最小改动、最高收益。
   102	
   103	2. **再做中风险：`resume` 状态语义微调**  
   104	   - 减少手工写 `idle` 的时机，或由 worker 周期状态回写主导，避免闪烁误判。
   105	
   106	3. **补“可选鉴权开关”而非全面重构**  
   107	   - 先给 monitor/配置路由提供可配置鉴权（默认可关），满足不同部署形态。
   108	
   109	4. **最后做低风险收口**  
   110	   - 文档表数统一；
   111	   - 响应结构在新增接口中渐进统一，不建议一次性重构。
[audit3 f7029de] docs: add third-pass audit report after syncing origin/main
 1 file changed, 83 insertions(+), 62 deletions(-)
f7029de docs: add third-pass audit report after syncing origin/main
517e2ed fix: audit round 2 — race condition, reorder validation, dead model cleanup
1fb94df feat: camera buffer fix, ui_element redesign, keyboard space, audit fixes