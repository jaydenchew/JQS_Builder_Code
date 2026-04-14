1	# 代码审计报告（2026-04-14，第四次复核）
     2	
     3	> 基线代码：`origin/main` @ `15ce231`（已重新 fetch + checkout）
     4	> 
     5	> 审计原则：证据优先；不将历史兼容实现直接判错；未确认前不建议删除代码，只标记“疑似冗余/需人工确认”。
     6	
     7	## A. 项目结构与核心流程理解
     8	
     9	1. **单 FastAPI 进程承载多域功能**：Builder（stations/banks/flows/coords/calibration/recorder/stream/opencv）、提现 API、monitor API/WebSocket 统一挂载。  
    10	   证据：`app/main.py` 中多组 `include_router(...)`。
    11	
    12	2. **核心交易链路是“入队 → Worker 执行 → PAS 回调”**：
    13	   - `POST /process-withdrawal` 做校验并写 `transactions`；
    14	   - `ArmWorker.run()` 轮询 `queued` 任务并执行 flow steps；
    15	   - `pas_client.callback_result()` 上报 PAS。  
    16	   证据：`app/routers/withdrawal.py`、`app/arm_worker.py`、`app/pas_client.py`。
    17	
    18	3. **执行逻辑是 DB 驱动 + fallback**：flow template、flow steps、ui_elements、swipe/keymap 均来自数据库，且存在 bank/station fallback。  
    19	   证据：`app/arm_worker.py::_execute_task`、`app/actions.py::lookup_ui_element/lookup_swipe`。
    20	
    21	4. **近期修复已落地（已复核）**：
    22	   - `process_id` 重复在 3 个 INSERT 分支均做 `IntegrityError(1062)` 兜底；
    23	   - `reorder_steps` 已有数量/重复/归属校验；
    24	   - `callback_sent_at` 已改为仅在回调函数返回非空时更新。  
    25	   证据：`app/routers/withdrawal.py`、`app/routers/flows.py`、`app/arm_worker.py`。
    26	
    27	## B. 不确定但需要人工确认的区域
    28	
    29	1. **monitor/builder 接口是否长期依赖网络隔离而非应用鉴权**。  
    30	   证据：`/process-withdrawal`、`/status/{process_id}`有 `verify_api_key`；monitor/flows/coords/stations/banks 路由未统一鉴权。需确认生产是否永远 `127.0.0.1 + Tunnel allowlist`。
    31	
    32	2. **unknown action “warning 后返回成功”是否是业务明确策略**。  
    33	   证据：`app/actions.py::execute_step` 中 `handler is None` 时直接 `return True`。需确认是兼容还是会掩盖配置错误。
    34	
    35	3. **`AUDIT_REPORT_2026-04-14.md`、`AUDIT_REPORT_3.md`、`AUDIT_REPORT_NEW.md` 是否都有保留价值**。  
    36	   证据：仓库根目录存在多份审计文档，内容/版本语义有重叠；但可能用于历史追踪或外部流程，需人工确认再清理。
    37	
    38	## C. 高/中/低风险问题清单（每条附证据和影响分析）
    39	
    40	### 高风险
    41	
    42	1. **PAS 回调“成功判定”未校验 HTTP 状态码，可能把失败当成功**  
    43	   - 证据：`app/pas_client.py::callback_result` 对 `resp` 直接 `return resp.json()`，未做 `resp.raise_for_status()` 或 `2xx` 判断。`app/arm_worker.py` 只判断 `cb_result is not None` 即写 `callback_sent_at`。  
    44	   - 影响：当 PAS 返回 4xx/5xx 但 body 仍是 JSON 时，系统会误记“已回调”，造成对账与补偿逻辑失真。
    45	
    46	### 中风险
    47	
    48	1. **鉴权边界不一致（依赖部署假设）**  
    49	   - 证据：`app/routers/withdrawal.py` 有依赖鉴权，`app/routers/monitor.py` 等管理面接口没有。  
    50	   - 影响：若后续部署从 localhost 漂移到内网可达，存在读交易日志、取截图、控制 arm 等未授权访问面。
    51	
    52	2. **reorder 逐条 UPDATE 无事务包裹，异常时可能出现部分重排**  
    53	   - 证据：`app/routers/flows.py::reorder_steps` 在循环中逐条更新 step_number，没有显式事务边界。  
    54	   - 影响：数据库异常/连接中断时可能留下中间状态，导致流程顺序异常且难复盘。
    55	
    56	3. **运行态 fallback 与管理态可见性不对称**  
    57	   - 证据：`lookup_ui_element/lookup_swipe` 支持 `bank_code IS NULL` 回退；管理接口常按精确 bank_code 查询。  
    58	   - 影响：产生“运行可用但后台不可见”的认知偏差，增加维护误改概率。
    59	
    60	### 低风险
    61	
    62	1. **文档数据库表数量描述不一致（14 vs 15）**  
    63	   - 证据：`db/schema.sql` 注释为 14 tables，README 仍有 15 tables 描述。  
    64	   - 影响：认知噪音，不直接影响执行。
    65	
    66	2. **日志时间字段仅 `HH:MM:SS`，跨日排障可读性一般**  
    67	   - 证据：`WorkerLogHandler.emit` 用 `datetime.now().strftime("%H:%M:%S")`。  
    68	   - 影响：导出/追溯长时段问题时，日志排序与定位成本略高。
    69	
    70	## D. 冗余代码清单（区分真冗余/疑似冗余/可能有意重复）
    71	
    72	1. **真正冗余**：本轮未发现可“直接安全删除”的代码。  
    73	
    74	2. **疑似冗余（需人工确认）**：
    75	   - 多份审计文档并存：`AUDIT_REPORT_2026-04-14.md` / `AUDIT_REPORT_3.md` / `AUDIT_REPORT_NEW.md`；可能是历史留档，也可能是重复产物。
    76	
    77	3. **可能有意重复（兼容/隔离）**：
    78	   - `arm_client.py`、`camera.py` 的类能力与模块级调用并存（兼容旧调用入口）；
    79	   - flow/template 的多段 fallback 查询链（兼容不同 bank/arm/transfer_type 组合）。
    80	
    81	## E. 一致性问题清单（接口、命名、返回结构、配置来源、异常处理）
    82	
    83	1. **接口鉴权一致性**：提现入口强鉴权；监控/配置入口默认无鉴权。  
    84	2. **返回结构一致性**：部分路由使用 response_model，部分返回裸 dict（`success/error`）。  
    85	3. **配置来源一致性**：运行态有 fallback，管理态展示维度不完全对齐。  
    86	4. **异常处理一致性**：回调成功判定基于“非空返回”而非 HTTP 语义；unknown action 默认成功跳过。  
    87	5. **状态时间一致性**：业务时间多数已 UTC 化，但日志时间格式仍偏本地展示。
    88	
    89	## F. 最小改动优先级建议（先做什么最安全）
    90	
    91	1. **先修高风险：回调成功判定改为基于 HTTP 状态码**（最小改动、高收益）  
    92	   - 在 `pas_client.callback_result` 加 `resp.raise_for_status()` 或明确 `if 200<=status_code<300`；
    93	   - 仅在真正成功时返回可用结果，失败统一返回 `None`。
    94	
    95	2. **再做中风险：reorder 加事务包裹**  
    96	   - 保持现有校验逻辑不变，仅把更新循环放入事务，避免部分写入。
    97	
    98	3. **补“可选鉴权开关”而非全面改造**  
    99	   - 对 monitor/配置类路由增加配置开关式鉴权（默认可保持现状），兼容当前 Tunnel 策略。
   100	
   101	4. **最后做低风险收口**  
   102	   - 统一文档中的表数量；
   103	   - 审计文档做版本化命名策略（例如仅保留 latest + history 目录）。