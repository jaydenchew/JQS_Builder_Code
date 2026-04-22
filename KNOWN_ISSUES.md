# Known Issues — Verified from Code Reviews

> Source: CODEX_CODE_REVIEW.md + CLAUDE_CODE_REVIEW.md (2026-04-14)
> Verified against live codebase. Each issue confirmed with file/line evidence.

---

## Won't Fix (Confirmed by business owner)

- **C1. Password logged in plaintext** — Even if masked in logs, passwords are accessible in the DB (Docker MySQL). System is on a dedicated machine with no external access. Masking adds complexity without real security benefit.
- **H2. Tool scripts hardcode DB password** — These are local utility scripts for data migration, not production code. DB password is also in `.env` on the same machine.
- **H3. `list_bank_apps` returns plaintext password/pin** — Intentional. Employees need to see credentials in Settings page for configuration and troubleshooting. System is internal-only (localhost).
- **H1. Dashboard innerHTML XSS** — Internal network only (DD-001). Attacker = employee with Builder access = already has full system access anyway.
- **N4. NSSM CF-Tunnel service account has no password set** — NSSM `ObjectName ".\username"` without password. Tested and verified: service starts successfully on current machine. NSSM handles passwordless user accounts for non-interactive services. If a future machine requires a password, the operator can set it via `nssm set CF-Tunnel ObjectName ".\username" "password"`.

---

## Fixed (2026-04-14)

- [x] **HR-1. `create_arm` worker failure leaves DB active**
  - Scenario: Admin adds new arm in Settings. Worker fails to start (e.g., COM port conflict). DB shows arm as `active=1, status='idle'`. PAS sends withdrawal for this arm's bank account → accepted and queued → but no worker exists to process it → task sits forever, PAS never gets callback.
  - Additionally, PAS has its own protection: when an arm stalls, PAS disables the bank group. So this is double protection.
  - Fix: on worker failure, auto-set `active=0, status='offline'` in DB.

- [x] **HR-2. Empty `PAS_API_URL` causes 50s block per task**
  - Scenario: `.env` is misconfigured with empty `PAS_API_URL`. Every completed task tries to callback, fails, retries 3 times (5s+15s+30s = 50s of blocking), then moves to next task. 1000 tasks/day = 14 hours of unnecessary waiting.
  - Fix: check URL at start of `callback_result`, return None immediately if empty. Normal retry behavior unchanged when URL is configured.

- [x] **MR-1. `reset_arm` blocks event loop**
  - Scenario: Employee clicks "Reset" on Dashboard to emergency-stop an arm. `reset_to_origin()` is a blocking hardware call (arm physically moves, takes 2-3 seconds). During those seconds, the entire FastAPI process freezes — PAS requests, Dashboard, everything stops responding.
  - Fix: execute hardware calls through worker's thread pool executor. Reset still works the same, but other requests are handled normally while arm moves.

- [x] **M6. Missing indexes on `transactions.station_id` and `bank_app_id`**
  - Scenario: Dashboard and monitor queries JOIN transactions with stations/arms. Without indexes, every query does a full table scan. At 1000-2000 transactions/day, this slows down within weeks.
  - Fix: added indexes on both columns in schema.sql + live DB.

- [x] **M1. Stall photo overwrites existing receipt screenshot**
  - Scenario: Step 15 (PHOTO) successfully captures the bank receipt and saves it to `transactions.receipt_base64`. Step 16 (close app) fails → stall triggered → system captures stall photo and overwrites `receipt_base64`. PAS receives the stall photo (current phone screen) instead of the actual bank receipt. Transaction was successful but PAS has no proof.
  - Fix: stall photo only fills `receipt_b64` if no receipt was previously captured (PHOTO step). If receipt already exists, it is preserved.

---

## Backlog (Real issues, lower priority)

