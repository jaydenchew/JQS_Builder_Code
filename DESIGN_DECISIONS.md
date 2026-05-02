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

## DD-011: Stall Auto-rejects All Queued Tasks (Superseded by DD-024)

**Status**: Superseded — applies only to hardware errors (`port open failed` / `not responding`).

**What (legacy)**: When an arm stalled, all `queued` transactions for that arm were immediately failed and reported to PAS with status=4.

**Why (legacy)**: A stalled arm could not process any more tasks until a human inspected and resumed it. Leaving tasks in the queue would cause PAS to wait indefinitely for callbacks that would never come.

**Update (2026-04-29)**: PAS now serializes requests (one task at a time, never overlapping), so under normal operation no queue exists during a stall. Soft errors (OCR mismatch, screen mismatch, click error, etc.) take the new self-recovery path defined in DD-024 — arm closes the open APP, returns to idle, no queue rejection. Queue auto-rejection still runs for hardware errors because the arm cannot self-recover when the COM port is unreachable.

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

---

## DD-022: CHECK_SCREEN Uses ORB+Similarity Align, Not Homography, Pure ORB, or OCR

**What**: `screen_checker.compare_screen()` uses **ORB feature match → RANSAC Similarity transform (4 DoF) → warpAffine → masked SSIM**. A three-tier gate (`inliers >= 25 AND aligned_ssim >= threshold AND valid_ratio >= 0.60`) decides pass/fail. `reason` ∈ `{"match", "popup_detected", "wrong_screen", "alignment_failed"}` is attached to every result for diagnosis.

**Why align-then-compare instead of direct SSIM/edge** (the old implementation): Real-world phone-rack photos drift a few pixels between pick-up/put-down even in a fixed cradle. Pixel-locked SSIM penalizes that drift linearly, so a correctly-displayed page reads SSIM ~0.5 on a good day, ~0.3 on a bad day. POC on 21 real rack photos: old algorithm passed 0/21, new algorithm passed 18/18 and correctly rejected 3/3 wrong pages. The algorithm change is not a tuning adjustment — it's an algorithmic correction for a physical reality the old algorithm couldn't compensate for.

**Why Similarity (4 DoF), not Homography (8 DoF)**: The physical setup is a fixed camera on a fixed mount pointing at a phone in a fixed cradle. The only possible displacement modes are:
- Translation (phone shifted a few mm in cradle) — 2 DoF
- Rotation (phone picked up tilted then replaced) — 1 DoF
- Uniform scale (camera/phone distance changed microscopically) — 1 DoF

Perspective distortion requires the camera plane to rotate relative to the phone plane, which cannot happen in this rig. Homography fits 4 extra DoF the data cannot support; on noisy ORB matches it produces trapezoidal distortions that warp a correct phone screen into a quadrilateral and blow up `valid_ratio`. POC observation: on a deliberately-wrong `test06`, Homography warped the phone image into a clearly non-physical shape while Similarity cleanly refused to fit (low inliers), which is the correct outcome.

**Why three gates, not just inliers**: Pure ORB+RANSAC inliers is robust to movement but fooled by two structurally-similar pages. POC negative case: a different in-app screen on the same phone hit 41 inliers (would PASS at `MIN_INLIERS=25`). Adding the SSIM gate on the aligned images cleanly catches it (SSIM = 0.58, rejected). Conversely, pure SSIM even on aligned images is fooled by popups that preserve most of the page pixels. So each gate has an irreducible job:
- `inliers >= 25` — "this is the correct page" (structure)
- `aligned_ssim >= threshold` — "the correct page isn't obscured" (content)
- `valid_ratio >= 0.60` — "alignment covered enough of the ROI to trust the SSIM result" (quality check)

Any single-gate approach has a known failure mode; the dual-gate (inliers + SSIM) matches the two operational failure modes we see in practice (wrong page vs popup). `valid_ratio` is a cheap third safety net, mostly guarding against degenerate transforms.

