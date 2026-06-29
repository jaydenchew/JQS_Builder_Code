# 文档维护地图 (DOCS_MAP)

> 本文件定义 WA Unified System 每份文档的**用途**、**该写什么内容**，以及"改了 X 该更新哪些文档"的反向索引。
> 目的：让"每做一件事就更新对应文档"有据可依。
>
> **维护规则**：新增 / 重命名 / 删除文档时，必须同步更新本文件、`README.md` 的文档索引表、`.agent/workflows/wa-system.md` 的 Required Reading。

---

## 1. 单一真相源（topic → 唯一归属文档）

| 主题 | 真相源文档 | 别处只放摘要 / 引用 |
|---|---|---|
| 对外 PAS / 报表 API 契约 | `API_SPEC.md` | `README.md`、`BUSINESS_CONTEXT.md` |
| DB schema（DDL） | `db/schema.sql` | `ARCHITECTURE_PLAN.md`（关系图）、`README.md`（表计数） |
| 设计决策 / 为什么这样写 | `DESIGN_DECISIONS.md`（DD-NNN，只增不删） | 各处 `见 DD-xxx` |
| 发了什么 / 何时（逐次改动） | `CHANGELOG.md` | — |
| 当前已知 bug / backlog | `KNOWN_ISSUES.md` | — |
| 领域 / 为什么用机械臂 / 新人心智模型 | `BUSINESS_CONTEXT.md` | — |
| as-built 架构、模块如何组装 | `ARCHITECTURE_PLAN.md` | — |
| Docker 线安装 runbook | `INSTALL.md` | `README.md`（condensed 版） |
| 部署 / NSSM / Cloudflare / 防火墙运维 | `deploy/README.md` | `INSTALL.md` |
| CHECK_SCREEN 运维读日志 | `CHECK_SCREEN_OPS.md` | — |
| smart plug 全栈（协议 + 实现） | `SMART_PLUG_SPEC.md` | `DESIGN_DECISIONS.md`（DD-029/030）、`deploy/README.md` |
| arm WCF 服务接口 | `arm_service/README.md` | — |
| 原生安装包构建 / 装机 | `JQS_install_package/README_BUILD.md` | — |
| vendored 第三方二进制清单 | `JQS_install_package/vendor/MANIFEST.md` | `README_BUILD.md` |
| 原生装机后操作清单 | `JQS_install_package/NEXT_STEPS.txt` | — |
| agent 入口 / 导航 / 不变量 | `.agent/workflows/wa-system.md` | — |
| 顶层索引 + 快速上手 | `README.md` | — |

---

## 2. 文档全景（16 份）

### main-repo

| 文档 | 用途 | 该写什么 / 何时更新 |
|---|---|---|
| `README.md` | 顶层入口 + 快速上手 + 索引表 | 新增安装前置 / `.env` 键 / 对外暴露端点 / 新文档入索引 / 15 表计数变动 |
| `ARCHITECTURE_PLAN.md` | as-built 架构（中文） | 改跨模块契约 / 并发模型 / 执行流水线 / 回调映射 / DB 关系 / 新 action_type |
| `BUSINESS_CONTEXT.md` | 领域"为什么" + 心智模型 | 改领域模型：新 action_type / PAS 状态码语义 / SAME-INTER / stall 生命周期 / arms 关系图 |
| `API_SPEC.md` | PAS↔WA 对外契约 | 任何外部可见行为：字段 / 状态码 / 回调时序 / dedup / 银行目录 |
| `DESIGN_DECISIONS.md` | ADR 决策日志（DD-001~034） | 新决策追加 DD；反转则旧条标 Superseded + 写新条 |
| `KNOWN_ISSUES.md` | 已知 bug / backlog（带 file:line） | 发现新缺陷 / 修复翻 checkbox / Won't-Fix 定性 |
| `CHECK_SCREEN_OPS.md` | CHECK_SCREEN 运维手册（中文） | 改 log 字段 / reason 值 / 健康阈值 / trigger 模式 / Builder 控件文案 |
| `INSTALL.md` | Docker 线装机 runbook | 改装机步骤 / 前置 / `.env` / Builder 配置项 / 校准 / 排障 / seed |
| `CHANGELOG.md` | 逐次改动日志（reverse-chron） | **任何 shipped 代码改动都要 prepend 一条**（见第 3 节） |
| `SMART_PLUG_SPEC.md` | smart plug 协议 + 实现全栈 | 改插座协议 / 控制契约 / `plug_*` 列 / MQTT 配置 / 监控端点 |
| `arm_service/README.md` | Arm WCF 服务接口 | 改 bind 口 8082 / `getstring` 参数（duankou/hco/daima）/ 命令编码 |
| `deploy/README.md` | 部署 / 服务 / tunnel 运维 | 改 NSSM / Cloudflare ingress 暴露面 / 防火墙 / 启动顺序 / 排障 |

