# WA Unified System — 架构文档

> 本文档描述系统的**实际架构**，包含模块交互、数据流、关键设计决策。

---

## 系统概览

单 FastAPI 进程，端口 9000。合并了 Builder（Web UI + 流程录制）和 JQS（执行引擎 + OCR）。

```
┌─────────────────────────────────────────────────────────────┐
│ FastAPI (端口 9000)                                          │
├──────────────┬──────────────────────────────────────────────┤
│ Builder UI   │ WA API                                        │
│ /            │ POST /process-withdrawal                      │
│ /recorder    │ GET  /status/{id}                             │
│ /transactions│ GET  /health                                  │
│ /settings    │                                               │
├──────────────┴──────────────────────────────────────────────┤
│ Monitor API + WebSocket                                      │
│ GET /api/monitor/status, /ws, /logs/ws                       │
│ POST /api/monitor/pause|resume|offline|reset/{arm_id}        │
├─────────────────────────────────────────────────────────────┤
│ WorkerManager (asyncio.Lock + _remove_worker 原子操作)          │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐         │
│ │ ArmWorker #1 │ │ ArmWorker #2 │ │ ArmWorker #N │         │
│ │ ArmClient    │ │ ArmClient    │ │ ArmClient    │         │
│ │ Camera       │ │ Camera       │ │ Camera       │         │
│ │ Executor     │ │ Executor     │ │ Executor     │         │
│ │ LogHandler   │ │ LogHandler   │ │ LogHandler   │         │
│ └──────────────┘ └──────────────┘ └──────────────┘         │
├─────────────────────────────────────────────────────────────┤
│ MySQL (wa-unified-mysql:3308) — 14 张表                      │
└─────────────────────────────────────────────────────────────┘
```

## 数据库 (14 张表)

```
arms ──< stations ──< phones
              │──< bank_apps
              │──< ui_elements
              │──< keymaps
              │──< swipe_actions
              │──< keyboard_configs
              │──< calibrations

flow_templates (arm_id) ──< flow_steps

transactions ──< transaction_logs

bank_name_mappings (独立)
```

### 关键字段

| 表 | 关键设计 |
|---|---------|
| `arms` | `camera_id`, `active` (worker 是否启动), `status` (idle/busy/offline) |
| `stations` | `id AUTO_INCREMENT`; `stall_photo_x/y` — stall 时 arm 移动到此位置拍摄手机全屏截图 |
| `transactions` | `status` ENUM 含 `stall` — 步骤失败需人工介入的状态 |
| `flow_templates` | `arm_id` 绑定到特定机器；`transfer_type` (SAME/INTER/NULL) |
| `calibrations` | 每个 station 的仿射矩阵、park 位、scale、旋转角 |
| `keymaps` | `keyboard_type VARCHAR(50)` — 支持长名称如 `s1_cimb_account_number` |

## 模块交互

### 任务执行流程

```
PAS → POST /process-withdrawal
  │
  ├→ 查 bank_apps (bank_code + account_no) → 得到 station_id
  ├→ 查 stations → 得到 arm_id
  ├→ 检查 arm active + status
  ├→ INSERT transactions (status='queued')
  │
  └→ ArmWorker 轮询发现新任务
       │
       ├→ 查 flow_templates (bank_code + arm_id + transfer_type)
       ├→ 查 flow_steps
       ├→ open_port + motor_lock (在 ThreadPoolExecutor 线程里)
       │
       ├→ 逐步执行 (actions.execute_step)
       │    ├→ CLICK: lookup_ui_element → arm.click (executor)
       │    ├→ TYPE: load_keyboard_config → arm.click per key (executor)
       │    ├→ SWIPE: lookup_swipe → arm.swipe (executor)
       │    ├→ PHOTO: arm.move → camera.capture_base64 (executor)
       │    ├→ OCR_VERIFY: arm.move → camera.capture → ocr.verify (executor)
       │    └→ CHECK_SCREEN: arm.move → camera.capture → screen_checker.compare (executor)
       │
       ├→ 根据结果决定 PAS callback status
       ├→ close_port（摄像头保持打开，不关闭）
       └→ 下一笔任务
```

### UI Element 坐标设计

所有 action type 统一使用 `step_name` 作为 `ui_element_key`：

```
flow_steps.ui_element_key = step_name
  → lookup_ui_element(bank_code, station_id, step_name)
  → ui_elements 表: (bank_code, station_id, element_key) → (x, y)
```