**Why not OCR as a CHECK_SCREEN signal**: POC `test07` was a correct page with a popup overlay. OCR read un-obscured background text (the popup covered ~35% of the page, text outside still matched the expected keywords) and returned PASS. The whole point of `CHECK_SCREEN` is catching popups before the robot arm clicks through them; a signal that silently accepts popups is worse than useless. OCR stays for `OCR_VERIFY` (explicit text-content check) — it's the wrong tool for "is this the right unobstructed page".

**Why ORB runs on the full image, not inside the ROI**: Counterintuitive but measured. The phone bezel and fixed UI chrome (status bar, nav bar) are the most reliable alignment anchors — they don't change between screens. User-configurable ROI is the interesting content region, typically the middle 65% of the page, which in negative cases has nearly-identical structure to the reference. Extracting ORB features only inside the ROI cuts keypoints by ~70% and makes RANSAC unstable. The algorithm runs ORB on the full image, applies the Similarity transform to the full image, and only scopes the SSIM comparison to the ROI. This way ROI still does its job (ignore dynamic zones) without starving the aligner.

**Why thresholds are module constants, not DB/UI fields** (`MIN_INLIERS=25`, `MIN_VALID_RATIO=0.60`, `RATIO_TEST=0.75`, `SCALE_TOLERANCE=(0.85, 1.15)`): They are engineering invariants of the algorithm, not operational knobs. An operator tuning `min_inliers` to 5 because "it keeps failing" would be defeating the wrong-screen gate entirely and is almost certainly the wrong fix. The only operator-tunable knob is `threshold` (aligned SSIM), because that's the one threshold that genuinely varies per-page (a text-heavy page rests around 0.95, a mostly-blank page can dip to 0.85). Everything else is either a RANSAC parameter or a sanity check on the algorithm's output.

**Why return a rich dict instead of (bool, float)**: The tuple loses diagnostics that are expensive to recover after the fact. `inliers` distinguishes "wrong page" from "correct page, popup on top" — same SSIM, different reasons, different operator response. `rot_deg` is a leading indicator of the cradle drifting (if rot creeps from 0.1° to 2° over a week, the cradle needs re-seating; catch it before it breaks). `ms` is free performance monitoring. The dict is self-documenting, the tuple unpacking at call sites was only marginally shorter, and only 2 call sites had to change. HTTP response keeps `match`/`score`/`threshold` aliases so frontend JS is zero-touch.

**What this does NOT change**: `execute_check_screen` control flow is identical — still retries up to `max_retries`, still calls `handler_flow` between retries, still raises `RuntimeError` on final failure. `reason` is logged and stored but does not branch. Smarter stall classification (e.g., route `reason=popup_detected` to handler-retry but `reason=wrong_screen` straight to stall) is a future, opt-in change on top of the data now being captured.

**Rollback**: Single-file revert of `app/screen_checker.py` + `app/actions.py` unpacker + `app/routers/opencv_router.py` delegate + `static/recorder.html` defaults. No schema, env var, or API contract changes. Stored `flow_steps.description` JSON is forward-compatible (old `threshold=0.70` still works, just overly loose, which CHANGELOG flags).

---

## DD-023: Calibration Uses Fiducial Card + Least-Squares Affine Fit, Not 3-Point Auto

**What**: Calibration (`/api/calibration/fiducial-save`) takes 5 anchor points (4 corners of a 50&times;50mm calibration card + card crosshair center) and fits a full 2x3 affine matrix via `np.linalg.lstsq`. RMSE is reported and the endpoint refuses to save if RMSE exceeds 2mm. The old 3-point method (move arm to A, B=A+(0,10), C=A+(10,0), match template in each photo) was deleted.

**Why delete the 3-point method rather than keep it as fallback**: It was producing bad calibrations reliably on at least one deployment. Keeping broken code around as "fallback" is worse than removing it because operators will re-run the bad method when the new one surfaces an issue, masking the real problem. The fiducial card method's worst failure mode is "RMSE too high, refuse to save" &mdash; a loud, obvious failure that sends the operator back to investigating the root cause (card placement, mechanical mounting, arm wear) rather than silently storing a wrong matrix.

