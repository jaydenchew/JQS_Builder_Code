# JQS_Builder_Code — Code Review 报告
 
## Context
 
本仓库是一个**物理 RPA 系统**:机械臂物理点击手机屏幕执行银行转账(柬埔寨银行多数没有开放 API)。系统通过 PAS(Payment Aggregation System)接收提款请求,排队后由机械臂在真实手机上完成操作,USB 摄像头拍照,OCR 校验结果,再回调 PAS。**任何 bug 都可能导致真实资金损失。**
 
本次 review 已阅读:
- `.agent/workflows/wa-system.md`(必读)
- `BUSINESS_CONTEXT.md`、`DESIGN_DECISIONS.md`(14 个 ADR)、`ARCHITECTURE_PLAN.md`、`API_SPEC.md`、`AUDIT_REPORT_7.md`
 
并已对照 ADR 确认以下行为**不是 bug,不应被 flag**:
- DD-001 仅 PAS 端点加认证(其他靠 localhost + Cloudflare Tunnel 边界)
- DD-003 未知 action 类型静默成功(forward-compat)
- DD-008 `capture_fresh()` 每次重开摄像头(DSHOW buffer)
- DD-009 SAME/INTER flow 用 `_inter` 后缀
- DD-012 失败永不自动重试(防止双付)
 
---
 
## 整体评估
 
架构合理、文档完善、ADR 齐全。AUDIT_REPORT_7 的三条 medium 已体现在代码中(UTC 时间统一、fallback 可见性、响应结构不一致)。本轮 review 发现 **1 个 Critical、5 个 High、6 个 Medium、若干 Low** 级别问题。**核心财务路径(回调、process_id 去重)设计正确**,不存在真正的双付风险。主要风险集中在**日志泄漏、内部 XSS、工具脚本硬编码凭据**。
 
---
 
## CRITICAL
 
### C1. 银行密码以明文写入日志
- **文件**:`app/actions.py:133, 136, 140`
- **说明**:`execute_type()` 中 `text` 由 `get_dynamic_value(step["input_source"], transaction, password, bank_code)` 返回。当 `input_source == "password"` 时,`text` 就是银行 App 的真实密码,却被 `logger.info("TYPE '%s' ...", text, ...)` 直接打印。
- **影响**:持久化日志里出现明文银行密码,违反 PCI-DSS,日志若外泄即等于账户失守。这**不**属于任何 ADR 豁免行为。
- **推荐方向**:在 `execute_type` 开头根据 `step["input_source"] in ("password", "pin")` 用 `"***"` 或长度占位替换;同样检查 `keyboard_engine` 里是否也打印 `text`。
 
---
 
## HIGH
 
### H1. Dashboard 存在内部 XSS(step/error 字段未转义)
- **文件**:`static/index.html:159-163`
- **说明**:`${a.current_task}` / `${a.current_step}` / `${a.last_error}` 直接插入模板字符串到 innerHTML。这些字段来源:
  - `current_task` = 流程步 `description`(Builder UI 任意输入)
  - `last_error` = Python 异常 `str(e)`(可含 OCR 文本、path)
- 只要 Builder 里有人(或通过未认证的 recorder API)录入 `<img onerror=...>` 名字的 step,就在 Dashboard 上触发 XSS。
- **缓解**:Dashboard 仅内网可达(DD-001),攻击面窄,但仍应转义。
- **修复方向**:加 `escHtml()` 或改用 `textContent`。
 
### H2. 工具脚本硬编码数据库密码
- **文件**:
  - `tools/copy_arm_data.py:50`
  - `tools/import_flows.py:6`
  - `tools/insert_acleda_mappings.py:3`
- **说明**:三处写死 `password='wa_unified_2026'`(与生产 DB 同值)。
- **影响**:仓库若被分发/泄漏即等于泄密;且每次改密码三处都要手改。
- **修复方向**:统一走 `app.database` 或读 `.env`,并确认 `.env` 已在 `.gitignore`。
 
### H3. `list_bank_apps` 返回明文 password/pin
- **文件**:`app/routers/banks.py:122-131`(`SELECT ba.*`)
- **说明**:查询 Bank Apps 时把 `password`、`pin` 一起返回到前端,`static/settings.html` 里很可能明文渲染。即便是内网,也无需在列表接口带出凭据。
- **修复方向**:明确列出需要的字段,或屏蔽为 `"***"`;在编辑时单独提供一个 `/apps/{id}/reveal` 接口。
 
