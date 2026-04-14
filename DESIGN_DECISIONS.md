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
