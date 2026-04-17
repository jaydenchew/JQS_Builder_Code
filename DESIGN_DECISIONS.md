# Design Decisions (ADR)

Architectural and design decisions that may look like bugs to someone unfamiliar with the business context. Each entry explains **what** the code does, **why** it was chosen, and **what alternatives were considered**.

---

## DD-001: Only Withdrawal Endpoints Have API Authentication

**What**: `/process-withdrawal` and `/status/{process_id}` require `X-Api-Key` + `X-Tenant-ID` headers. All other endpoints (monitor, flows, coordinates, stations, banks, recorder, stream) have no authentication.

**Why**: The system runs on a dedicated machine. FastAPI binds to `127.0.0.1` (localhost only). External access comes through Cloudflare Tunnel (or ngrok during testing) which only exposes the withdrawal and status paths. Builder UI, Dashboard, and all configuration APIs are only accessible from the machine itself.

**Alternative considered**: Add authentication to all 70+ endpoints. Rejected because it adds complexity with no real benefit — the network boundary already isolates these endpoints. If deployment model changes (e.g., shared network + `0.0.0.0`), this decision should be revisited.

---

## DD-002: Single Worker Per Arm (No Task Locking)

**What**: `_fetch_next_task()` does a simple `SELECT ... WHERE status='queued' LIMIT 1` followed by a separate `UPDATE ... SET status='running'`. There is no `SELECT FOR UPDATE` or atomic claim mechanism.

**Why**: `WorkerManager` guarantees exactly one worker per `arm_id` (dictionary keyed by arm_id, checked on add). There is no scenario where two workers compete for the same task. Adding row-level locking would be defensive coding against an impossible condition.

**Alternative considered**: `UPDATE ... WHERE status='queued' LIMIT 1` atomic claim. Rejected as unnecessary complexity given the single-worker-per-arm guarantee.

---

## DD-003: Unknown Action Type Silently Succeeds

**What**: `execute_step()` logs a warning and returns `True` (success) when encountering an unknown `action_type`.

**Why**: All action types are written by the Builder frontend from a fixed list (CLICK, TYPE, SWIPE, PHOTO, OCR_VERIFY, CHECK_SCREEN, ARM_MOVE). Unknown values can only appear from manual database edits or future action types not yet implemented. Failing the entire transaction for an unknown step would be disproportionate — better to skip and let the flow continue.

**Alternative considered**: Raise RuntimeError to stall the arm. Rejected because it penalizes the user for a configuration issue that may not affect the transfer outcome.

---

## DD-004: Fallback Queries (bank_code IS NULL) in Execution

**What**: `lookup_ui_element` and `lookup_swipe` fall back to `bank_code IS NULL` entries if no bank-specific coordinate is found. Management APIs do not show these fallback entries.

**Why**: This supports "shared coordinates" — positions that are the same across all banks on a station (e.g., a fixed camera position). The fallback is a compatibility mechanism from the early system when coordinates were not bank-specific.

**Why management APIs don't show fallback**: Currently no shared coordinates are in active use. All coordinates are bank-specific. Adding fallback visibility to the UI would add confusion for operators. If shared coordinates become needed again, the management API should be updated.

---

## DD-005: Response Structure Mixed (Pydantic vs Dict)

**What**: Withdrawal routes use `StandardResponse(status=bool, message=str)` Pydantic models. Monitor, flows, coordinates, and other management routes return raw dicts like `{"success": True}` or `{"error": "..."}`.

**Why**: Withdrawal routes are the external API (called by PAS) and benefit from strict typing. Management routes are internal (called by the Builder UI JS code that already handles both formats). Retrofitting all routes to Pydantic would require changing both backend and frontend simultaneously with no functional benefit.

**Future direction**: New routes should use Pydantic models. Existing routes migrate gradually.

---

## DD-006: Resume Writes status='idle' Immediately

**What**: `resume_arm` sets `arms.status='idle'` in the database even though the worker might pick up a task and become `busy` milliseconds later.

**Why**: When an arm stalls, the status is set to `offline`. On resume, it must be changed back to `idle` so that new withdrawal requests are accepted (the withdrawal endpoint checks `arms.status != 'offline'`). The brief idle→busy transition is normal and harmless. The worker updates its own status to `busy` when it picks up a task.

**Alternative considered**: Don't write status on resume, let the worker manage it entirely. This was tried and caused a regression: the arm stayed `offline` in DB after resume, blocking all new requests.

---

## DD-007: Pause Does Not Write DB Status

**What**: `pause_arm` only sets `_paused=True` in memory. It does not update `arms.status` in the database.

