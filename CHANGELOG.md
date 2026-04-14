# Changelog

## Camera Buffer Fix, UI Element Redesign, Keyboard Space, Stall Queue Handling (2026-04-13)

### Camera: Real-time Frame Capture
- **`capture_fresh()` reopens camera**: DSHOW buffers frames indefinitely when nobody reads. Previous attempts (fixed flush count, time-based flush) all failed. Now `capture_fresh()` closes and reopens the camera to guarantee a real-time frame. Used by PHOTO, OCR_VERIFY, CHECK_SCREEN.
- **`CAP_PROP_BUFFERSIZE = 1`**: Set on camera open to minimize DSHOW internal buffer.
- **`capture_base64()` defaults to fresh**: Uses `capture_fresh()` internally for stall photos and error screenshots.

### UI Element Key: step_name Instead of Shared camera_pos
- **Unified design**: PHOTO/OCR_VERIFY/CHECK_SCREEN now use `step_name` as `ui_element_key`, same as CLICK/ARM_MOVE. Each step has its own independent coordinates in `ui_elements`.
- **Backend**: `execute_photo`, `execute_ocr_verify`, `execute_check_screen` all read `step["ui_element_key"]` instead of hardcoded `"camera_pos"`.
- **Frontend**: `readForm()`, `addQuick()`, test/runAll paths all updated.
- **step_name uniqueness**: `saveFlow()` validates no duplicate step names within a flow.
- **Backward compatible**: Existing flows with `ui_element_key='camera_pos'` still work; key migrates to `step_name` when user saves in Builder.

### SAME/INTER Transfer Type Isolation
- **Auto `_inter` suffix**: When editing an INTER flow in Builder, `readForm()` automatically appends `_inter` to step names (and `ui_element_key`), preventing coordinate conflicts with SAME flows.
- **Copy flow suffix**: `copy_template` API auto-renames steps when copying between transfer types (SAME→INTER adds `_inter`, INTER→SAME removes it).
- **`addQuick()` respects transfer type**: Quick-add buttons also apply the suffix.

### Handler Flow Bank Code Fix
- **`_run_handler_flow` uses handler's bank_code**: Previously passed the main flow's `bank_code` to handler steps, causing `lookup_ui_element` to fail when handler has a different bank_code (e.g. `ACLEDA_AFTER_POPUP`). Now extracts bank_code from the handler ref string (`parts[0]`).

### Keyboard: Space and Special Key Support
- **CHAR_ALIASES mapping**: `' '` → `'space'`, `'\n'` → `'enter'`, `'\t'` → `'tab'`. Applied to all 4 typing paths: simple keymap backend, simple keymap frontend test, intelligent keyboard backend, intelligent keyboard frontend test.
- **Page fallback for special keys**: When `char_to_page` config doesn't include space (only has `a-z`/`A-Z`), the typing loop now falls back to scanning `pages.*.keys` for the aliased key name.

### Stall: Auto-reject Queued Tasks
- **`_fail_queued_tasks()`**: When an arm stalls, all queued transactions for that arm are automatically marked `failed` and reported to PAS with `status=4` and error message. Previously queued tasks were stuck indefinitely.

### OCR_VERIFY / CHECK_SCREEN Duplicate Log Fix
- **Single log entry**: `execute_step` no longer writes a second `transaction_logs` entry for OCR_VERIFY/CHECK_SCREEN — these actions handle their own logging internally.

### Log Rotation
- **NSSM settings**: `AppRotateOnline 1`, `AppRotateSeconds 86400` (daily), `AppRotateBytes 10485760` (10MB cap).

### Transactions UI
- **Modal detail view**: Transaction details now shown in a modal popup instead of requiring scroll to bottom of page.

### Bank Apps
- **Unique key fix**: `uk_bank_account` changed to `(station_id, bank_code, account_no)` to allow same bank account on different stations.
- **Phone column**: Bank Apps table in Settings now shows which phone each app belongs to.