**Why fit a full 2x3 affine instead of hardcoding a diagonal scale + translation**: The existing pipeline (`pixel_to_arm` in `app/calibration.py:97`) does `M @ [raw_x, raw_y, 1]` on the stored `transform_matrix`. Nothing in that pipeline assumes `M[0][1] == 0` or `M[1][0] == 0`. The old `_compute_calibration` was already fitting a full 2x2 in the upper-left and storing the translation in the third column. Writing our new matrix as `[[sx, 0, tx], [0, sy, ty]]` would throw away the one degree of freedom that encodes camera-mount-to-arm-axis rotation. On one test machine, a calibration returned `rotation_degrees = -45.6°`. Whether that number is real or noise from a collinear 3-point fit is unknown, but the safe engineering choice is to let the data determine the matrix shape, not to hardcode an assumption.

**Why the calibration card, not camera intrinsic calibration or a checkerboard**: The vendor ships this card with the hardware, physically printed with known 50mm &times; 50mm dimensions. Users can visually place it and clearly identify its 4 corners. A full OpenCV-style `calibrateCamera` with a checkerboard would give focal length and distortion coefficients, which the pixel-to-arm pipeline does not use (the arm only needs a 2D affine mapping at the park plane). So the extra complexity of intrinsic calibration buys nothing. The fiducial card gives us exactly the 5 well-distributed 2D anchor points we need.

**Why 5 anchors and not more**: Reading 4 corners gives 4 independent pairs. Adding the crosshair (= geometric center of the 4 corners in pixels, = pen-touch position in arm) gives a 5th pair that's _not_ redundant with the other 4 in pixel space (it's their centroid) but _is_ directly observed in arm space (user moved the pen there). The extra anchor primarily reduces sensitivity to user imprecision on any single corner click. Adding more (say, the 4 outer-card corners) would require the user to click more points for diminishing returns. If RMSE is routinely too high, it's almost always because of corner-click imprecision on the 4 we already have, not because 5 anchors is too few.

**Why require the user to click corners instead of auto-detecting via contours**: We tried mentally sketching this. Auto-detect would be: threshold &rarr; `findContours` &rarr; `approxPolyDP` to 4-point polygon &rarr; filter by expected area &rarr; sort corners. This works in lab conditions but is fragile in the field (paper shadow, glare on the black border, partial occlusion by the pen or fixtures, dust, printer ink variation). User clicking is deterministic, predictable, and takes 4 seconds. If future throughput demands justify auto-detect, it can be added as a "suggest 4 corners, let user adjust" layer without changing the downstream fit.

**Why "card axes parallel to arm axes" assumption is kept**: This is the _one_ remaining assumption. It's baked into the mapping from detected corner pixels to known arm coords (TL corner arm = pen_arm + (-25, -25)). A user rotating the card 5&deg; on the stage would introduce up to (25mm &times; sin(5&deg;)) &asymp; 2mm error at the corners, which would show up as RMSE ~1.5mm (not rejected at the 2mm threshold, but visible in the per-anchor-error breakdown). A 10&deg; rotation would show RMSE around 4mm and be rejected outright. This is acceptable: the UX tells users to visually align the card, the physical card is easy to align against the phone stage's straight edges, and RMSE surfaces egregious deviations.

**Why RMSE threshold = 2mm**: Typical good fits come in at 0.3-0.5mm RMSE. Doubling that gives headroom for normal user-click imprecision (&plusmn;2px per corner &asymp; &plusmn;0.4mm given typical `scale_mm_per_pixel` ~0.2). Going beyond 1mm RMSE means either the card is significantly rotated on the stage, or a corner was misclicked by &gt;5px, or the camera mounting has shifted. All three are conditions that warrant operator attention rather than silent acceptance. `2.0` is a round number with clear headroom above typical noise and clear distance below "something's wrong here."

