---
 
# 第二轮验证(2026-04-14,基于 origin/main 修复后的提交 3034fcf / a043fc8 / c8da892)
 
## 修复验证
 
对照 `KNOWN_ISSUES.md` 逐项核对 origin/main 的实际代码:
 
### Fixed — 全部验证通过
 
| ID | 文件:行 | 验证结果 |
|---|---|---|
| HR-1 create_arm 回滚 | `app/routers/stations.py:24-28` | ✅ 正确。`active=True` + worker 启动失败时,执行 `UPDATE arms SET active=0, status='offline'` 并返回 `success:False` 含错误说明。 |
| HR-2 PAS_API_URL 短路 | `app/pas_client.py:53-55` | ✅ 正确。`callback_result` 入口判 `not PAS_API_URL` 立即 `return None`,完全跳过重试循环。 |
| MR-1 reset_arm 异步化 | `app/routers/monitor.py:118-122` | ✅ 正确。`reset_to_origin()` 与 `close_port()` 都改走 `loop.run_in_executor(worker._executor, ...)`,不再阻塞事件循环。 |
| M6 索引 | `db/schema.sql:81-87` | ✅ schema 已加 `idx_station_id` 与 `idx_bank_app_id`。`KNOWN_ISSUES.md` 注明已同步执行 ALTER TABLE 到 live DB。 |
| M1 stall 照片不覆盖 receipt | `app/arm_worker.py:201-203` | ✅ 正确。从无条件覆盖改为 `if not receipt_b64 and stall_screenshot:`,先前 PHOTO step 抓到的回执会保留。 |
 
### Won't Fix — 业务决策已在 KNOWN_ISSUES.md 记录,逻辑成立
 
- **C1 / H2 / H3 / H1**:owner 决策——系统部署在专机、内网、Cloudflare Tunnel 仅放行 3 条 PAS 路径;DB 密码本身在同机 `.env` 与 Docker MySQL 里也能读到;Builder 操作员等于已经拿到全部权限。**遮蔽密码不会带来真实安全收益,只增加复杂度**——这个推理在当前部署模型下是站得住的。
- **建议**:在 `.gitignore` 加显式 `.env` 项保险;把 `wa-system.md` 的"`0.0.0.0` 部署需重审认证策略"也复制到 `KNOWN_ISSUES.md` Won't Fix 区,以防将来部署模型变更时丢失上下文。
 
### Backlog — 仍未修,符合预期
 
- M2 (OCR 关键字优先级)、M4 (saveFlow 非事务) 都标记 backlog,理由清楚。
 
---
 
## 第二轮新发现
 
修复+新功能(transactions 分页、install_tunnel)引入的小问题:
 
### N1. Transactions 页"All" 选项实际只返回 50 行 ⚠️
- **文件**:`static/transactions.html:139` + `app/routers/monitor.py:131`
- **现象**:前端代码 `const params = pageSize ? ['limit=' + pageSize] : [];`——选 "All" 时 `pageSize=""`,不传 `limit` 参数。后端 `list_transactions(..., limit: int = 50, ...)` 默认值 50。
- **结果**:用户选 "All",前端拿到 50 行,UI 看起来像"只有 50 笔交易"。
- **修复方向**:前端选 "All" 时显式传 `limit=0` 或 `limit=10000`;或后端把 `limit` 默认值与"None 时不限制"语义对齐(注意若真的不限制会有内存压力,建议封顶 5000)。
- **严重度**:Medium(用户视角下数据不全,但不会丢数据)。
 
### N2. `asyncio.get_event_loop()` 在 reset_arm 中已弃用
- **文件**:`app/routers/monitor.py:119`
- **说明**:Python 3.10+ 在协程上下文里推荐 `asyncio.get_running_loop()`,`get_event_loop()` 在没有运行循环时会发 `DeprecationWarning`,3.12 起在某些场景直接报错。
- **修复方向**:`loop = asyncio.get_running_loop()`,或干脆 `await asyncio.to_thread(worker.arm_client.reset_to_origin)`(更简洁)。
- **严重度**:Low。
 
### N3. `worker._executor` 访问私有属性
- **文件**:`app/routers/monitor.py:120-121`
- **说明**:从路由层直接拿 worker 的 `_executor` 私有线程池,封装泄漏。如果将来 ArmWorker 重构为多池或换实现,这里会沉默坏掉。
- **修复方向**:在 `ArmWorker` 上加 `async def run_in_executor(self, fn, *args)` 公开方法,路由层调用它。
- **严重度**:Low / Nit。
 
### N4. `install_tunnel.ps1` 服务账户配置可疑
- **文件**:`deploy/install_tunnel.ps1`(NSSM 安装段)
- **说明**:`& $NSSM set $SERVICE_NAME ObjectName ".\$env:USERNAME"` 设置了运行账户但**没有配套设置密码**。NSSM 在没有密码时,会拒绝以指定用户启动服务(或回退到 LocalSystem,行为不明确)。如果实际部署是手工再补密码、或借助 `$env:USERNAME == "Administrator"` 的特殊路径,应在脚本里加 `Read-Host -AsSecureString` 或注释说明运维步骤。
- **严重度**:Low(部署期发现,产线运行不受影响)。
- **建议**:验证一次部署:`sc.exe qc CF-Tunnel` 看 `SERVICE_START_NAME` 是否如预期。
 
### N5. install_tunnel 流程对 cloudflared 路径硬编码
- **文件**:`deploy/install_tunnel.ps1` 顶部 `$CF_EXE = "C:\Program Files (x86)\cloudflared\cloudflared.exe"`
- **说明**:cloudflared 安装可能在 `C:\Program Files\cloudflared\` 或自定义路径。脚本应 `Get-Command cloudflared` 兜底。
- **严重度**:Low。
 
---
 
## 关键文件指引(本轮)
 
| 主题 | 文件:行 |
|---|---|
| HR-1 修复 | `app/routers/stations.py:24-28` |
| HR-2 修复 | `app/pas_client.py:53-55` |
| MR-1 修复 | `app/routers/monitor.py:118-122` |
| M1 修复 | `app/arm_worker.py:201-203` |
| M6 修复 | `db/schema.sql:81-87` |
| N1 新问题 | `static/transactions.html:139`, `app/routers/monitor.py:131` |
| N2 新问题 | `app/routers/monitor.py:119` |
| N4/N5 部署脚本 | `deploy/install_tunnel.ps1` |
 
---
 
## 总评
 
修复质量良好:
- 5 个 Fixed 项**都对应实际代码改动且逻辑正确**,没有"号称修了但其实没改"的情况。
- Won't Fix 区写得很专业——每条都有"在此部署模型下为何无收益"的论证,而不是简单"我不修",owner 复核时易于核对。
- 引入的新代码量小,但 N1(分页 "All" 失效)是真实可见的用户问题,建议下一次小迭代一起处理。N2/N3 是代码卫生级别。
 
整体 review 通过。