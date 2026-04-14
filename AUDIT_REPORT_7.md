AUDIT_REPORT_2026-04-14.md
     1	# 代码审计报告（2026-04-14，第七次复核）
     2	
     3	> 复核说明：本次按“证据优先、谨慎定性、不过度重构”原则重新审计。  
     4	> 结论摘要：**本轮未发现新的“必须立即修复”的严重行为缺陷**；多项历史问题已在前几轮修复，剩余主要为架构取舍或维护性议题。
     5	
     6	---
     7	
     8	## A. 项目结构与核心流程理解
     9	
    10	1. **单进程聚合服务**：Builder/Monitor/Withdrawal API 在同一 FastAPI 进程注册，Worker 由 lifespan 启动。  
    11	   - 证据：`app/main.py` 的 `include_router(...)` 与 `manager.start_all()`/`manager.stop_all()` 生命周期调用。
    12	2. **核心提现链路**：`/process-withdrawal` 入队（或失败落库）→ `ArmWorker` 轮询 `queued` 任务执行 flow → 回调 PAS。  
    13	   - 证据：`app/routers/withdrawal.py::process_withdrawal`、`app/arm_worker.py::_fetch_next_task/_process_task`、`app/pas_client.py::callback_result`。
    14	3. **“每 arm 单 worker”是显式架构约束**：`workers` 以 `arm_id` 唯一索引，已存在时不会重复创建。  
    15	   - 证据：`app/worker_manager.py` 的 `self.workers` 字典、`add_worker` 中 `if arm_id in self.workers: return True`。
    16	4. **配置驱动 + fallback 执行模型**：运行态允许 bank/station fallback（例如 `bank_code IS NULL`），以兼容共享坐标/动作配置。  
    17	   - 证据：`app/actions.py::lookup_ui_element/lookup_swipe`。
    18	
    19	---
    20	
    21	## B. 不确定但需要人工确认的区域
    22	
    23	1. **监控/配置接口是否永久依赖网络边界隔离（Tunnel + localhost）**  
    24	   - 证据：提现和状态接口有 `verify_api_key`，但 monitor/flows/coords 等路由未统一鉴权。  
    25	   - 需要确认：这是否是你们长期的部署契约（而非临时环境假设）。
    26	2. **`pause/resume` 的 DB 状态语义是否定义为“运营态可读”而非“严格运行态”**  
    27	   - 证据：`pause` 与 `resume` 都会把 `arms.status` 写成 `idle`。  
    28	   - 需要确认：你们是否接受短暂 `idle -> busy` 切换用于运营可视化，而非精确反映每毫秒执行态。
    29	3. **PAS 扩展接口调用来源**（`update_account_status`、`send_alert`）  
    30	   - 证据：函数存在，但当前主执行链路只见 `callback_result`。  
    31	   - 需要确认：是否由外部脚本/运维任务调用。
    32	
    33	---
    34	
    35	## C. 高/中/低风险问题清单（每条附证据和影响分析）
    36	
    37	### 高风险
    38	
    39	**本轮未发现新的高风险“线上行为不一致/立即致 bug”项。**
    40	
    41	> 注：此前反复出现的“同 arm 多 worker 抢任务”推断，本轮按代码证据不成立（单 arm 单 worker 约束明确）。
    42	
    43	### 中风险
    44	
    45	1. **执行侧 fallback 与管理侧可见性不对称（维护认知风险）**  
    46	   - 证据：运行态查找支持 `bank_code IS NULL` 回退（`actions.py`）；管理接口普遍按具体 bank 查询。  
    47	   - 影响：可能出现“运行有效但后台不可见”的排障困惑与误改风险。
    48	
    49	2. **响应结构长期混用（演进成本）**  
    50	   - 证据：`withdrawal.py` 使用 `response_model`；多个管理/监控接口直接返回 `{success/error}` 或原始 dict。  
    51	   - 影响：前端/调用方统一处理成本高，后续接口治理阻力较大。
    52	
    53	3. **时间语义仍有局部混用（可观测性成本）**  
    54	   - 证据：主任务 PAS 回调使用 UTC 字符串（`datetime.now(timezone.utc)`）；`_fail_queued_tasks` 仍使用本地 `datetime.now()`。  
    55	   - 影响：跨系统对时与事件线复盘复杂度上升。
    56	
    57	### 低风险
    58	
    59	1. **文档一致性问题（14 vs 15 tables）**  
    60	   - 证据：`README.md` 写 15 表；`db/schema.sql` 注释写 14 表。  
    61	   - 影响：主要是沟通噪音，不影响运行。
    62	
    63	2. **监控 WebSocket 参数入口风格偏松**  
    64	   - 证据：`/api/monitor/logs/ws` 的 `arm_id` 通过函数参数接收，行为上可用但约束文档较弱。  
    65	   - 影响：可维护性/可理解性问题，非当前线上故障来源。
    66	
    67	---
    68	
    69	## D. 冗余代码清单（区分真冗余/疑似冗余/可能有意重复）
    70	
    71	1. **真正冗余**：本轮未发现“可在当前证据下直接删除”的代码。  
    72	2. **疑似冗余（需人工确认）**：`pas_client.update_account_status`、`pas_client.send_alert`（仓库主链路未见调用）。  
    73	3. **可能有意重复（兼容/隔离）**：执行层多级 fallback 与模块包装风格，倾向于兼容性保留，不建议贸然删改。
    74	
    75	---
    76	
    77	## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）
    78	
    79	1. **接口鉴权一致性**：仅提现相关接口强制 API key，Builder/monitor 走网络边界隔离模型。  
    80	2. **返回结构一致性**：强类型模型与裸 dict 混用。  
    81	3. **配置来源一致性**：运行态支持 fallback，管理态可见性不完全覆盖 fallback 来源。  
    82	4. **时间处理一致性**：同一业务域内 UTC 与本地时间并存。  
    83	5. **状态语义一致性**：`arms.status` 与 worker 实时态是“近似同步”而非严格一致（需产品/运维共识）。
    84	
    85	---
    86	
    87	## F. 最小改动优先级建议（先做什么最安全）
    88	
    89	> 按“低改动、可回退、不改核心架构”排序。
    90	
    91	1. **先收口审计口径（治理动作）**：把“每 arm 单 worker”写入审计前置假设，避免后续重复报伪风险。  
    92	2. **可选：统一 `_fail_queued_tasks` 时间到 UTC**（1 行级改动，收益在对时一致性）。  
    93	3. **可选：给 fallback 数据加“来源提示”而不是改执行逻辑**（降低维护误判）。  
    94	4. **文档小修**：统一 README 与 schema 的表数量描述。  
    95	5. **暂不建议**：基于当前部署模型，不建议做“全端点强鉴权/大规模响应结构重构”这类高改动项。
    96	
    97	---
    98	
    99	## 本轮结论（可执行摘要）
   100	
   101	- 第七次复核**未发现新的严重行为缺陷**。  
   102	- 当前剩余事项以“可维护性一致性”与“文档/可观测性”为主。  
   103	- 建议进入“低风险小修 + 审计口径固化”阶段，而非继续大范围安全重构。