**What this does NOT change**: `pixel_to_arm`, `save_calibration`, the `calibrations` DB table schema, and every downstream consumer of the transform matrix (production CLICK steps, `keyboard_engine.py`'s random-PIN offset calculation, `settings.html`'s matrix display) are **all unchanged**. The new matrix has the same 2x3 JSON shape, same semantics (`M @ [raw_x, raw_y, 1] = arm_pos_at_park`), same companion fields (`camera_park_pos`, `scale_mm_per_pixel`, `rotation_degrees`, `raw_height`).

**Rollback**: Single commit revert restores the old endpoints and UI. Existing calibration rows (produced by either method) remain usable throughout.

---

## DD-024: Soft Stall Auto-recovers via Per-Arm STALL Flow

**What**: When a flow step fails with a non-hardware error (OCR mismatch, screen mismatch, click anomaly, exception in actions, etc.), the worker no longer pauses or marks the arm offline. Instead it:

1. Captures the stall photo (unchanged).
2. Looks up the arm's STALL flow (`flow_templates WHERE bank_code='STALL' AND arm_id=<self> AND status='active'`) and runs its steps via the normal `actions.execute_step` path. Steps named `done` / `done_inter` are sentinels that break the loop.
3. Calls `_cleanup_arm` (reset to (0,0), close port).
4. Sends PAS callback `status=4` for the failed task.
5. Sets `arms.status = 'idle'` and the worker fetches the next task.

Hardware errors (`port open failed` / `not responding`) keep the legacy DD-011 / pre-DD-024 behaviour: arm goes `offline + paused`, queued tasks rejected, requires human resume.

**Why now**: PAS now serializes withdrawal requests (one task at a time, no queue overlap). With single-task semantics, a soft failure does not cascade; the only thing the system has to guarantee before accepting the next task is that the phone is in a known state (home screen) and the arm is at origin. That can be accomplished mechanically without human inspection.

**Why per-arm STALL flow rather than hardcoded actions**: Each arm controls a different physical phone with different recents/swipe coordinates. The handler-flow precedent (DD-010) already establishes the pattern of "a separate flow_template that owns its own bank_code and coordinates". STALL flow reuses that pattern: `bank_code='STALL'` is recorded once per station independent of any banking app's recordings, the operator authors arbitrary step sequences in Builder, and adding/removing arms requires no code change.

**Why move PAS callback to AFTER cleanup_arm in the stall branch**: PAS may dispatch the next task as soon as it receives the callback. By cleaning up first, we guarantee the arm is physically at origin before PAS knows the stall completed — eliminating a race where the next task could begin while the arm is still mid-cleanup. Success branches keep their original ordering (callback → cleanup) because they don't change arm state expectations for PAS.

**Why error inside STALL flow is swallowed, not re-stalled**: A STALL flow that itself raises would recurse into another stall (infinite loop). Any per-step error (missing coord, swipe out-of-range, etc.) is logged at `WARNING` and the loop continues with the next step. If the entire flow fails, `_cleanup_arm` still runs and the arm still returns to idle. The transaction was already marked stall + reported to PAS before the close flow ran, so even total failure of the close flow doesn't lose the failure record.

**Why DB `transactions.status='stall'` is set BEFORE running the close flow**: If the close flow or cleanup crashes (process kill, hardware fault mid-recovery), the transaction is still recorded as stall in the database. The PAS callback may not have been sent yet (`callback_sent_at IS NULL` is the signal), but the truth-of-record is consistent.

**What this does NOT change**:
- DD-012 (no automatic retry) still holds — a stalled transaction is never re-queued or re-attempted by WA.
- The success path's PAS callback timing.
- `stall_reason` / `stall_details` semantics — written on stall, cleared on next successful task.
- Hardware error handling (DD-011 still applies for that subset).

**Files**: `app/arm_worker.py` only. New method `_run_stall_close_flow`, restructured `_process_task` failure branch with `is_hardware_error` flag, per-branch `_cleanup_arm` calls (replacing the previous shared call).

**Rollback**: Single-file revert restores the legacy "always offline + paused on stall" behaviour. STALL flow_template rows in the database become inert (no code reads them).