### H4. `callback_sent_at` 写入与回调不是原子
- **文件**:`app/arm_worker.py:169-213`(三分支:成功、OCR 成功、stall)
- **说明**:流程是 ① 更新 `status` → ② 调 PAS 回调 → ③ 成功才写 `callback_sent_at`。若 ② 成功后进程崩溃,数据库里就是 `status='success' AND callback_sent_at IS NULL`,没有任何机制再修正或对账。
- **为何不是 Critical**:重启后 `_fail_queued_tasks` 只处理 `queued`,不会对 `success/stall` 二次回调,所以**不会双付、不会双回调**。仅是一条观测/对账盲点。
- **修复方向**:把 callback 结果与状态合并在一条 UPDATE 里(先调用 PAS,再一次性写 `status + callback_sent_at + finished_at`);或加后台巡检补发。
 
### H5. `_process_task` 假设 task 字段齐全
- **文件**:`app/arm_worker.py`(`_process_task` 开头,读取 `task["password"]`、`task["process_id"]`、`task["pay_from_bank_code"]`)
- **说明**:这些字段不存在时直接 `KeyError`,落到外层 `except Exception`(148 行附近),机械臂立即 pause。正常情况下 `withdrawal.py` 已经保证字段齐全,但手工补录、迁移脚本、partial 事务都可能出现异常行。
- **修复方向**:在取值处 `.get()` 并 `raise ValueError("missing field X")`,触发正常 stall 路径而不是裸 KeyError。
 
### H6. `_execute_task` 异常捕获过于宽泛
- **文件**:`app/arm_worker.py:140-149`
- **说明**:只有 `RuntimeError("port open failed"/"not responding")` 触发 30s 等待,其他所有 `Exception`(含瞬时 DB 抖动、asyncio 超时、socket 断开)都会立即把机械臂标成 offline 需要人工介入。
- **影响**:生产运营负担、误 stall 率高。与 DD-012(不自动重试**事务**)不矛盾——瞬时基础设施错误不是"事务失败",可以安全重试当前 step。
- **修复方向**:对 `ConnectionError / asyncio.TimeoutError / pymysql.OperationalError` 区别处理(短等后重试同一 step),而非直接脱产。
 
---
 
## MEDIUM
 
### M1. Stall 照片覆盖已有 receipt 截图
- **文件**:`app/arm_worker.py:201-207`
- **说明**:失败分支里 `stall_screenshot` 若非 None 就覆盖 `receipt_b64`,然后写入 DB。早前 PHOTO step 已保存的截图会被覆盖,人工排查时丢失失败瞬间之前的状态。
- **修复方向**:保留原 `receipt_base64`,把 stall 照片写到新字段(如 `stall_screenshot`)。
 
### M2. OCR 回执关键字优先级导致误判
- **文件**:`app/ocr.py`(receipt status 关键字循环)
- **说明**:若屏幕同时出现 "Review" 和 "Failed"(例如 "Review pending – Failed retry"),按关键字列表顺序先命中就返回,可能把**失败**误判为 **pending**。
- **修复方向**:用权重/优先级(failed 优先于 review 优先于 success),或按在屏上的坐标/区域判定。
 
### M3. Handler flow 的 bank_code 未校验
- **文件**:`app/actions.py`(`_run_handler_flow`,约 364 行)
- **说明**:从 `handler_flow_ref` 用 `split("__")[0]` 取 bank,格式错时不会报错,直接拿到 `"INVALID"` 去查 UI elements,全部 miss 后静默失败。
- **修复方向**:`len(parts) == 2` 校验 + bank_code 白名单校验。
 
### M4. `saveFlow()` 的删-插非事务
- **文件**:`static/recorder.html`(保存流程的 `DELETE from flow_steps` + 多次 `INSERT`)
- **说明**:若 INSERT 中途失败(网络/校验),flow_template 只剩空 steps,线上执行即 stall。
- **修复方向**:后端提供一个 `replace_flow_steps` 事务端点,前端只打一次请求。
 