- [ ] **N2. `asyncio.get_event_loop()` deprecated in Python 3.10+**
  - Files: `app/actions.py`, `app/arm_worker.py`, `app/keyboard_engine.py`, `app/routers/monitor.py` (5 occurrences)
  - Should be `asyncio.get_running_loop()`. Works fine on Python 3.11, but will warn/fail on 3.12+. Fix all 5 at once when upgrading Python.

- [ ] **N3. `worker._executor` accessed from route handler (encapsulation leak)**
  - File: `app/routers/monitor.py` L120-121
  - Route directly accesses worker's private thread pool. Should expose a public method on ArmWorker. Code hygiene issue, not a runtime risk.

- [x] **Recorder MJPEG stream blocks other cameras (CRITICAL for multi-arm)** — FIXED
  - `capture_fresh` now calls `prev._release_hw()` to release any other camera instance before opening its own (same logic as `camera_open`). Recorder stream gets interrupted momentarily but resumes on next frame. Worker can always open its camera regardless of what else is streaming.
  - Remaining edge case: after force-releasing Recorder's camera and immediately opening a different one, the first frame may be blank/dark if warmup is insufficient. This was observed once but is rare.

- [x] **capture_fresh missing try-finally — camera leak on hardware exception** (HIGH) — FIXED
  - If `read()` or warmup throws (USB disconnect, hardware error), `release()` never executes. Camera hardware locked until service restart. Same class of issue that caused multi-arm stalls.
  - Fix: wrap the open→read→release block in try-finally.

- [x] **_crop_roi no validation — empty array crash on bad config** (MEDIUM) — FIXED
  - If `top_percent > bottom_percent` in Builder config, crop returns empty array. `cv2.cvtColor` crashes. Builder misconfiguration triggers runtime crash.
  - Fix: validate y1 < y2, x1 < x2 before cropping, return None if invalid.

- [x] **OCR config JSON parse error silently swallowed** (MEDIUM) — FIXED
  - `actions.py execute_ocr_verify`: if `step["description"]` has invalid JSON, exception is caught with `pass`. No log. `field_rois` silently falls back to legacy mode. Very hard to debug.
  - Fix: add `logger.warning` in the except block.

- [x] **Error screenshot failure silently swallowed** (LOW) — FIXED
  - `actions.py execute_step`: if capture_base64 fails in error handler, exception caught with `pass`. No log.
  - Fix: add `logger.warning`.

- [x] **Service restart leaves transactions stuck as 'running'** (MEDIUM) — FIXED
  - No startup recovery: if service crashes mid-task, `status='running'` transactions stay forever. PAS never gets callback.
  - Fix: on startup, scan for `status='running'` and set to `stall` + callback PAS status=4.

- [ ] **CHECK_SCREEN handler_flow can recurse infinitely** (LOW)
  - `_run_handler_flow` uses `ACTION_MAP` which includes `CHECK_SCREEN`. If handler flow contains CHECK_SCREEN with its own handler, infinite recursion. No depth limit.
  - Actual risk: low (handlers are typically CLICK/SWIPE only). Fix: add max recursion depth (e.g., 2).

- [ ] **Handler flow shares transaction context — _ocr_result can be overwritten** (LOW)
  - Handler flow uses same `transaction` dict as main flow. If handler contains OCR_VERIFY, it overwrites `_ocr_result`. Main flow reads wrong OCR result.
  - Actual risk: low (no handler currently has OCR_VERIFY). Fix: snapshot and restore `_ocr_result` around handler execution.

- [ ] **Callback not exactly-once — no background retry for permanent failures** (MEDIUM)
  - If all 3 retries fail (5s/15s/30s), `callback_sent_at` stays NULL. No periodic scan to retry. PAS never learns the result.
  - Partial mitigation: PAS can query `/status/{process_id}`. But WA should have background sweep for `callback_sent_at IS NULL AND finished_at IS NOT NULL`.

- [ ] **coordinates.py keymaps batch — non-atomic delete+insert** (LOW)
  - Same class as M4 (saveFlow). DELETE all old keymaps then INSERT new ones with autocommit=True. If INSERT fails mid-way, old data deleted but new data incomplete. Probability: very low (Builder localhost operation).