- CLICK/ARM_MOVE/PHOTO/OCR_VERIFY/CHECK_SCREEN 全部用 `step_name` 查坐标
- 同一 flow 内 step_name 必须唯一（Builder saveFlow 前端校验）
- SAME 和 INTER flow 通过 `_inter` 后缀区分，避免坐标互相覆盖
- Builder 编辑 INTER flow 时自动给 step_name 加 `_inter` 后缀
- Copy flow 切换 transfer_type 时自动加/去后缀
- Handler flow（如 ACLEDA_AFTER_POPUP）用自己的 bank_code 查坐标，和主 flow 独立
- Stall 拍照坐标在 `stations.stall_photo_x/y`，和 flow step 坐标独立

### Stall 队列处理

当 arm stall 时，除了当前失败的任务回调 PAS status=4 外，该 arm 上所有 queued 状态的任务也会自动标记为 failed 并回调 PAS status=4，附带错误信息。不会让排队任务无限等待。

### 非阻塞架构

所有 arm/camera 阻塞操作通过 `run_in_executor` 在专属线程里执行：

```python
async def _hw(executor, func, *args):
    """actions.py 里的 helper — 硬件调用不阻塞事件循环"""
    if executor is None:
        return func(*args)  # Builder recorder 直接调（无 executor）
    return await asyncio.get_event_loop().run_in_executor(executor, func, *args)
```

- 每个 ArmWorker 有独立的 `ThreadPoolExecutor(max_workers=1)`
- `time.sleep` 全部替换为 `await asyncio.sleep`
- DB 操作保持 async (aiomysql)
- 结果：多个 worker 并行执行，互不阻塞

### PAS Callback Status

```
OCR_VERIFY 步骤结果 → 存入 transaction["_ocr_result"]
                          │
arm_worker._process_task 读取 _ocr_result：
  │
  ├→ success + receipt_check:
  │    ├→ receipt_result = "success" → callback status=1
  │    ├→ receipt_result = "fail"    → callback status=2
  │    └→ receipt_result = "review"  → callback status=3
  │
  ├→ success (无 receipt_check) → callback status=1
  │
  └→ 任何步骤失败（OCR 验证失败、步骤执行异常等）
       → DB status='stall' + 截图
       → callback status=4
       → arm offline + 暂停（需人工检查手机状态）
       → 不尝试自动关闭 APP（状态不确定，交给人工处理）
```

所有 callback 都带 receipt 截图，以 `multipart/form-data` file 方式发送（非 base64 JSON）。DB 仍存 base64，发送时 decode 为文件字节。不重试，失败交给 PAS 人工处理。

**回调一致性保证：** `callback_result` 检查 HTTP 状态码，仅 2xx 视为成功。非 2xx 或网络异常返回 None，worker 不写 `callback_sent_at`，保留 NULL 以便后续对账/重发。Stall 时该 arm 所有 queued 任务也会自动回调 status=4 后标记 failed。

**Stall 设计原则：** 任何步骤级失败一律走 stall（DB status='stall', PAS status=4），因为：
- 机器无法判断转账是否已经成功（可能已走到确认步骤）
- 自动关闭 APP 依赖 `all_apps_btn`，不是所有银行都有，且状态不确定时操作危险
- arm 必须 offline + 暂停，等人工检查手机屏幕后再 resume

**Stall 拍照：** stall 时 arm 先移动到 `stations.stall_photo_x/y` 位置拍摄手机全屏截图，附在 PAS 回调和 DB `receipt_base64` 里，方便远程排查。位置在 Settings 页面配置，跟 flow 里各步骤的 ui_element 独立。未配置时在当前位置拍。

### Builder Recorder 调试流程

```
用户选择 arm → Dashboard 暂停 arm
  → 去 Recorder 页面 → Connect arm (检查 worker 已暂停)
  → 调试 (move/click/swipe/test-step) — 所有操作带 arm_id
  → Disconnect arm
  → Dashboard 恢复 arm
```

离开 Recorder 页面时 `beforeunload` 事件自动断开 arm 和 camera。

## 文件结构