**Why**: When pause is requested, the current task may still be running. Writing `idle` would be a lie. Writing `paused` would require adding a new ENUM value to the schema. The worker will naturally update its status when the current task finishes. The `get_status()` method returns `paused` from memory for the Dashboard to display correctly.

---

## DD-008: Camera capture_fresh() Reopens Camera

**What**: `capture_fresh()` closes and reopens the camera every time, instead of just reading a frame.

**Why**: DSHOW (DirectShow) on Windows buffers frames internally in a FIFO queue. When the camera is open but nobody reads for 30-60 seconds (during arm clicks/typing), hundreds of stale frames accumulate. There is no reliable way to flush this buffer — `grab()` count-based flush, time-based flush, and `CAP_PROP_BUFFERSIZE=1` all failed in testing. Reopening the camera is the only method that guarantees a real-time frame.

**Performance impact**: ~300-400ms per capture_fresh call. Acceptable because PHOTO/OCR_VERIFY/CHECK_SCREEN steps already have multi-second delays for screen loading.

**capture_frame() still exists**: Used only for MJPEG streaming where frames are read continuously (no buffer buildup).

**Release after capture**: `capture_fresh()` closes the camera immediately after reading a frame, not at task end. This reduces the exclusive lock window from minutes (entire task) to ~400ms (open→read→close). Multi-arm concurrent photo steps no longer block waiting for each other's tasks to finish.

---

## DD-009: SAME/INTER Flows Use _inter Suffix

**What**: When recording or copying an INTER flow, all step names automatically get `_inter` appended (e.g., `select_account` → `select_account_inter`). This also affects `ui_element_key`.

**Why**: `ui_elements` is keyed by `(bank_code, station_id, element_key)`. If SAME and INTER flows share step names, they share coordinates. But many steps have different screen positions in SAME vs INTER flows (e.g., "select account" button is at a different position). Without the suffix, saving one flow overwrites the other's coordinates.

**Enforcement**: Builder `readForm()` auto-appends suffix. `copy_template` API auto-renames when changing transfer_type. `saveFlow()` validates step_name uniqueness.

---

## DD-010: Handler Flow Uses Its Own bank_code

**What**: When CHECK_SCREEN runs a popup handler flow (e.g., `ACLEDA_AFTER_POPUP__15`), the handler steps look up coordinates under the handler's bank_code (`ACLEDA_AFTER_POPUP`), not the main flow's bank_code (`ACLEDA`).

**Why**: The handler flow is a separate template with its own `bank_code`. Its steps (like `close_popup`, `tick_do_not_show_again`) may only exist for the handler, not for the main bank. Using the main flow's bank_code would cause "UI element not found" errors.

**How**: The handler reference string format is `BANK_CODE__TEMPLATE_ID`. `_run_handler_flow` extracts `parts[0]` as the bank_code for all handler step executions.

---

## DD-011: Stall Auto-rejects All Queued Tasks

**What**: When an arm stalls, all `queued` transactions for that arm are immediately failed and reported to PAS with status=4.

**Why**: A stalled arm cannot process any more tasks until a human inspects and resumes it. Leaving tasks in the queue would cause PAS to wait indefinitely for callbacks that will never come. Auto-rejecting lets PAS know immediately so it can route to other channels or notify the operator.

---

## DD-012: No Automatic Transaction Retry

**What**: Failed/stalled transactions are never automatically retried by WA.

**Why**: The system cannot know the state of the banking app after a failure. The transfer might have partially completed (e.g., reached the confirmation screen). Retrying could result in a double transfer. Human inspection is required to determine what happened before any recovery action.

---

## DD-013: Log Timestamps Use Local Time

**What**: Worker log buffer uses local `HH:MM:SS` format, while PAS callback timestamps use UTC.

**Why**: Logs are displayed on the Dashboard for human operators sitting at the machine. Local time is more intuitive for real-time monitoring. PAS callbacks use UTC because they cross system boundaries and need timezone-unambiguous timestamps for reconciliation.

---

## DD-014: process_id is INT (Not BIGINT)

**What**: `transactions.process_id` is `INT` (max ~2.1 billion).

**Why**: PAS assigns process_ids. Current volume is low (hundreds per day). INT capacity is sufficient for decades of operation. If PAS changes to larger IDs, migration to BIGINT is a single ALTER TABLE.

---

## DD-015: Cloudflare Tunnel Runs via NSSM (Not Native Service)

**What**: `cloudflared` is installed as a Windows service using NSSM (service name `CF-Tunnel`), not via `cloudflared service install`.