- [ ] **withdrawal.py — queued task arm may go offline between check and insert** (LOW)
  - If admin sets arm offline between the status check and INSERT, task stays queued forever. Probability: extremely low. Mitigation: startup recovery handles `running`, but not `queued` with offline arm.

- [ ] **arm_client.py call_arm — no return value validation** (LOW) — PARTIALLY FIXED in commit 9d84be9
  - Remaining: motor_lock, move, press, lift all ignore call_arm return value. If arm service disconnects mid-task, commands silently fail and errors only surface when a later step tries to read a result.
  - Fixed sub-case: `open_port()` no longer writes a garbage handle into `self._resource` when WCF returns 0 or a negative value. Previously caused the "COM in use then 2nd click says Connected but arm doesn't move" sequence in Builder. See commit message for full walkthrough.
  - Remaining cleanup (future): make call_arm return a structured result so callers can distinguish "no response" vs "returned error code" vs "returned OK". Currently returns None on exception, string on success — ambiguous when the string itself is an error code like "0" or "-3".

- [ ] **Builder Test mode handler flow only dispatches CLICK/ARM_MOVE** (MEDIUM)
  - `testOne()` and `testAll()` in `static/recorder.html` have their OWN JS loop iterating handler-flow steps, and it hardcodes `if (hs.action_type === 'CLICK' || hs.action_type === 'ARM_MOVE')`. Any SWIPE / TYPE / OCR_VERIFY / CHECK_SCREEN step in a handler_flow is silently skipped with no log entry. User is left staring at "camera moved but nothing happened" and concluding the handler doesn't work.
  - Production is NOT affected — `actions.py::_run_handler_flow` uses the full `ACTION_MAP` dispatch, so real transactions execute every action type correctly.
  - Symptom encountered on ABA slide-confirm flow where the handler was `SWIPE` to retry the slide.
  - Fix options: (a) mirror ACTION_MAP list in the JS dispatch, (b) delegate to backend via a new `/api/recorder/test-handler-flow/{flow_id}` endpoint that calls `_run_handler_flow` directly (removes the double-implementation entirely).

- [ ] **Dashboard Pause does not release the arm's COM port** (LOW-to-MEDIUM)
  - `pause()` in `app/arm_worker.py` just sets `self._paused = True`. It does not call `close_port()` or motor_unlock. So when the user pauses an arm in Dashboard and then tries to "Connect Arm" in Builder to operate it manually, the COM port may still be held by the paused worker's `_resource` handle, causing `open_port` to get back "busy" error codes from WCF.
  - Combined with the (now-fixed) open_port pollution bug, this used to produce the "1st click COM in use, 2nd click falsely Connected" pattern.
  - Intended workaround: use Dashboard **Set Offline** instead of **Pause** to fully release the port before Builder takeover. Set Offline closes the port cleanly.
  - Possible fix: have Pause call `close_port()` before setting the flag, and Resume call `open_port()` before clearing it. Minor semantic change — Pause would transition worker to "not holding hardware" vs current "frozen but still holding". Needs DD review.

- [ ] **Changing `arms.camera_id` in Settings does not restart the worker** (MEDIUM)
  - `PUT /arms/{id}` (`app/routers/stations.py`) only calls `restart_worker` when the `active` flag changes. Editing just `camera_id` writes the new value to DB but the running `ArmWorker` still holds a `Camera(camera_id=<old>)` instance. Result: Builder shows the preview from the OLD camera even though DB and Settings UI both show the new ID. Very confusing during initial setup.
  - Operational workaround documented in INSTALL.md Step 8.4: `nssm restart WA-Unified` after changing camera_id.
  - Possible fix: detect `camera_id` delta in the PUT handler and call `manager.restart_worker(arm_id)` just like the active-flag branch does.