```
Builder_JQS_Code/
├── docker-compose.yml         MySQL container (wa-unified-mysql:3308)
├── .env                       配置 (DB + PAS + Auth)
├── requirements.txt           依赖
├── README.md                  部署指南 + API 列表
├── CHANGELOG.md               变更记录
├── ARCHITECTURE_PLAN.md       本文档
│
├── db/
│   ├── schema.sql             14 张表 DDL
│   ├── seed.sql               从 builder-mysql 导出的真实数据
│   ├── run_sql.py             SQL 执行工具
│   └── export_seed.py         导出当前 DB 配置数据到 seed.sql
│
├── app/
│   ├── main.py                入口 (lifespan: DB + WorkerManager + cleanup)
│   ├── config.py              .env 配置读取
│   ├── database.py            aiomysql 连接池
│   ├── auth.py                API Key 认证
│   ├── models.py              Pydantic 模型
│   │
│   ├── worker_manager.py      管理所有 ArmWorker (asyncio.Lock + _remove_worker 原子操作)
│   ├── arm_worker.py          单台机器 Worker (ThreadPoolExecutor + 任务循环)
│   ├── arm_client.py          ArmClient 类 + 模块级兼容函数
│   ├── camera.py              Camera 类 + 模块级兼容函数
│   │
│   ├── actions.py             步骤执行器 (全部非阻塞, executor 参数)
│   ├── keyboard_engine.py     智能键盘引擎 (非阻塞)
│   ├── screen_checker.py      屏幕比对 (ORB 对齐 + SSIM diff)
│   ├── ocr.py                 可配置 OCR (字段可选 + receipt status)
│   ├── (stall_detector.py 已删除 — 零调用，stall 由 arm_worker OCR 分支处理)
│   ├── pas_client.py          PAS HTTP 回调
│   ├── calibration.py         标定 (async, DB-backed, 缓存)
│   │
│   └── routers/
│       ├── withdrawal.py      WA API (接收任务, arm 可用性检查)
│       ├── monitor.py         监控 API + WebSocket (status/logs/control)
│       ├── stations.py        CRUD: arms (auto add_worker), stations, phones
│       ├── banks.py           CRUD: templates (arm_id, copy), apps, mappings
│       ├── flows.py           CRUD: flow_steps (reorder)
│       ├── coordinates.py     CRUD: ui_elements, keymaps, swipes, keyboards
│       ├── calibration_router.py  标定 API + 3 点自动标定
│       ├── stream.py          MJPEG 流 (per arm_id)
│       ├── recorder.py        录制 + 调试 (per arm_id, debug lock)
│       └── opencv_router.py   参考图 capture/compare (per arm_id)
│
├── static/
│   ├── index.html             Dashboard (机器卡片 + Live Logs + WebSocket)
│   ├── recorder.html          Flow Builder (arm 选择 + 标定 + OCR 配置)
│   ├── transactions.html      交易列表 + 详情 + 日志 + 截图
│   ├── settings.html          Arms/Stations/Phones/BankApps 管理
│   ├── css/style.css
│   └── js/api.js              API client + 导航栏
│
├── references/                参考图片 (references/{arm_name}/{bank_code}/{name}.jpg)
│
├── deploy/
│   ├── install_service.bat    NSSM 安装脚本 (Windows 服务)
│   ├── uninstall_service.bat  NSSM 卸载脚本
│   ├── nssm.exe               NSSM 可执行文件
│   ├── tesseract-setup.exe    Tesseract OCR 安装包
│   ├── README.md              部署说明
│   └── logs/                  NSSM 服务日志输出
│
└── arm_service/
    ├── README.md              Arm WCF 服务文档
    ├── VC_redist.x86.exe      Visual C++ 运行时
    ├── service/               WCF 服务程序
    └── examples/              示例代码
```

## 关键设计决策

### 1. ArmClient/Camera 类 + 模块级兼容函数

```python
# arm_client.py
class ArmClient:
    def __init__(self, com_port, service_url, z_down): ...
    def click(self, x, y): ...

_default = ArmClient()  # 模块级默认实例

def click(x, y):         # 模块级函数 → 转发给 _default
    return _default.click(x, y)
```

Worker 创建自己的 ArmClient 实例。Builder recorder 不指定 arm_id 时用模块级默认。两套代码共存不冲突。

### 1b. Camera 并发架构

Camera 类使用双标志位 + 双锁设计，解决 Worker/Recorder 共享摄像头的冲突：

```
_enabled   : Worker 控制（run() 时 True, stop() 时 False）
              — 决定 capture_frame / camera_open 是否工作
_streaming : Recorder API 控制（stream_start / stream_stop）
              — 仅控制 generate_mjpeg 循环，不影响 Worker 拍照

_init_lock : 类级全局锁（threading.Lock），串行化 cv2.VideoCapture() 初始化
              — 防止多台 arm 同时打开摄像头时后端冲突

Backend: DSHOW (CAP_DSHOW) — 经 `tools/camera_parallel_test.py` 实测验证：
  - MSMF/DSHOW/AUTO 三种后端都无法在 Windows 上同时打开多个摄像头（OpenCV 限制）
  - DSHOW 单独按 index 打开 3 个摄像头均 100% 成功
  - DSHOW read 速度 0.8ms vs MSMF 2.9ms，更快更干净
  - DSHOW 帧缓冲区在无人读取时无限积压（非覆盖式），无法通过 grab() 可靠清空

独占模型 (_active_instance): 类变量追踪当前持有硬件的 Camera 实例。
`camera_open()` 自动释放上一个（`_release_hw()`），保证同一时刻只有一个 VideoCapture 存在。
多 arm 同时需要拍照时自动排队（全局 `_init_lock`），每次切换约 0.4s 开销。
`stream_stop()` 关闭摄像头释放硬件，Recorder 切换 arm 时旧摄像头立即释放。
`_cleanup_arm()` 任务结束后关闭摄像头。
连续 30 次 read 失败自动关闭 camera 触发 re-init。

capture_fresh() — 实时帧保证：
  DSHOW 缓冲区无法可靠清空（grab 计数/时间检测均失败），因此 capture_fresh()
  通过关闭并重新打开摄像头来彻底重置缓冲区。PHOTO/OCR_VERIFY/CHECK_SCREEN 均使用此方法。
  capture_frame() 仅用于 MJPEG streaming（连续读取，无缓冲问题）。
_lock      : 实例锁，保护 self._camera 引用的读写
```