### M5. Schema:`transactions.bank_app_id` / `station_id` 允许 NULL
- **文件**:`db/schema.sql`
- **说明**:`withdrawal.py` 的 "Bank app not found" 分支会插入这两个字段为 NULL,导致 monitor/对账查询里 JOIN 失败、审计链断裂。
- **修复方向**:要么改成 NOT NULL + 把"bank app not found"写入一张独立的 `rejected_requests` 表,要么给这两列加 `NOT NULL DEFAULT 0` 哨兵值。
 
### M6. 关键外键缺索引
- **文件**:`db/schema.sql`
- **说明**:`transactions.station_id`、`transactions.bank_app_id` 仅用于 JOIN,没有索引;Dashboard monitor 跨表 `LEFT JOIN` 随交易量线性变慢。
- **修复方向**:`ADD INDEX idx_station_id(station_id), idx_bank_app_id(bank_app_id)`。
 
---
 
## LOW / NITS
 
- **L1 死代码**:`app/camera.py` 的 `capture_frame()` 仅 MJPEG 使用,运行时路径全走 `capture_fresh()`,DD-008 已说明。建议在 docstring 明确"仅用于 streaming,非采集路径勿调用"。
- **L2 `.env.example`**:`PAS_API_URL` 指向 staging,提交仓库时应改为占位符。
- **L3 `settings.html`**:Bank App 表格明文展示 password/pin(内网 UI)。结合 H3 修好即可。
- **L4 `calibration` 无缓存**:`type_with_random_pin` 每位数字查一次 DB(约 4 次/PIN),非关键但可优化。
- **L5 回调重试与 PAS 幂等**:`pas_client.py` 有 5s/15s/30s 重试,依赖 PAS 侧 `process_id` 去重(API_SPEC.md 有说明)。若 PAS 承诺幂等,无问题;建议在代码注释里显式记录这一契约。
- **L6 日志时间戳**:分钟级在快序列中排序会丢失;DD-013 已声明本地时间显示为人读,可接受。
- **L7 WebSocket 日志无脱敏**:`monitor.py` WS 广播 transaction 历史含 `bank_code`/`error_message`,内网可接受,但与 C1 一起处理更好。
 
---
 
## 假阳性(驳回)
 
- **Camera `_active_instance` race**:agent 曾怀疑 `camera.py:61` 读 `_active_instance` 未加锁。复核 `camera.py:51-79` 整段已在 `with Camera._init_lock:` 之内(57 行),**不存在竞争**,此报告不采纳。
- **`process_id` 去重竞争**:`withdrawal.py:21-25` 先 SELECT 再 INSERT 看似 TOCTOU,但三处 INSERT 都用 `try/except IntegrityError(1062)` 兜底 + schema 上有 UNIQUE。真正一致性由 UNIQUE 保证,**不是 bug**。
 
---
 
## 关键文件清单(快速定位)
 
| 问题 | 文件 | 行号 |
|---|---|---|
| 密码明文日志 (C1) | `app/actions.py` | 133, 136, 140 |
| Dashboard XSS (H1) | `static/index.html` | 159-163 |
| 工具硬编码 DB 密码 (H2) | `tools/copy_arm_data.py` / `tools/import_flows.py` / `tools/insert_acleda_mappings.py` | 50 / 6 / 3 |
| Bank apps 返回密码 (H3) | `app/routers/banks.py` | 122-131 |
| callback_sent_at 非原子 (H4) | `app/arm_worker.py` | 169-213 |
| task 字段无保护 (H5) | `app/arm_worker.py` | `_process_task` 开头 |
| 异常捕获过宽 (H6) | `app/arm_worker.py` | 140-149 |
| stall 照片覆盖 (M1) | `app/arm_worker.py` | 201-207 |
| OCR 关键字优先级 (M2) | `app/ocr.py` | receipt keyword loop |
| Handler bank_code (M3) | `app/actions.py` | `_run_handler_flow` |
| saveFlow 非事务 (M4) | `static/recorder.html` | saveFlow |
| schema NULL/索引 (M5/M6) | `db/schema.sql` | transactions 表 |
 
---
 
## 推荐的修复优先级
 
1. **立刻(防止凭据泄漏)**:C1、H2、H3
2. **进入生产前**:H1、H4、H5、H6
3. **Backlog**:M1–M6、L1–L7
 
本文件只是 review 报告,**用户明确要求不做任何修改**。后续若需修复,应单独走 implementation 流程,并对照 `DESIGN_DECISIONS.md` 逐条确认不违反 ADR。