### Audit Fixes (Round 1)
- **auth.py**: Empty WA_API_KEY/WA_TENANT_ID now returns 503 instead of silently allowing all requests. Prevents accidental unauthenticated access when `.env` is misconfigured.
- **Pause status fix**: `pause_arm` no longer force-writes `arms.status='idle'` while a task may still be running. Worker naturally updates status when task completes, avoiding false "idle" state.
- **UTC time consistency**: `_fail_queued_tasks` callback timestamp changed from `datetime.now()` (local) to `datetime.now(timezone.utc)`, matching the main flow's UTC convention.
- **Dead code removed**: `pas_client.update_account_status` and `pas_client.send_alert` deleted — never called anywhere in codebase.

### Audit Fixes (Round 2)
- **process_id race condition**: All 3 INSERT paths in `/process-withdrawal` now catch `IntegrityError(1062)` and return `"Duplicate process_id"` instead of 500. SELECT pre-check retained as fast path; IntegrityError is the concurrency safety net.
- **reorder_steps validation**: Added 3 guards before updating: step count match, no duplicate IDs, all IDs belong to template. Prevents corrupted step ordering from malformed requests.
- **Dead models removed**: `WithdrawalCallback`, `AccountStatusUpdate`, `AlertMessage` deleted from `models.py` — no references in codebase (corresponding `pas_client` functions already removed).

### Withdrawal Validation
- **Self-transfer rejected**: `/process-withdrawal` now rejects requests where `pay_from_bank_code == pay_to_bank_code` and `pay_from_account_no == pay_to_account_no`. Returns error without entering queue.

### Tools Cleanup
- Removed 17 one-off debug/migration scripts from `tools/`. Kept: `camera_parallel_test.py`, `import_flows.py`, `copy_arm_data.py`, `insert_acleda_mappings.py`.

---

## Camera / Logs / PAS / Settings Fixes (2026-04-09)

### Breaking Changes
- **PAS callback receipt → file upload**: `callback_result` now sends receipt photos as `multipart/form-data` file (field name `receipt`, JPEG bytes) instead of base64 JSON string. All scenarios affected: success, receipt check, stall. DB retains base64 — only the HTTP call converts.

### Camera Concurrency Overhaul
- **DSHOW backend** (经 `tools/camera_parallel_test.py` 实测验证): MSMF/DSHOW/AUTO 三种后端在 Windows 上都无法同时打开多个摄像头。DSHOW 单独按 index 打开均 100% 成功，read 速度 0.8ms（MSMF 2.9ms），选择 DSHOW 作为后端。
- **独占模型 (`_active_instance`)**: 类变量追踪当前持有硬件的 Camera 实例。`camera_open()` 自动释放上一个摄像头后再打开新的，保证同一时刻只有一个 VideoCapture 存在。多 arm 同时拍照时通过全局锁自动排队，每次切换约 0.3s。
- **`stream_stop()` 关闭摄像头**: 修复了 Recorder 切换 arm 时旧摄像头不释放导致新摄像头 grabFrame 全部失败的 bug。
- **Dual flag design**: `_enabled` (Worker-only) / `_streaming` (Recorder-only) 分离控制。Recorder `stream_stop()` 不影响 `_enabled`。
- **优化 warmup**: sleep 0.5s → 0.15s，warmup 帧数上限 2（DSHOW 几乎不需要预热）。
- **`_cleanup_arm()` 关闭摄像头**: 任务结束后释放硬件，其他 arm 可以打开自己的摄像头。
- **`stop()` 释放摄像头**: `camera_disable()` called in `stop()` to release hardware when worker is removed.
- **Auto-recovery on failure**: 30 consecutive `read()` failures auto-close camera for re-init. MJPEG stream auto-stops after 50 consecutive failures.