---

## DD-025: FIND_AND_CLICK Uses Template Crop + Inverse-Projected ROI

**What**: New `flow_steps.action_type` value `FIND_AND_CLICK` locates a button at runtime via `cv2.matchTemplate` and / or EasyOCR within an ROI, then converts the pixel hit to arm coordinates with `calibration.pixel_to_arm` and clicks. Fully implemented in `app/find_and_click.py` + a thin `execute_find_and_click` in `app/actions.py`.

**Why this design over alternatives**:

- **`cv2.matchTemplate`, not ORB**: CHECK_SCREEN already uses ORB+Similarity for whole-screen alignment. For locating a small button that *translates within* an ROI, `matchTemplate` is more direct: its score is interpretable as "how well does this template match here", and there's exactly one peak per real button. ORB would over-engineer for cases the user explicitly described (banner shifts UI by a small amount; no scale or rotation change).
- **Template is a separate small crop, not the existing reference image**: CHECK_SCREEN stores whole rotated frames at `references/<arm>/<bank>/<name>.jpg`. FIND_AND_CLICK could have reused them by adding a "crop rect" field, but storing a dedicated `<name>_tpl.jpg` (typically 60x60 px) keeps the two namespaces orthogonal: a CHECK_SCREEN reference can change without invalidating an unrelated FIND_AND_CLICK template, and operators don't have to define crop coords inside a JSON config. Storage cost is negligible (template files are <5 KB).
- **ROI percentages are applied to the rotated frame**: same convention as `app/ocr.py` `verify_configurable`. CHECK_SCREEN's ROI applies post-alignment to the reference's gray image, which is conceptually different (it's about where to compare) — that subtle inconsistency was kept because rewriting CHECK_SCREEN's ROI semantics would touch more code than it's worth.
- **Camera offsets follow the random_pin pattern**: `[(0,0), (-2,0), (0,-2)]` by default. First attempt at the recorded anchor; subsequent attempts step into safe directions away from `arms.max_x` / `max_y`. Operators can override `camera_offsets_mm` per step. Boundary-clamped (not skipped) so a misconfigured offset can't crash the arm.
- **`disambiguation` is configurable**: `best_score` works for the common case but operators may hit edge cases (two visually identical icons, banners with the same text). Adding `closest_to_center` and `unique_only` upfront avoids forcing a code change later. Defaults stay friendly.
- **Failure raises into the existing stall path**: instead of building a parallel recovery mechanism, `execute_find_and_click` raises after retries; `arm_worker._process_task` then routes through DD-024's STALL flow (auto-close app, return to (0,0), arm stays idle). This means one stall pathway, not two.
- **Enabled checkboxes are the source of truth, `combine` is an override**: the runtime auto-derives `combine` from `template.enabled` / `ocr.enabled` whenever exactly one provider is on, and only honours an explicit `combine` field when both are enabled (the only case with a real choice). Earlier behaviour treated the three fields independently and silently failed at runtime if a Builder user unchecked Template while the `combine` dropdown still said `template_then_ocr` — now the dropdown becomes inert in that case instead of poisoning the step.

**Why a new ENUM value rather than a flag on CLICK**:

- ENUM keeps the executor dispatch table clean (one handler per type).
- Builder UI's per-action conditional rendering naturally extends with another `else if` branch instead of conditionally branching inside the CLICK form.
- Telemetry (`transaction_logs.action_type`) gets a distinct identifier for monitoring and rollups.
- Mirrors how CHECK_SCREEN was added when "click after visual confirmation" was needed, rather than overloading CLICK.

**Trade-offs accepted**:

- Lighting / scale variations beyond a few mm break `matchTemplate`. Acceptable because the use case is fixed-distance camera + flat phone screen; if real failures appear, ORB-based fallback can be slotted into `find_and_click.locate_button` without changing the action_type or DB schema.
- OCR-only mode is slower than template (one EasyOCR call per attempt vs one matchTemplate). Operators choose mode per-step in Builder; defaults bias toward template_only.
- The `verify_radius_px` knob (default 30) is empirical; works for typical button-with-label sizes (40-100 px tall on a 480-wide rotated frame). If buttons are much larger or smaller the operator may have to tune it. Documented in the description JSON schema.

**Files**: `app/find_and_click.py` (new, ~370 lines), `app/actions.py` (registration + new executor + transaction_logs exclusion), `app/routers/opencv_router.py` (4 endpoints: capture-template, template preview, template delete, find-and-click test), `db/schema.sql` (ENUM extension), `static/recorder.html` (8 small edits across action dropdown, render/read form blocks, saveFlow coord-sync list, testOne / testAll, selectFieldRoi handler, plus 4 new JS helpers).

**Rollback**: Revert the actions.py + find_and_click.py + opencv_router.py + recorder.html changes. The ENUM extension is forward-compatible (drop existing FIND_AND_CLICK rows or `ALTER` to remove the value); no data migration is required for other tables.

---

## DD-026: FIND_AND_SWIPE Reuses Recorded (start, end) as Offset Baseline

**What**: New `flow_steps.action_type` value `FIND_AND_SWIPE` extends FIND_AND_CLICK's vision-locate pattern to swipe gestures. Implemented in `app/find_and_swipe.py` as a thin orchestrator that imports `locate_button` and helpers from `find_and_click.py` (no fork). The recorded swipe `(start, end)` from `swipe_actions` is used not as a physical position but as a vector — `(end - start)` is the offset that gets re-applied on top of the matched runtime position.

**Why this design over alternatives**:

- **Recorded `(end - start)` offset, not two separate templates**: an alternative was to record one template for the slider start handle and another for the slider end mark, then locate both at runtime. Rejected because slider end positions usually have no distinctive visual feature (gradient, blank space, or text that drifts) — operators couldn't reliably record an end-template. Using the recorded offset assumes the slider track length is constant across UI states, which holds for every banking app we've seen (card width is fixed by screen width, not transfer type).
- **Camera anchor as separate field, not "Start = camera anchor"**: an earlier draft made `swipe_actions.start_x/y` double as the camera anchor. Rejected after operator feedback: it broke the analogy with FIND_AND_CLICK (which has its own explicit camera position field) and introduced a hidden invariant ("Start must equal Camera Position"). Now `description.camera_anchor_mm` is independent — operators can position the camera at a wider view and still record a tight slider start, mirroring how FIND_AND_CLICK handles its anchor. Backward compatibility kept via a fallback: if `camera_anchor_mm` is missing, the runtime uses `(sx_recorded, sy_recorded)` (legacy dual-purpose).
- **Reuses `swipe_actions` table, not a new column or new table**: the table's `(start_x, start_y, end_x, end_y)` schema is exactly right. Each FIND_AND_SWIPE step still gets its own row keyed by its own `swipe_key`; operators don't need to create a SWIPE first. The shared table does not imply step-level coupling — it's the same engineering convenience as FIND_AND_CLICK reusing `ui_elements` for its camera anchor (CLICK uses that table too, but the steps are independent).
- **Direct import from `find_and_click.py`, no shared utility module**: `app/find_and_swipe.py` does `from app.find_and_click import locate_button, load_template, _hw, _get_arm_id_for_station, _get_arm_limits, _clamp, DEFAULT_*`. A "cleaner" refactor would extract these into `app/visual_locator.py`, but that's a bigger surface change with no immediate benefit. If a third visual action_type appears, refactor then. This preserves a small diff and a clear "find-and-swipe is find-and-click + swipe" reading.
- **Clamp + warning on shrunk swipes, not abort**: when the matched start + recorded offset would push the end past `arms.max_x` / `max_y`, we clamp and surface a warning if the swipe shrinks below 70% of recorded length. Aborting was rejected because most "shrunk" swipes still trigger the underlying Android slide gesture (the system cares about gesture velocity + final point, not absolute distance), and we'd rather try than auto-stall. The 70% threshold is empirical; operators monitoring `transaction_logs.message` can re-tune the camera anchor if warnings cluster.

**Why a new ENUM value rather than extending SWIPE with a flag**:

- ENUM keeps the executor dispatch table clean (`SWIPE` → `execute_swipe`, `FIND_AND_SWIPE` → `execute_find_and_swipe`).
- Builder UI's per-action conditional rendering naturally extends with another `else if` branch.
- Telemetry (`transaction_logs.action_type`) gets a distinct identifier for stall analysis (count failed FIND_AND_SWIPEs separately from plain SWIPE failures).
- Mirrors FIND_AND_CLICK's choice over "extend CLICK with a flag".

**Trade-offs accepted**:

- Slider track length is assumed constant. Holds today; if a future banking app stretches its slider per transfer type, we'd need to either record two templates or expose a `swipe_distance_scale` config field. Not anticipated; not pre-built.
- Two foreign keys per step (`swipe_key` + `description.camera_anchor_mm`) is slightly heavier than FIND_AND_CLICK's one (`ui_element_key` + description). Acceptable because swipes inherently need two anchor positions (start/end), not one.
- Operator must remember "arm should be at Camera Position when click-to-record Start/End" — otherwise the calibration's pixel-to-arm conversion will miss. Same hidden invariant FIND_AND_CLICK has, just twice (once per coord). Documented in the form's tip text; if real recording errors emerge, add a pre-save sanity check.

**Files**: `app/find_and_swipe.py` (new, ~250 lines), `app/actions.py` (registration + new executor + transaction_logs exclusion at line 556), `app/routers/opencv_router.py` (1 new endpoint: find-and-swipe test; capture-template / template preview / template delete reused from FIND_AND_CLICK), `db/schema.sql` (ENUM extension), `static/recorder.html` (9 small edits: action dropdown, render branch, post-render template-load hook, setMode trigger, readForm branch, saveFlow swipe coord-sync predicate, testOne / testAll branches, plus a new `testFasFind()` JS helper).

**Rollback**: Revert actions.py + find_and_swipe.py + opencv_router.py + recorder.html changes. ENUM extension is forward-compatible (drop existing FIND_AND_SWIPE rows or `ALTER` to remove the value).

---

## DD-027: CHECK_SCREEN trigger Field — Symmetric "Expect-Present" / "Expect-Absent" Semantics

**What**: `flow_steps.description` for `CHECK_SCREEN` accepts a new `trigger` field with two values:

- `on_mismatch` (default — preserves all prior behaviour): the configured reference image MUST be on screen. If the camera frame doesn't match, run the popup-handler flow and retry up to `max_retries`. Loop exhaustion → stall.
- `on_match` (new): the configured reference image SHOULD NOT be on screen. If the camera frame matches it (e.g. a verification CAPTCHA or promotional popup IS visible), run the popup-handler flow to dismiss it and retry. Loop exhaustion (popup never goes away) → stall.

Both modes share the exact same loop, capture path, handler-flow plumbing, screenshot capture, and stall recording. The only divergence is the success criterion, expressed as one boolean expression in `app/actions.py`:

```
expected_state_reached = (
    (trigger == "on_mismatch" and is_match) or
    (trigger == "on_match" and not is_match)
)
```

**Why this design over alternatives**:

- **Single field, symmetric loop, no new code path**: an alternative was to add a separate action_type (e.g. `CHECK_SCREEN_ABSENT`) with its own executor. Rejected because it would duplicate the entire loop, the move-to-camera step, the handler invocation, the screenshot capture, the stall logging — every change to CHECK_SCREEN would have to be mirrored. The two semantics are pure inverses; the one-line predicate captures that exactly without duplicating any infrastructure.
- **Field name `trigger` over `mode` / `expect` / `invert`**: `trigger` reads naturally with the `on_<event>` value vocabulary already used elsewhere ("trigger this branch when the screen is on_match"). `mode=required/optional` was confusing because both modes can stall. `expect=present/absent` was clearer but doesn't compose with the value `on_match` (we'd write `expect=absent` then the dropdown labels would be inverted). `invert=true/false` was rejected as opaque — a builder operator new to the codebase wouldn't know what's being inverted.
- **Default to old behaviour, opt-in to new**: backward compatibility is non-negotiable since 6+ existing CHECK_SCREEN steps in production rely on the original "expect present" semantic. `config.get("trigger", "on_mismatch")` in Python + `<option value="on_mismatch">` as the first dropdown option ensures (a) DB rows without the field run identically, (b) Builder operators opening an existing step see the safe default selected, (c) on Save Flow the description gets the explicit `"trigger":"on_mismatch"` written but behaviour does not change.
- **No new ENUM, no schema change, no migration**: `trigger` lives inside the JSON in `flow_steps.description` (`LONGTEXT`), exactly like `threshold` / `max_retries` / `roi`. This matches how every other CHECK_SCREEN config evolution has been added. Avoids an `ALTER TABLE` round-trip on every deployment machine; avoids needing per-machine DB migration coordination.