- [ ] **Fiducial calibration assumes card axes parallel to arm axes** (LOW, algorithmic limit documented in DD-023)
  - `_fit_fiducial_affine` computes arm coordinates for the 4 corners as `pen_arm ± (half, half)`, which only holds if the card is physically laid with printed edges parallel to the arm's X/Y axes. A 2° placement rotation introduces ~1mm error at the card corners; 5° rotation produces RMSE around 2mm and gets rejected by the `RMSE_THRESHOLD_MM = 2.0` gate.
  - Mitigation: the UI instructions (INSTALL.md Step 9) tell the operator to align the card visually, and the RMSE gate surfaces bad placements immediately.
  - Possible future enhancement: add an optional "second pen anchor" step (pen on TR corner as well as crosshair) that provides a second physical reference, letting the code solve for card orientation automatically. Would eliminate the manual-alignment dependency entirely.

- [x] **random_pin scan range excluded digit 0 and included backspace** — FIXED in commit 260f998
  - `positions[:10]` scanned index 9 (backspace `-`) and missed index 10 (digit `0`). Any PIN containing `0` when it appeared in the bottom-center slot would always fail to find the digit and stall.
  - Fix: replaced with `positions[:12]` + `_DIGIT_SKIP = {9, 11}` to exclude the two fixed non-digit keys (backspace at index 9, enter at index 11) and include all 10 digit cells including index 10.

- [ ] **random_pin close-up fallback cannot recover mis-locked cells** (LOW)
  - The close-up fallback (added in commit 260f998) skips cells already in `assigned`. If the wide-view pass OCR'd a false positive (e.g., cell 3 was misread as `5` and locked in), the real `5` will never be found on close-up because cell 3 is already taken. Close-up can only recover digits that were simply *not found*, not digits that were *found at the wrong position*.
  - Symptom: close-up loop runs and finishes but `target_digits` is still not satisfied → stall. Diagnose by checking the `pos 1` log line: if it shows 10 digits recognised but the stall still happens, a mis-lock occurred.
  - Possible fix: add a confidence threshold or multi-pass voting so a single OCR result doesn't permanently lock a cell. Out of scope for current implementation.

- [ ] **OCR failure should not stall — new status code + branch step**
  - Currently any OCR mismatch → stall (status=4), arm pauses, all queued tasks rejected.
  - Proposed: OCR failure returns new status (e.g., status=5 "OCR mismatch") to PAS. Arm does NOT pause, continues next queued task. Builder configures which step to jump to on OCR failure (e.g., skip confirm, go straight to photo).
  - Requires: PAS protocol change (new status code), arm_worker execution logic, Builder UI for branch config, API_SPEC update.

- [ ] **Name verification with word-order independence**
  - PAS sends "SAORY Yee" but bank displays "Yee SAORY". Current name matching does exact substring match which would fail on reordered names.
  - Proposed: split name into words, check each word appears in OCR text regardless of order.
  - Depends on enabling name verification in flow config (currently only account + amount are checked).

- [x] **M2. OCR receipt keyword priority can cause misjudgment** — RESOLVED
  - Field-level ROI crops only the receipt status area, so only one keyword appears in the cropped text. Priority order no longer matters. Also changed default order to failed→review→success as extra safety.

- [ ] **M4. `saveFlow()` delete-then-insert is non-transactional**
  - Scenario: Editing an 18-step flow in Builder. Frontend deletes all 18 old steps, then inserts new ones one by one. If network disconnects after inserting step 10, the flow has only 10 steps in DB. Next execution runs 10 steps then finishes — transfer may be incomplete.
  - Probability: very low (Builder runs on localhost), but theoretically possible.
  - Fix when ready: create backend `replace_flow_steps` endpoint with single transaction.

---

## Notes

- Issues from audit rounds 1-7 have already been fixed and are not listed here.
- "Won't Fix" items are business decisions confirmed by the system owner.
- Design decisions are documented in `DESIGN_DECISIONS.md`.