### Live Logs Fix
- **Thread-safe `drain_new()`**: Added `threading.Lock` to `WorkerLogHandler.drain_new()` and `emit()` to prevent race conditions between logging threads and the WebSocket drain loop.
- **Broader log capture**: Handler now also matches on `record.threadName` (executor thread names start with arm name), catching hardware-level logs that don't include `[ARM-XX]` in message text.

### Station ID Auto-increment
- **`stations.id` is now `AUTO_INCREMENT`**: No longer requires manual ID entry. Schema updated, live DB migrated.
- **`create_station` API**: Removed `id` from INSERT; catches duplicate key errors with friendly message.
- **Settings UI**: Removed "Station ID" input field from add form.

### Settings UI
- **Wider input fields**: Table inputs widened across Arms, Stations, Bank Apps tabs (name: 110px, COM: 80px, account: 150px, stall photo: 65px, etc.) so saved data is fully visible.

---

## Stall Overhaul (2026-04-09)

### Breaking Changes
- **Unified failure handling**: ALL step failures now produce `stall` (previously only OCR failures did). DB `transactions.status` ENUM now includes `stall`. PAS always receives `status=4` for any failure.
- **Removed `_close_app`**: No longer attempts to auto-close the bank app on failure. The arm state is unknown after a failure — human must inspect.

### New Features
- **`stall` transaction status**: New DB ENUM value distinguishes "needs manual investigation" from normal `failed` (which is reserved for receipt-check determined failures).
- **Stall photo position**: `stations` table gains `stall_photo_x` / `stall_photo_y` columns. On stall, arm moves to this position for a full phone screenshot before reporting to PAS. Configurable in Settings page.
- **Guaranteed failure screenshots**: `OCR_VERIFY` / `CHECK_SCREEN` steps that crash before writing their own log now fall through to the generic `transaction_logs` INSERT, ensuring the screenshot is always saved.

### Bug Fixes
- **OCR receipt-only check fell through to legacy path**: When `verify_fields` is `[]` (empty — receipt status check only), Python treated it as falsy and fell into the `else` branch which hardcodes account+amount verification. Fixed: condition changed from `if ocr_config.get("verify_fields")` to `if ocr_config is not None`.
- **EasyOCR model not pre-downloaded**: `pip install easyocr` only installs the package; detection/recognition models (~100MB) download on first `Reader()` call. Under Windows service (cp1252 encoding), tqdm progress bar's `█` character caused `UnicodeEncodeError`. Fixed: models stored in project `models/` directory, `ocr.py` passes `model_storage_directory` to Reader, `install_service.bat` pre-downloads during setup + sets `PYTHONIOENCODING=utf-8` via NSSM.
- **Camera disabled after Recorder use**: Recorder's `camera_close` called `camera_disable()` which set `_enabled=False` on the Worker's camera instance. Worker resume never re-enabled it, causing all captures to fail. Fixed: `camera_enable()` called on resume and at task start.
- **PAS receipt was OCR screenshot instead of PHOTO**: `_process_task` prioritized `_ocr_result.screenshot_b64` over DB `receipt_base64`. When flow has OCR_VERIFY then PHOTO, PAS received the OCR confirmation page instead of the actual receipt photo. Fixed: DB `receipt_base64` (written by PHOTO step) now takes priority; OCR screenshot is fallback only.
- **PHOTO step missing from transaction_logs**: `execute_photo` wrote to `transactions.receipt_base64` but `execute_step` never captured its return value, so `transaction_logs.screenshot_base64` was always NULL for PHOTO steps. Fixed: `execute_step` now captures PHOTO handler's returned base64 and writes it to `transaction_logs`.
- **Copy flow only supported arm target**: `copy_template` API only accepted `arm_id`. Extended to also accept `transfer_type` (e.g. SAME→INTER) with auto-generated name. Recorder UI updated with 3 copy options.