**Why `max_retries` keeps its meaning unchanged in both modes**:

- `on_mismatch`: "how many chances does the popup-clearing flow get to bring the expected screen back?"
- `on_match`: "how many chances does the popup-clearing flow get to make the popup go away?"

In both, the loop ends as soon as the expected state is observed once, and stalls when all attempts are exhausted with the wrong state still present. This symmetry preserves operator intuition — they don't need to remember "in mode X, max_retries means Y, but in mode Z it means W."

**Why `_run_handler_flow` is invoked in both modes without modification**:

The handler-flow block already runs only when `expected_state_reached == False`. For `on_mismatch`, that block fires when the screen doesn't match (handler dismisses the popup that's blocking the expected screen). For `on_match`, it fires when the screen DOES match (handler dismisses the popup that should not be there). The semantic of "handler removes whatever is making the expected state false" applies identically to both modes — the same hardware actions (tap close, swipe away) have the same effect regardless of which mode we're in.

**Why the failure RuntimeError text branches on trigger**:

The original message `"screen does not match '%s' after %d attempts"` reads as a complete misdirection in `on_match` mode (where "does match" is the failure case). Diagnosing a stall by reading `transaction_logs.error_message` would mislead the operator into checking why the screen is missing when in fact the popup is stuck on screen. Two distinct messages keep operations triage straightforward. The `trigger` value is also embedded in `fail_meta` so the per-step JSON in `transaction_logs.message` shows the mode.