### install-package

| 文档 | 用途 | 该写什么 / 何时更新 |
|---|---|---|
| `JQS_install_package/README_BUILD.md` | 原生（去 Docker）安装包构建指南 | 改原生服务 / 端口 / DB 名 / installer 强制 `.env` 默认 / `install_all.ps1` 步骤 |
| `JQS_install_package/vendor/MANIFEST.md` | vendored 二进制清单 + 版本 | 改任一 vendored 件文件名 / 版本 / 来源 / wheelhouse |
| `JQS_install_package/NEXT_STEPS.txt` | 原生装机后操作清单 | 改操作员手动步：`.env` 键 / 首屏路由 / seed 导入 / tunnel / 插座 |

### agent-internal

| 文档 | 用途 | 该写什么 / 何时更新 |
|---|---|---|
| `.agent/workflows/wa-system.md` | agent 入口 / 导航 / 不变量 | 改 reading set / 新增不变量 / File Map 主文件改名 / 表 & ADR 计数 |

---

## 3. 反向索引：改了 X → 更新哪些文档

| 你改了… | 必更 | 可能波及 |
|---|---|---|
| 新增 / 改 `flow_steps.action_type` | `CHANGELOG` · `DESIGN_DECISIONS`(新 DD) · `BUSINESS_CONTEXT`(Action 表) · `ARCHITECTURE_PLAN` · `db/schema.sql`(ENUM) | `API_SPEC` · `CHECK_SCREEN_OPS` |
| 改 PAS 契约（字段 / 状态码 / 回调 / 重试） | `API_SPEC` · `CHANGELOG` · `BUSINESS_CONTEXT` · `ARCHITECTURE_PLAN` | `DESIGN_DECISIONS` · `README` |
| 加 / 改 DB 表或列 | `db/schema.sql` · `CHANGELOG`(迁移 SQL) · `ARCHITECTURE_PLAN` | `README`(15 表) · `BUSINESS_CONTEXT` · `wa-system.md` |
| 改算法（CHECK_SCREEN / calibration / OCR / random_pin） | `DESIGN_DECISIONS` · `CHANGELOG` | `CHECK_SCREEN_OPS` · `ARCHITECTURE_PLAN` |
| 加 / 改 `/api/*` 端点 | `CHANGELOG` | `API_SPEC`(对外 / 报表) · `deploy/README`(需 tunnel) · `README` |
| 改 smart plug | `SMART_PLUG_SPEC` · `CHANGELOG` | `DESIGN_DECISIONS` · `deploy/README` |
| 改部署 / 服务 / 防火墙 / NSSM / tunnel | `deploy/README` · `CHANGELOG` | `INSTALL` · `README` |
| 改 `.env` / config 默认值 | `INSTALL`(Step 5) · `README`(Step 5 块) | `CHANGELOG` · `SMART_PLUG_SPEC`(若 MQTT_*) · `README_BUILD`(installer 强制值) |
| 改原生安装包 | `README_BUILD` · `NEXT_STEPS.txt` | `vendor/MANIFEST` · ⚠️ `payload/db` 工具（已与主项目分叉） |
| 发现 / 修 bug | `KNOWN_ISSUES` | `CHANGELOG`(若发版) |
| 加 / 改 / 删文档、改不变量 | `wa-system.md`(导航) · `README`(文档索引) · 本 `DOCS_MAP.md` | — |
| **任何 shipped 代码** | **`CHANGELOG`（铁律）** | 对应专题文档 |