### UI
- Dashboard: added **Stall** counter card (orange).
- Transactions page: `stall` status style (orange bold) + filter option + **From/To bank** columns + `to_bank` filter.
- Settings page: Stall Photo X/Y inputs per station.

---

## Phase 1-5: Initial Merge (Builder + JQS -> Unified System)

- Merged `system_new/` (Builder) and `JQS_Code/` (execution engine) into single FastAPI service
- Single MySQL database `wa-unified-mysql` (port 3308) with 13 tables
- `arms` table: added `camera_id` and `active` fields for multi-machine support
- `ArmClient` class + `Camera` class (instance-based, not global variables)
- `ArmWorker` + `WorkerManager` for multi-arm task processing
- All action functions accept `arm`/`cam` instance parameters
- Seed data exported from `builder-mysql` (real recorded flows)
- All Builder routes + static files + calibration data migrated

## Bug Fixes

- **Camera not enabled in Worker** — Builder's Camera class has `_enabled` gate; Worker never called `camera_enable()`. Fixed: auto-enable on Worker start.
- **`score` uninitialized in CHECK_SCREEN** — If all captures fail, `score` was never assigned. Fixed: `score = 0.0` before loop.
- **keymaps `keyboard_type` truncated** — `VARCHAR(20)` too short for `s1_cimb_account_number` (22 chars). Fixed: `VARCHAR(50)`.
- **`calibration_router.py` parameter mismatch** — Route passed `pen_offset_x/y` kwargs but function expected `(station_id, data)` dict. Fixed: `data.pop("station_id")` pattern.
- **`mysqldump` warning in seed.sql** — First line `mysqldump: [Warning]...` treated as SQL. Fixed: removed warning line.
- **seed.sql data source** — Initially used JQS placeholder data instead of real builder-mysql data. Fixed: re-exported from builder-mysql.

## UI Upgrades

- **Dashboard** — Machine status cards with Pause/Resume/Offline/Reset buttons (WebSocket real-time)
- **Live Logs** — Terminal-style log panel (black bg, colored levels, auto-scroll, arm selector)
- **Transactions page** — List + detail + step logs + screenshot viewer + retry failed
- **Settings page** — Full CRUD for Arms/Stations/Phones/Bank Apps (standalone page)
- **Navigation** — Added Settings and Transactions links to all pages

## Multi-Arm Improvements

- **Arm -> Station linkage** — Recorder station dropdown dynamically filters by selected arm
- **Settings filter** — Recorder Settings modal filters data by current arm
- **Debug lock** — Connect arm requires Worker to be paused first (prevents conflict)
- **WebSocket merged status** — Pushes DB arm status + Worker memory status together

## Calibration

- **Migrated to database** — New `calibrations` table replaces JSON files
- **Dynamic query** — `get_all_calibrations()` queries all stations, no hardcoded `range(1,5)`
- **All functions async** — `calibration.py` rewritten for DB access
- **3-point auto-calibration** — `POST /api/calibration/auto-calibrate` (template matching + matrix calculation)
- **Manual fallback** — If template matching fails, user clicks reference in 3 photos
- **Calibrate button** — Added to recorder nav bar, full calibration UI in modal

## Flow Binding to Arm

- **`flow_templates.arm_id`** — New column binds flows to specific arms
- **Worker query** — Prioritizes arm-specific flow, falls back to `arm_id IS NULL`
- **Builder filter** — Flow list only shows flows for selected arm
- **Create with arm_id** — New flows auto-bound to current arm
- **Copy Flow** — Duplicate flow + steps to another arm (coordinates not copied)

## OCR Configurable Verification

- **Configurable fields** — Choose which fields to verify: account_no, amount, account_name
- **Receipt status** — Verify transaction result (success/review/failed keywords per bank)
- **JSON config** — Stored in `flow_step.description`, same pattern as CHECK_SCREEN
- **Builder UI** — Checkbox fields + receipt status keyword inputs in step editor
- **Backward compatible** — Old steps without config fall back to account + amount verification