**Why**: `cloudflared service install` registers the service under LocalSystem account, which looks for config files in `C:\Windows\System32\config\systemprofile\.cloudflared\`. This is a different directory from the user's `~/.cloudflared/` where `cloudflared tunnel login` stores credentials. Even when config files are manually copied to the system directory, YAML formatting issues and permission problems cause the service to fail silently.

NSSM runs the service as the actual user (`ObjectName = .\username`), so it naturally reads from `C:\Users\<user>\.cloudflared\config.yml` where credentials and config are stored. This matches the manual `cloudflared tunnel run` behavior exactly.

**Alternative considered**: Copying config + credentials to system profile directory. Attempted and failed due to YAML encoding issues, path escaping, and no useful error messages from the service on failure.

---

## DD-016: OCR Uses Tesseract for Digits, EasyOCR for Text

**What**: When `field_rois` is configured, numeric fields (account_no, amount) are OCR'd with Tesseract + digit whitelist, while text fields (name, receipt_status) use EasyOCR.

**Why**: EasyOCR is a general-purpose OCR that tries to recognize all characters. For fields that only contain digits (bank account numbers, amounts), this generality works against it — it may misread `1` as `l`, `0` as `O`, or miss decimal points. Tesseract with `tessedit_char_whitelist=0123456789.` constrains the search space to only digits, dramatically reducing misrecognition.

For text fields (customer names, receipt status keywords), Tesseract's character-level approach is weaker than EasyOCR's neural network for mixed-case multi-word text. So each engine is used where it excels.

**Preprocessing**: All field crops get CLAHE contrast enhancement + 3x bicubic upscale + white border padding. Numeric fields additionally iterate through 6 preprocessing variants × 2 Tesseract PSM modes (6 and 7) = 12 Tesseract attempts:
- `inverted`, `adapt_inv`, `otsu_inv` (inverted + adaptive/OTSU threshold)
- `direct`, `adapt_direct`, `otsu_direct` (non-inverted equivalents)

**Smart match (not first-non-empty)**: When `expected` value is provided, the loop keeps trying until a method produces text that matches the expected account/amount (using the same match function the verifier will use). This prevents picking up the first noisy-but-nonempty result and failing verification. If no method matches, the first non-empty Tesseract result is kept for logging.

**Fallback**: If all 12 Tesseract attempts fail to match, EasyOCR is tried with 4x upscale in both direct and inverted variants (2 attempts). If still no match, the best Tesseract result (or last EasyOCR result) is returned so the failure log shows what was seen.

**No `field_rois` path**: The old single-ROI or fullscreen EasyOCR path is used unchanged — meta is not collected for this path (see DD-019).

---

## DD-017: ArmWorker Wakeup Is Event-driven, Not Polled

**What**: `ArmWorker.run()` uses `asyncio.Event` to wait for new tasks. `/process-withdrawal` calls `manager.notify_worker(arm_id)` after a successful `queued` INSERT, which sets the event and immediately wakes the worker. A 30-second `wait_for` timeout is kept as a safety net.

**Why**: The previous implementation slept 2 seconds between queue polls. At low volume this meant every new task waited 0–2 seconds before the worker noticed it — pure wasted latency. Event-driven wakeup drops this to near zero.

**Why keep the 30s timeout**: `notify_worker` is only called from `/process-withdrawal`. If the service is restarted while tasks exist in the queue (e.g., from the startup recovery path), no notify will fire. The 30s fallback ensures the worker still picks up pre-existing tasks after at most 30 seconds.

**Event lifecycle**: Events are created in `WorkerManager._create_worker()` (covering both `start_all()` startup and dynamic `add_worker()` paths) and removed in `_remove_worker()`. `notify_worker()` silently no-ops if the arm has no event (worker was removed).

**Why not just call `notify_worker` anywhere a task status changes**: The only source of new queueable tasks is `/process-withdrawal`. `_fail_queued_tasks` is called from within the worker's own loop — no external wakeup needed. Simpler contract = fewer bugs.

---

## DD-018: Stall Reason Is Classified by Keyword Matching

**What**: `ArmWorker._classify_stall_reason(error_msg)` maps free-text error messages to one of 7 categories (`arm_hw_error`, `flow_not_found`, `ocr_mismatch`, `screen_mismatch`, `camera_fail`, `step_failed`, `unknown`) using case-insensitive substring matching.

**Why**: The error messages are produced by many different code paths (hardware client, OCR, screen checker, flow loader, action executor). Adding structured exception types everywhere would touch ~20 files. Keyword matching on the final error string is a single point of classification that catches all current and future error paths, at the cost of being slightly brittle if error messages are reworded.

**Match order matters**: Most specific patterns first (`port open failed`, `no active flow`), then topic keywords (`ocr`, `screen does not match`, `camera`). This prevents a hardware error whose message happens to contain "camera" from being misclassified as `camera_fail`.

**Why not store the full stacktrace**: `stall_details` already stores `Step <name>: <error_msg>`. Full traces belong in `service_stderr.log`. The DB column is meant for at-a-glance Dashboard display, not forensic debugging.

---

## DD-019: OCR Meta Is Stored in transaction_logs.message as JSON

**What**: `_ocr_field` returns `{"text", "method", "engine", "attempts", "latency_ms"}`. `verify_configurable` aggregates per-field meta into a single dict. `execute_ocr_verify` JSON-serializes it into `transaction_logs.message`.

**Why `message` column (not a new column)**: `message` was previously used to store the raw OCR text on failure (`None` on success). Success writes were wasted space. Repurposing the column for structured meta JSON on success (and `ocr_text | meta=<json>` on failure) gives us observability for free without a schema change.

**Why not a separate `ocr_meta` column**: The data is already transaction-log-scoped (one row per OCR_VERIFY step). Adding a column means a migration and breaks the symmetry with other action types that also use `message`. JSON in TEXT is good enough for occasional manual inspection or future log-mining scripts.

**Backward compatibility**: Old logs (before this change) have `message=None` on success and `message=<ocr_text>` on failure. New code handles both: failure meta is prefixed with the OCR text so grep still works, and JSON-parsing code should guard against non-JSON values.

---

## DD-020: Camera Verify/Swap Allowed on Idle Workers (Not Just Paused/Offline)

**What**: `/api/monitor/arms/{id}/camera-preview` and `/api/monitor/arms/swap-camera` accept any worker state except `busy`. The Dashboard `↻ Verify` button is enabled for `idle`, `paused`, `offline`, `no_worker` and only disabled for `busy`.

**Why**: Workers auto-start to `idle` on every service start. If verify required `paused/offline`, the post-restart "auto-expand all previews to remind operators to check camera mapping" feature would never trigger after a normal startup — defeating the entire reason the feature exists. The original conservative `paused/offline only` policy was a planning mistake corrected after testing.

**Why idle is safe for `capture_fresh`**: `Camera.capture_fresh()` acquires the per-instance `_lock` plus the class-level `_init_lock`. If a queued task arrives during the ~0.5s capture window, the worker's own camera operations wait on the same lock and run after — no corruption, just a sub-second serial delay.

**Why idle is safe for `restart_worker`**: An idle worker has no `_current_task`, so cancelling its asyncio task only interrupts the `wait_for(event, 30)` wakeup loop. Queued tasks remain `status='queued'` in the DB and are picked up by the freshly recreated worker on its first `_fetch_next_task` iteration. The only observable effect is a sub-second gap in arm availability.

**Why busy is forbidden**: Mid-task `capture_fresh` from outside the worker would corrupt camera state during, e.g., an `OCR_VERIFY` step. Mid-task `restart_worker` would cancel the running task with no clean rollback (transaction would be left `status='running'`). Both cases would cause real data loss.

**Alternative considered**: A "pause both → swap → resume both" wrapper button that auto-orchestrates state transitions. Rejected because the swap endpoint already does the moral equivalent atomically (idle worker is "as good as paused" from the perspective of cancellation safety).

---

## DD-021: Service Status Indicator Lives in the Global Nav, Not Per-Page

**What**: The MySQL/Arm WCF/Cloudflare Tunnel/WA Service status block is rendered by `loadNavServices()` in `static/js/api.js` and injected into the shared nav bar by every page that uses `<div id="nav">`. The Dashboard body no longer has its own copy.

**Why a single global indicator**: Operators need to know if the underlying services are up no matter which page they're on. Previously, only the Dashboard showed this — going to Builder/Settings/Transactions hid the indicator, forcing a navigation back to Dashboard just to check status. Worse, the per-page approach meant if we ever added the panel to other pages, each would need its own copy of `loadServices` + interval timer.

**Why polling is in `api.js`, not in each page**: The nav is rendered by `api.js` already (`navHTML()` + `DOMContentLoaded` handler). Adding the polling there guarantees that any page including `<script src="/static/js/api.js">` gets the indicator for free. Pages that use a custom nav (e.g., Flow Builder's `builder-nav`) opt out simply by not having `<div id="nav">` — `loadNavServices` early-returns if the element doesn't exist.

**Why click-to-expand instead of always-visible details**: The summary pill ("Services" with one dot) takes ~80px of nav width. Showing all 4 services inline would push the nav past 600px and crowd page navigation links. Click-to-expand keeps the nav lean while preserving full detail one click away. Hover tooltip provides a quick read without a click.

**Why 30s polling, not WebSocket push**: Service status changes infrequently (a tunnel/MySQL going down is rare). `/api/monitor/services` runs four short health checks (DB query, HTTP HEAD, sc.exe query, in-process uptime) — cheap to run but pointless to push more often than needed. WebSocket would also need every page to maintain the connection just to show 4 dots, which is wasteful.