**What this does NOT change**:

- `screen_checker.compare_screen` algorithm — pure visual comparison, no semantic awareness, byte-for-byte unchanged.
- `_run_handler_flow` — handler invocation mechanism unchanged; same `BANK__template_id` parsing, same step iteration.
- `/api/opencv/compare` endpoint — Builder's "Test Compare" button only does the comparison and returns SSIM/inliers/etc., never executes the trigger logic.
- DB schema, seed files, seed import/export tooling — all preserve `description` as an opaque JSON string.
- `arm_worker.py`, `recorder.py`, other action types, PAS / API protocol — none touched.
- 6+ existing CHECK_SCREEN steps in production — keep working without re-save (default-value path).

**Files**: `app/actions.py` (~12 lines net add inside `execute_check_screen`), `app/screen_checker.py` (docstring only), `static/recorder.html` (3 edits inside the CHECK_SCREEN branch + step list summary badge), `CHANGELOG.md`, `BUSINESS_CONTEXT.md`, `ARCHITECTURE_PLAN.md`, `CHECK_SCREEN_OPS.md`.

**Rollback**: Revert `app/actions.py` + `app/screen_checker.py` + `static/recorder.html` changes. `description` rows that were re-saved with explicit `"trigger":"on_mismatch"` remain readable by the reverted code (the explicit field is silently ignored). Rows authored as `"trigger":"on_match"` will fall back to default behaviour after rollback (i.e. behave like `on_mismatch`); this would be visible if such steps exist — operators should re-author them as inverted CHECK_SCREEN_ABSENT-style flows or remove them.