## Audit Fixes — Non-blocking Architecture

- **ThreadPoolExecutor per worker** — All blocking arm/camera calls run in dedicated threads via `run_in_executor`, never block the async event loop
- **`asyncio.sleep` everywhere** — Replaced all `time.sleep` in async code (actions.py, keyboard_engine.py, arm_worker.py)
- **`_hw(executor, func, *args)` helper** — Consistent pattern for wrapping blocking hardware calls
- **Silent fallback fixed** — `_get_arm`/`_get_cam` return error dict instead of falling back to wrong default arm/camera
- **Dynamic worker creation** — `manager.add_worker(arm_id)` creates worker without restart; called automatically on `POST /api/stations/arms`
- **Worker lifecycle cleanup** — `stop_all()` and `set_offline()` properly close arm ports and cameras
- **WorkerLogHandler scoped** — Attached to `app` logger (not root); filters by arm name; removed on `stop()`
- **WebSocket error handling** — Exceptions logged and sent to client instead of silently swallowed
- **COM port backoff** — Hardware errors trigger 30s pause before retrying
- **Frontend state reset** — `onArmChange` resets all cached coords, position, step index
- **Reference image paths unified** — `opencv_router.py` now uses `references/{bank_code}/{name}.jpg` (same as `screen_checker.py`)
- **`arm_id` passed everywhere** — All test-step, opencv/compare, opencv/capture-reference calls include arm_id
- **Recorder error handling** — All arm endpoints return `{success, error}` JSON, no HTTPException 500s
- **Worker DB status sync** — Worker sets `arms.status = 'idle'` on startup

## PAS Callback + Stall Logic Redesign

- **Status codes**: 1=success, 2=fail (step or receipt), 3=in-review, 4=stall (OCR unrecognizable)
- **Pre-transfer OCR fail → status=4, pause arm** — Any mismatch means potential config/hardware issue
- **Post-transfer OCR result → status 1/2/3** — Based on receipt keyword matching (success/fail/review)
- **Post-transfer OCR fail → status=4, pause arm** — Can't determine result, need human check
- **Non-OCR step fail → status=2, close app, continue** — Probably transient, safe to try next task
- **No retry** — All failures reported to PAS for human investigation
- **Removed stall_detector 3-photo check** — No longer needed; OCR result is the sole judgment
- **Removed PAS update_account_status/send_alert calls** — PAS handles bundle disable internally
- **All callbacks include receipt screenshot** — PAS always has visual evidence
- **`_ocr_result` stored in transaction dict** — Worker reads OCR outcome to determine callback status

## Random PIN Keypad Support

- **New keyboard type `random_pin`** — For banks with randomized PIN keypads
- **Tesseract per-cell OCR** — Cuts each grid cell from photo, tries 4 preprocessing methods (adaptive threshold, OTSU, fixed threshold, raw gray)
- **Multi-position fallback** — If target digit not found at primary camera position, automatically tries 2 offset positions for different lighting angles
- **`bank_apps.pin` field** — New column for APP PIN separate from transfer password
- **`input_source = "pin"`** — New option in TYPE step to use the pin field
- **Builder UI** — "Random PIN Keypad" option in keyboard type selector, 12-position grid recorder via camera click
- **~1 second OCR** — Tesseract processes 10 cells in ~1s, well within 15-20s PIN timeout
- **Tested 100% success** — Two consecutive real-device tests found correct digit and typed PIN

## Reference Image Storage Restructured

- **Path changed** to `references/{arm_name}/{bank_code}/{name}.jpg`
- **Per-arm isolation** — Different arms have different cameras/lighting, references not shared
- **Fallback** — If arm-specific reference not found, falls back to `references/{bank_code}/{name}.jpg` (legacy)
- **All callers updated** — opencv_router, screen_checker, recorder.html

## Audit Fixes Round 2 — Worker Lifecycle, Schema, Behaviour