**关键规则：**
- Worker `run()` 调 `camera_enable()` 设置 `_enabled=True`
- `_cleanup_arm()` 调 `camera_close()` 释放摄像头（MSMF 不支持多摄像头同时打开）
- Recorder 的 `/camera/close` 调 `stream_stop()`，只停 MJPEG 流，不碰 `_enabled`
- Recorder 不会影响正在执行任务的 Worker 的拍照能力

### 2. flow_templates 绑定 arm_id

同一个银行在不同机器上可能有不同的 flow（步骤不同、delay 不同）。`arm_id` 列区分。Worker 查询时优先匹配 arm_id，找不到回退 `arm_id IS NULL`。

Copy Flow 功能：复制 template + steps 到另一台 arm（坐标需重新录制）。

### 3. 标定存数据库

`calibrations` 表取代 JSON 文件。`calibration.py` 全部 async，内存缓存 + DB 持久化。`get_all_calibrations()` 动态查所有 station，不硬编码。

3 点自动标定：移动 arm 到 3 个位置拍照，模板匹配计算仿射矩阵。失败时用户手动点击参考点。

### 4. OCR 验证可配置

配置存在 `flow_step.description` (JSON)：

```json
{
  "verify_fields": ["pay_to_account_no", "amount"],
  "receipt_status": {
    "success": ["Success", "Successful"],
    "review": ["In Review", "Pending"],
    "failed": ["Failed", "Unsuccessful"]
  }
}
```

两种场景：
- 转账前验证 (verify_fields only) — 不匹配则 status=4 暂停
- 转账后验证 (receipt_status) — 按关键词匹配返回 1/2/3/4

### 5. 不重试原则

任何失败直接报告 PAS，不自动重试。原因：
- 转账可能已经成功但 OCR 没读到 → 重试 = 重复转账
- 未知弹窗无法自动处理 → 重试只会重复失败
- 人工判断比机器猜测更安全

API 不暴露 retry 端点。`/api/monitor/transactions/{id}/retry` 已删除。

### 6. Random PIN 键盘

某些银行 APP 的 PIN 输入使用随机排列的数字键盘。

```
拍照 → 切 10 个格子 → Tesseract 逐个识别 → 找到目标数字 → 点击 N 次
```

- 用 arm 坐标反算像素位置，精确切格子
- 4 种预处理方法尝试（adaptive threshold / OTSU / fixed / raw）
- 找不到目标数字 → 移动 camera 2mm 换角度重拍（最多 3 个位置）
- `bank_apps.pin` 字段存 APP PIN，`input_source = "pin"` 引用
- 实测 ~1 秒完成 OCR，远低于 15-20 秒超时限制

### 7. WorkerManager 并发安全

```
asyncio.Lock (_lock) 保护所有 worker dict 操作：
  add_worker()    → 加锁后检查 + 创建，防止并发重复
  _remove_worker()→ cancel task → await → cleanup → stop（原子）
  stop_all()      → 加锁遍历所有 worker 调 _remove_worker
  set_offline()   → 加锁调 _remove_worker，完全清除（不是 pause）
                    resume 后创建全新实例，camera 重新 enable
  delete_arm()    → 加锁调 _remove_worker 再删 DB
```

`OCR_REQUIRED` 环境变量（默认 `true`）：当 OCR 引擎不可用时，true = raise RuntimeError（任务失败，arm 暂停），false = 跳过并继续（非生产用途）。

`set_offline` 在移除 worker 前打 WARNING 级别 log（含 arm_name），Live Logs 可见，提示操作人员 offline 是临时停机，`active=1` 时重启服务会自动恢复。

### 8. 参考图片按 arm 隔离

```
references/{arm_name}/{bank_code}/{name}.jpg
```

不同 arm 的摄像头拍出的图不同（光线、角度），参考图不能共用。加载时先找 arm 目录，找不到回退到无 arm 的旧路径。