### WorkerManager Rewrite
- **`asyncio.Lock`** — Added `_lock` to prevent race conditions when concurrently adding/removing workers
- **`_remove_worker(arm_id)`** — New atomic operation: cancel task → await → `_cleanup_arm()` → `stop()`. Single point for all worker teardown
- **`stop_all()` order fixed** — Was calling `stop()` (shuts executor) before `_cleanup_arm()` (which needs executor). Now: cancel task first, then cleanup, then stop
- **`set_offline()` now fully removes worker** — Previously only paused+cleaned, leaving a zombie worker with closed camera. Now removes from memory so `resume()` creates a fresh instance (guaranteeing `camera_enable()` runs)
- **`add_worker()` returns bool** — Returns False if arm not in DB, True on success
- **`resume()` returns bool** — Propagates `add_worker()` result instead of always returning True

### Worker Lifecycle via Settings
- **`update_arm()` syncs runtime** — When `active=0`, calls `manager.set_offline()`; when `active=1`, calls `manager.resume()`. Previously only changed DB
- **`delete_arm()` stops worker** — Cancels task and removes worker from memory before deleting DB record. Previously left zombie workers

### Schema Fix
- **`flow_steps.description` VARCHAR(255) → TEXT** — OCR config JSON, receipt keywords, and CHECK_SCREEN config can easily exceed 255 bytes. Applied ALTER TABLE on live DB

### Data Integrity
- **`copy_template`** — Now catches duplicate key constraint and returns a friendly error instead of 500
- **`delete_phone`** — Checks for dependent bank_apps before deleting; returns error instead of DB exception
- **`delete_station`** — Checks all dependent tables (phones, bank_apps, ui_elements, keymaps, swipe_actions, keyboard_configs, calibrations) before deleting
- **`delete_arm` dead code removed** — The transaction check after the station check was always an empty result set; removed
- **`create_arm` / `update_arm` check worker return value** — `add_worker()` and `resume()` results now propagated to caller; DB-success-but-worker-fail returns `{"success": false, "error": "..."}` instead of swallowing the failure
- **`set_offline` warning log** — Logged before `_remove_worker()` (while handler is still attached) using arm_name so it appears in Live Logs; clarifies that offline is temporary and arm auto-resumes on service restart if `active=1`

### OCR Behaviour
- **`OCR_REQUIRED` config** — New env var (default `true`). When true, missing OCR engine raises RuntimeError (task fails, arm pauses) — consistent with OCR verification failure behaviour. When false, skips with warning
- **`pytesseract` added to requirements.txt** — Was missing despite being imported in `keyboard_engine.py`
- **`TESSERACT_CMD` unified in `ocr.py`** — The generic OCR fallback now also reads `TESSERACT_CMD` from config, same as the random PIN path

### Dead Code Removal
- **`/api/monitor/transactions/{id}/retry` endpoint deleted** — Violates no-retry principle; frontend button was already removed
- **`retryTx()` JS function deleted** — Dead code in `transactions.html`, no HTML element called it
- **`app/stall_detector.py` deleted** — Zero imports across entire codebase; stall logic replaced by OCR-based worker pause

### Reference Image Management
- **`delete_reference` supports arm path** — Added `arm_id` query param; now tries `references/{arm_name}/{bank_code}/{name}.jpg` first, falls back to legacy path

### Flow Builder UI
- **`list_templates` includes global fallback** — When querying with `arm_id`, now also returns `arm_id IS NULL` templates so the Builder UI shows what the worker will actually use

## Deployment & Maintenance

- **Tesseract OCR** — Added to system requirements (`C:\Program Files\Tesseract-OCR\`)
- **`TESSERACT_CMD`** — Configurable in `.env` or `config.py`
- **Test files cleaned** — Removed all `deploy/test_*` and debug files
- **`db/export_seed.py`** — One-click export current DB to seed.sql for backup
