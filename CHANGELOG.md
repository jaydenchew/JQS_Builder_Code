# Changelog

## random_pin: fix scan range, add close-up fallback + elimination (2026-04-22)

### Problem

Two bugs in `type_with_random_pin` caused OCR failures on some PIN layouts:

1. **Wrong scan range** (`positions[:10]`): index 9 (backspace `-`) was scanned but index 10 (digit `0`) was never scanned. On any layout where `0` appears in the bottom-center slot, the system could never find it and would stall.

2. **No recovery when OCR misses a digit**: The 3 wide-view offset passes would sometimes fail to recognise certain digits (e.g., `8` and `6` were consistently missed in one MBB deployment). With no fallback, the task always stalled.

### Fix

`app/keyboard_engine.py` — `type_with_random_pin` only:

- **Scan range**: replaced `positions[:10]` with `positions[:12]` and `_DIGIT_SKIP = {9, 11}`. Index 9 (backspace) and index 11 (enter/confirm) are excluded; index 10 (digit `0`) is now correctly included.

- **Close-up fallback**: after the 3 wide-view passes, any unrecognised digit cells trigger a targeted retry. The camera computes the position that centres the cell in frame (inverse calibration), flies there, uses `capture_fresh` to avoid buffer frames, and OCRs only the centre 100×100 crop. A guard skips cells where the computed cam position deviates more than 30mm from the recorded `camera_pos` (likely exceeds arm travel limits) and logs a warning instead.

- **Elimination**: if after the close-up loop exactly one digit and one unassigned cell remain, the digit is assigned without another move.

- If targets are still not satisfied after all fallback steps, `RuntimeError` is raised immediately so the arm stalls — no extra retries that would risk a PIN timeout.

### Known remaining issue (not in scope)

If the wide-view passes **mis-lock** a digit to the wrong cell (false OCR positive), the close-up fallback cannot recover it. That cell is marked `assigned` and skipped. See KNOWN_ISSUES.md.

---

## Fix random_pin category lock + test-mode routing (2026-04-22)

Two gaps introduced by the keyboard category-lock feature (which stores
`{category: ...}` in keyboard_configs for simple/multi-page keyboards):

1. **`syncKbCategory` never locked the dropdown for random_pin keyboards.**
   Random_pin configs are stored with `{type: "random_pin", ...}` not
   `{category: ...}`. The lock function only read `parsed.category`, so
   `foundCategory` was always null for random_pin → dropdown stayed
   unlocked. Fix: accept `parsed.category || parsed.type` as the source
   of truth for the category name.

2. **`testTypeStep` silently failed for random_pin keyboards.**
   The routing `if (_cfg.pages) → _typeMultiPage else → _typeSimple` had
   no branch for random_pin (which has neither `pages` nor keymaps).
   Fell through to `_typeSimple`, called the keymaps API, got "no keymap
   found" error or silent skip. Fix: add an explicit `_cfg.type ===
   "random_pin"` branch that toasts/logs a clear "skipped in test mode"
   message. Production execution path is unaffected (keyboard_engine.py
   correctly handles random_pin via the `type` field independently).

---

## Per-arm X/Y movement limits in Builder (2026-04-22)

### Problem

Each mechanical arm has physical track limits. Moving beyond them causes the arm to stall and lose the (0, 0) reference, requiring a manual power-cycle and physical re-zeroing. The system had no software guard: an operator could jog, click on the camera, or type coordinates into the Move box that exceeded the track length, silently sending the arm into the hard stop.

### Fix

Every arm now stores `max_x` and `max_y` (FLOAT, default 90/120 mm). Any Builder action that would result in a position outside `[0, max_x] x [0, max_y]` is blocked before the command is sent:

- **Frontend** (`static/recorder.html`): `_armLimitError(x, y)` checks on every jog step, Move-button submit, camera-click move/click/swipe.
- **Backend** (`app/routers/recorder.py`): `_check_limits(arm_id, x, y)` reads limits from DB and rejects `/arm/move`, `/arm/click`, `/arm/swipe`, `/arm/click-pixel`, `/arm/move-pixel`, and `/test-step` CLICK/SWIPE/ARM_MOVE. This is the safety net if another client bypasses the frontend.
- **Settings** (`static/settings.html`): Max X and Max Y fields added to the arm edit form. Fields are required; saving without valid positive values is rejected.
- **DB** (`db/schema.sql` + live `ALTER TABLE`): `arms.max_x` and `arms.max_y` added with `NOT NULL DEFAULT 90/120`.

Production flow execution (`execute_click`, `execute_swipe`, etc. in `actions.py`) is deliberately NOT restricted: if coordinates were within limits when recorded in Builder, they are within limits at runtime.

### Configuration

Open Settings → Arms, set Max X and Max Y per arm. Changes take effect immediately (Builder reads them on arm select). The arm does not need to be restarted.

---

## Per-bank flow seeds + import script (2026-04-22)

### What

New `db/` files let a new machine import the flow structure (step names, action types, delays, OCR ROIs, CHECK_SCREEN config) for any supported bank without restoring the full DB.

**Files added:**

| File | Purpose |
|---|---|
| `db/export_bank_seed.py` | Generates a seed from the live DB for a given bank+arm |
| `db/import_bank_seed.py` | Imports a seed onto any arm by substituting the arm name at run time |
| `db/seed_bank_ABA.sql` | ABA Same Bank (1 main + 1 handler, 20 steps) |
| `db/seed_bank_ACLEDA.sql` | ACLEDA Same + Interbank (2 main + 1 handler, 44 steps) |
| `db/seed_bank_WINGBANK.sql` | WINGBANK Same Bank (1 main, 19 steps) |
| `db/seed_bank_MBB.sql` | MBB Same + Interbank (2 main, 60 steps) |
| `db/seed_bank_CIMB.sql` | CIMB Same + Interbank (2 main, 76 steps) |

### How to use

```powershell
# Import on a new machine (after adding the arm in Settings -> Arms):
py db\import_bank_seed.py db\seed_bank_ABA.sql ARM-05

# Regenerate after editing flows and commit to share with the team:
py db\export_bank_seed.py ABA ARM-01
```

### What the seeds include / exclude

Included | Excluded
---|---
flow_templates (name, transfer_type, amount_format) | ui_elements (X/Y coordinates)
flow_steps (all step fields: action_type, delays, description / OCR ROI JSON, CHECK_SCREEN config JSON) | keymaps, swipe_actions
Handler flow templates referenced by CHECK_SCREEN steps | keyboard_configs
&nbsp; | references/ (per-machine camera captures)
&nbsp; | calibrations (per-machine)

### Technical notes

- Seeds are arm-agnostic: `{ARM_NAME}` placeholder is replaced at import time, so the same `.sql` file works for ARM-01, ARM-05, etc.
- Handler flow template IDs are resolved via `CONCAT(..., @handler_N_id, ...)` so the `handler_flow` field in CHECK_SCREEN description JSON always points at the newly-assigned ID on the target machine, not the source machine's ID.
- Seeds are idempotent: existing flows for that bank+arm are deleted before re-insert.
- Import guard: if the arm does not exist in the DB the import fails loudly (referencing a nonexistent table triggers a MySQL error).

---

## Calibration: Fiducial card replaces 3-point auto-calibrate (2026-04-21)

### Problem

The old 3-point method (`/api/calibration/auto-calibrate`) was unreliable on new hardware:

- **Collinear failures** &mdash; `step_mm=10` produced pixel displacements around 48px on this camera, so template matches with `TM_CCOEFF_NORMED >= 0.5` (the old threshold) occasionally returned 3 near-collinear hits on similar features in the scene. Users hit `det=0.00e+00` errors often enough that they resorted to bumping `step_mm` to 12 as a workaround, which is only luck-based.
- **Small measurement baseline** &mdash; 10mm arm moves were measured via single-pixel template matches. A 2px match error gave a 20% scale error. No redundancy.
- **No quality metric** &mdash; the endpoint accepted the output and saved it regardless of the actual fit quality. A completely wrong calibration looked identical to a good one in the DB.
- **No compensation for bad motion** &mdash; every run required 3 actual mechanical moves of the arm. If a move silently failed (e.g., `call_arm` returned `None` and was swallowed), all 3 photos were of the same scene and the matrix came out as noise.
- **Brittle in face of camera-to-arm rotation** &mdash; the fitted matrix could technically encode rotation, but with only 3 anchor points and small displacements the rotation term was heavily noise-influenced (we saw one machine reporting `-45.6°` rotation that appeared to be fit noise, not real mounting).

### Fix

Completely replaced the algorithm with a **fiducial card** based flow. The hardware vendor ships a 50&times;50mm printed calibration card with a center crosshair; we reuse it:

1. **Capture one photo** with the card under the camera (`/api/calibration/capture-for-calibration`)
2. **User clicks the 4 corners** of the inner black square on the photo, in order TL &rarr; TR &rarr; BR &rarr; BL
3. **User jogs the pen tip** onto the card crosshair and clicks "Set Pen Reference"
4. **Backend fits a full 2x3 affine** via `np.linalg.lstsq` from 5 (pixel, arm) pairs (4 corners + crosshair), reports **RMSE** alongside `scale_x`, `scale_y`, `rotation_degrees`, `scale_anisotropy`, and per-anchor errors
5. **Rejects saves with RMSE &gt; 2mm** &mdash; surfacing bad runs instead of silently storing garbage

### Algorithm improvements

- **Large baseline** &mdash; card corners span 50mm (vs 10mm in the old method). Pixel match error has 5&times; less leverage on scale.
- **Overdetermined fit** &mdash; 5 anchors &times; 2 equations = 10 equations for 6 unknowns &rarr; least-squares fit + meaningful RMSE.
- **Full 2x3 affine** &mdash; the fitted matrix carries off-diagonal terms, so any camera-mount rotation relative to the arm is absorbed automatically. Nothing is hardcoded to a diagonal scale matrix.
- **Zero mechanical motion during fit** &mdash; one photo, no A/B/C moves. Motion errors can't pollute the fit.
- **Quality gate** &mdash; `RMSE_THRESHOLD_MM = 2.0`. Typical good fit is 0.3-0.5mm.

### Changes

- `app/routers/calibration_router.py` &mdash; removed `/auto-calibrate`, `/auto-calibrate/manual-points`, `_find_template`, `_compute_calibration`; removed unused imports (`ArmClient`, `Camera`, `time`). Added `/capture-for-calibration`, `/fiducial-save`, `_fit_fiducial_affine`. Net change: -150 / +180 lines.
- `static/recorder.html` &mdash; replaced the old 3-step "Capture Template &rarr; Start Auto Calibration" modal with a 4-step "Capture Photo &rarr; Click Corners &rarr; Align Pen &rarr; Result" modal. All calibration JS rewritten with `cal*` prefix preserved. Reuses global `jog()`, `S.curX/Y`, `getArmId()`, `toast()`.
- **Zero DB schema change** &mdash; `calibrations` table unchanged; `save_calibration(station_id, data)` dict keys unchanged; downstream consumers (`pixel_to_arm`, `keyboard_engine.py`, `recorder.py pixel_to_arm callers`, `settings.html`) all zero-diff.

### Remaining assumption (documented for operators)

The user must place the calibration card with its printed edges **roughly parallel to the arm's X/Y axes** (hand alignment, &plusmn;2&deg; acceptable &rarr; &lt;1mm error over 25mm half-diagonal). Deliberate mis-rotation of the card is caught by RMSE gate. See DD-023 for rationale.

### Operator workflow

1. Builder &rarr; click "Calibrate" on the station indicator
2. Enter card inner-square size (default 50mm, check card printing)
3. Click "Capture Photo"
4. Click the 4 corners in order on the displayed image
5. Jog the pen onto the crosshair (use arrow keys or jog buttons)
6. Click "Set Pen Reference &amp; Save"
7. Result panel shows RMSE, scale\_x/y, anisotropy, rotation, and per-anchor errors. If RMSE &lt; 1mm: save accepted. If 1-2mm: investigate anchor errors. If &gt; 2mm: rejected, redo.

### No rollback path needed for old calibrations

Existing rows in the `calibrations` table (produced by the old 3-point method) remain readable and usable by `pixel_to_arm`. Only the *production of new calibrations* is changed. If a deployed machine prefers to keep its old calibration, no action required. If it shows accuracy issues, re-run the new fiducial flow.

---

## CHECK_SCREEN: ORB Align + Masked SSIM replaces SSIM+edge (2026-04-18)

### Problem
Production `CHECK_SCREEN` used full-image SSIM (0.6) + Canny edge IoU (0.4). On real phone-rack photos SSIM drops to ~0.5 because of physical-world factors the algorithm can't compensate for:
- Phone moves a few pixels between pick-up/put-down (even in fixed cradle)
- Moire patterns from camera-to-LCD, varying with micro-angle shifts
- Ambient light fluctuations between morning/afternoon
- Edge IoU amplifies pixel-level jitter instead of smoothing it

Field symptom: runs stalled at `screen mismatch after 3 attempts (best score=0.52)` even when the page was visually correct. User turned off ROI because "putting the phone back even slightly offset kills it". ROI narrower than full image made it worse, not better.

### Fix
Replaced the algorithm with **ORB feature match → RANSAC Similarity transform → warp → masked SSIM** (three-tier gate):

1. **ORB (2000 features) on full image** — phone bezel and fixed UI chrome are the best alignment anchors, never crop before feature extraction
2. **BFMatcher + Lowe ratio 0.75 → `cv2.estimateAffinePartial2D`** — Similarity (4 DoF: tx/ty/rot/uniform scale), not Homography, because the physical setup is a fixed cradle + fixed camera, perspective distortion is impossible
3. **`cv2.warpAffine` current → reference coords** with a parallel mask warp for the valid-pixel region
4. **ROI applied AFTER alignment**, only to scope the SSIM comparison region
5. **Gate**: `inliers >= 25 AND aligned_ssim >= threshold AND valid_ratio >= 0.60`

### Return value upgrade: tuple → dict
`screen_checker.compare_screen()` now returns a rich dict:
```python
{"pass": bool, "ssim": float, "inliers": int, "rot_deg": float,
 "scale": float, "valid_ratio": float, "ms": float, "reason": str}
```
`reason` ∈ `{"match", "popup_detected", "wrong_screen", "alignment_failed"}` — diagnostic only for now (not driving new control flow), but unblocks future smarter stall classification.

HTTP response at `/api/opencv/compare` keeps `match` / `score` / `threshold` aliases so `recorder.html` JS consumers (`r.match`, `r.score`, `r.threshold`) stay zero-touch.

### POC validation (21 real phone-rack photos in `ORB+OCR/`)
- Old SSIM+edge: 0/21 pass rate (SSIM ~0.52 on correct page)
- New Align+Diff: 18/18 correct-page pass, 3/3 wrong-page reject — including 1° and 3° rotation perturbations simulating pick-up/put-down
- Median runtime: ~31 ms per compare (faster than old edge+SSIM due to aggressive ORB keypoint cap)
- Wrong-page detection is now dual-gate: `test06` (different page, 22 inliers) rejects on inliers gate; popup cases reject on SSIM gate with `reason=popup_detected`

### Operator action required after deploy
The `threshold` semantic changed from "0.6×SSIM + 0.4×edge composite" to "aligned SSIM". Old `threshold=0.70` values will still work but are overly loose (negatives can slip through at 0.60). **Recommended: re-save any existing CHECK_SCREEN steps in Builder or manually change stored thresholds to 0.80** (the new default).

### Files
- `app/screen_checker.py` — full rewrite of `compare_screen`, added `_align_similarity`, 6 module constants (`ORB_NFEATURES=2000`, `MIN_INLIERS=25`, `DEFAULT_SSIM_THRESHOLD=0.80`, `MIN_VALID_RATIO=0.60`, `RATIO_TEST=0.75`, `SCALE_TOLERANCE=(0.85, 1.15)`), removed dead `_edge_similarity` and `capture_rotated_from`
- `app/actions.py` — `execute_check_screen` default threshold 0.85→`screen_checker.DEFAULT_SSIM_THRESHOLD`, dict unpack, enriched log (`ssim=X.XXXX inliers=N rot=X.XXdeg reason=...`), `transaction_logs.message` now stores JSON with 9 fields (same pattern as OCR observability, since table has no `details` column)
- `app/routers/opencv_router.py` — `/compare` now delegates to `screen_checker.compare_screen`; removed 4 local dupes (`_compare_grayscale` / `_ssim` / `_edge_similarity` / `_crop_roi`); default threshold aligned to module constant. Fixes a pre-existing inconsistency where Builder "Test Compare" used 0.8/0.2 SSIM/edge weights while runtime used 0.6/0.4
- `static/recorder.html` — 5 threshold defaults 0.70→0.80 (lines 1501/1667/2108/2198/2762). No field ID / JSON schema changes
- `DESIGN_DECISIONS.md` — added DD-022
- `ARCHITECTURE_PLAN.md` — tech-stack line updated

### No schema change, no env var, no UI field change — single `git revert` rolls back.

---

## Camera Verify/Swap Hardening — Post-review Fixes (2026-04-17)

Follow-up to commit `6f69568` addressing three concerns raised in code review:

### Fix 1: Preview now honors the global camera exclusive lock
- **Problem**: `_capture_one_frame_blocking` (used when the target arm has no live worker) called `cv2.VideoCapture(camera_id, CAP_DSHOW)` directly, bypassing the `Camera._init_lock` + `_active_instance` serialization model. If another worker on a different camera was mid-capture, DSHOW could race on USB hub arbitration and either fail the preview or disturb the other worker.
- **Fix**: `_capture_one_frame_blocking` now instantiates a `Camera` object and calls `capture_fresh()`, which participates in the global lock like any other worker camera op. No new hardware contention paths are introduced.
- **Files**: `app/routers/monitor.py`.

### Fix 2: Swap DB update is now atomic
- **Problem**: `swap_camera` issued two separate `UPDATE arms SET camera_id=...` statements. If the second one failed (DB error, connection drop between statements), both arms would end up bound to the same `camera_id` — a state the system cannot self-heal from.
- **Fix**: Replaced with a single `UPDATE arms SET camera_id = CASE id WHEN %s THEN %s WHEN %s THEN %s END WHERE id IN (%s, %s)` statement. MySQL guarantees single-statement atomicity, so either both arms swap or neither does.
- **Files**: `app/routers/monitor.py`.

### Fix 3: Swap follow-up waits for worker readiness instead of fixed 1.5s
- **Problem**: After swap, the frontend used `setTimeout(renderCamPanel, 1500)` to refresh the preview. But `restart_worker` has to cancel the old task (up to ~0.8s if mid-`capture_fresh`), tear down the old worker, create the new one, and wait for `run()` to set `_running=True`. Under worst case, 1.5s is not enough and the refresh either hits `no_worker` error or races an `offline` worker.
- **Fix**: Replaced fixed timeout with `_waitForWorkerReady([armId, targetId], 8000)` — polls the WebSocket-pushed `worker_status` of both arms at 500ms intervals and proceeds only when both are past `offline`/`no_worker`. Caps at 8s to avoid hanging the UI if something goes wrong.
- **Files**: `static/index.html`.

---

## Dashboard Camera Verify/Swap, Nav Service Indicator, Auto-refreshing Stats (2026-04-17)

### Dashboard: Camera Verify & One-click Swap
- **Problem**: Windows DSHOW renumbers USB camera indices on every boot, so after PC restart `arms.camera_id=0` may point at a physically different camera than yesterday. Operators had no in-app way to detect or fix this — required SQL `UPDATE arms SET camera_id=...` and service restart. Real incident: ARM-01's stream showed ARM-02's view, only diagnosed after 30+ minutes.
- **Fix**: Each Dashboard arm-card now has a `↻ Verify` button. Clicking expands an inline preview that captures one fresh frame from that arm's currently bound camera, plus a swap dropdown listing other non-busy arms. One click swaps `camera_id` between two arms in DB and live-restarts both workers — no service restart needed.
- **Auto-prompt on session start**: First time entering Dashboard per browser session, all non-busy arms auto-expand their preview as a "remember to check the cameras" reminder. Subsequent visits in the same session require manual click (no spam).
- **Preview cache**: Preview is captured once per click and cached in JS. The 2-second WebSocket arm-card re-render repaints from cache, so a kept-open panel does not hammer `/camera-preview` every 2 seconds (this was a bug during development that opened+closed the camera nonstop).
- **Files**: `app/worker_manager.py` (+`restart_worker`), `app/routers/monitor.py` (+`/arms/{id}/camera-preview`, +`/arms/swap-camera`), `static/index.html` (UI + cache logic).
- **Safety policy**: Verify and swap only require worker to be **non-busy** (idle/paused/offline). `busy` workers are blocked at both backend and frontend (button disabled with tooltip). Idle workers are safe because `capture_fresh` shares the per-arm camera lock; restart on idle is equivalent to a quick stop+start and queued tasks are preserved.
- **No schema change**: Reuses existing `arms.camera_id` column.

### Nav: Global Service Status Indicator
- **Problem**: The Services panel (MySQL/Arm WCF/Tunnel/WA Service) lived in the Dashboard body and took 80px of vertical space. It was also invisible from Builder/Settings/Transactions pages — operators had to bounce back to Dashboard to check.
- **Fix**: Service status moved to the right side of the global nav bar as a compact pill: green dot + "Services" when all up, red dot + "Services (N down)" when any are down. Click expands a popover with per-service status and detail (uptime, HTTP code, error). Tooltip shows full breakdown on hover. Visible on every page.
- **Files**: `static/js/api.js` (+`loadNavServices`), `static/css/style.css` (nav-svc styles), `static/index.html` (removed the body Services panel).
- **Polling**: 30s interval, same as before. Silently degrades to "Services unavailable" if `/api/monitor/services` errors.

### Dashboard: Auto-refreshing Stats Cards
- **Problem**: The 5 stat cards (Today Total / Success / Failed / Stall / In Queue) only loaded once on page open. Operators had to refresh the whole page to see updated counts after transactions completed.
- **Fix**: `loadStats()` extracted into its own function and polled every 5 seconds. WebSocket arm-card pushes are unchanged.
- **Files**: `static/index.html`.

---

## Event-driven Worker Wakeup, Stall Reason Classification, OCR Observability (2026-04-16)

### Optimization #2: Event-driven Worker Wakeup
- **Problem**: `ArmWorker.run()` used `await asyncio.sleep(2)` when queue was empty, so newly submitted tasks waited up to 2 seconds before the worker noticed them.
- **Fix**: `WorkerManager` now creates a dedicated `asyncio.Event` per worker and passes it into `ArmWorker.__init__(task_event=evt)`. When `/process-withdrawal` successfully inserts a `queued` task, it calls `manager.notify_worker(arm_id)` which sets the event, immediately waking the worker. A 30-second `wait_for` timeout remains as a safety net.
- **Files**: `app/worker_manager.py`, `app/arm_worker.py`, `app/routers/withdrawal.py`.
- **Scope**: `notify_worker` is only called for the final queued INSERT; the two failure-path INSERTs (bank_app not found, arm offline) skip it since they don't produce queueable tasks. Event binding happens in `_create_worker()` so both `start_all()` and `add_worker()` (dynamic arm creation) get it.
- **Effect**: New-task latency drops from 0–2s to near zero.

### Optimization #3: Stall Reason Classification
- **Problem**: When an arm stalled, `arms.status = 'offline'` was all we knew. Operators had to grep `service_stderr.log` to figure out why.
- **Fix**: `arms` table gains two new columns: `stall_reason VARCHAR(50)` and `stall_details TEXT`. `ArmWorker._classify_stall_reason()` categorizes the error message into one of: `arm_hw_error`, `flow_not_found`, `ocr_mismatch`, `screen_mismatch`, `camera_fail`, `step_failed`, `unknown`. The Dashboard WebSocket (`/api/monitor/ws`) exposes both fields.
- **Files**: `db/schema.sql`, `app/arm_worker.py`, `app/routers/monitor.py`.
- **Clear timing**: Stored on stall; cleared on worker startup, on successful task completion, and on `resume_arm`.
- **Migration required** (existing installs): `ALTER TABLE arms ADD COLUMN stall_reason VARCHAR(50) NULL AFTER status, ADD COLUMN stall_details TEXT NULL AFTER stall_reason;`
- **Backward compatibility**: Columns are NULL-able with no default, so existing INSERTs and `SELECT *` callers keep working.

### Optimization #5: OCR Observability
- **Problem**: `_ocr_field` returned a plain string. We had no idea which of the 12 Tesseract preprocessing variants actually matched, how many attempts were needed, or how long each field took. Impossible to optimize.
- **Fix**: `_ocr_field` now returns `{"text": str, "method": str, "engine": str, "attempts": int, "latency_ms": int}`. `verify_configurable` collects per-field meta into `ocr_meta = {"fields": {...}, "total_latency_ms": int}` and returns it as a 5th tuple element. `execute_ocr_verify` JSON-encodes the meta into `transaction_logs.message`, viewable via `/api/monitor/transactions/{id}/logs`.
- **Files**: `app/ocr.py`, `app/actions.py`.
- **Method naming**: Tesseract methods are named `<preproc>_psm<n>` (e.g. `inverted_psm6`, `otsu_inv_psm7`). EasyOCR fallbacks are named `easyocr_4x_direct` / `easyocr_4x_inverted`.
- **Callers updated**: Both `verify_configurable` call sites in `actions.py` (ocr_config path and legacy `verify_transfer_from_frame` path) unpack the new 5-tuple.

---

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

### Camera Scan
- **Scan Cameras button in Settings**: Detects all connected USB cameras (index 0-9), shows preview image for each. Cameras occupied by active arms shown as "Occupied (ARM-XX)". Helps operators identify which camera index corresponds to which phone.
- **capture_fresh releases other camera**: Before opening its own camera, `capture_fresh` now releases any other Camera instance holding hardware (matching `camera_open` logic). Fixes "Camera reopen failed" when Recorder stream or another arm was occupying a different camera.

### Camera Warmup After Contention
- **0.5s delay after releasing other camera**: When `capture_fresh` force-releases another arm's camera, waits 0.5s for DSHOW hardware to fully release before opening own camera. Fixes stale frame issue when two arms photograph simultaneously.
- **Increased warmup**: Sleep 0.15s→0.3s, warmup frames 2→3 minimum. Prevents capturing residual sensor frames after camera switch.

### OCR Smart Match — Tesseract retry + EasyOCR fallback
- **Expected-aware Tesseract**: `_ocr_field` now accepts `expected` parameter. When Tesseract reads a result that doesn't match expected, it continues trying remaining preprocessing methods instead of returning immediately. Previously, first result with any digit was returned even if wrong (e.g., `012801402` instead of `012501402` — `5` misread as `8`).
- **EasyOCR fallback on mismatch**: After all 12 Tesseract methods fail to match, falls back to EasyOCR (4x upscale + inverted). EasyOCR result also checked against expected before accepting.
- **`_quick_match` helper**: Reuses existing account (leading-zero + suffix) and amount (float normalization) matching logic for inline validation during OCR.

### Robustness Fixes
- **capture_fresh try-finally**: Camera is now always released even if `read()` or warmup throws an exception (USB disconnect, hardware error). Prevents camera hardware lockup.
- **Startup recovery**: On service start, scans for `status='running'` transactions (orphaned by crash) and marks them as stall + callbacks PAS status=4.
- **OCR config parse warning**: JSON parse errors in step description now logged instead of silently swallowed.
- **Error screenshot warning**: Failure to capture error screenshot now logged.
- **ROI boundary validation**: `_crop_roi` checks `top < bottom` and `left < right`, returns None + warning on invalid config instead of crashing.

### Field-level OCR ROI + Tesseract Tuning
- **Per-field ROI**: Each verify field (account, amount, name) and receipt_status can have its own ROI region. Cropped area is sent to targeted OCR engine for higher accuracy.
- **Tesseract for digits**: Account and amount fields use Tesseract with digit whitelist (`0123456789.`) + PSM 7 (single line) + multi-preprocessing (CLAHE, adaptive threshold, OTSU). Falls back to EasyOCR if Tesseract fails.
- **EasyOCR for text**: Name and receipt status fields use EasyOCR with 3x upscale.
- **Visual ROI selector per field**: Each checkbox field in Builder has its own "Select ROI" button. Snapshot is cached — first click captures photo, subsequent clicks reuse it for instant framing.
- **Tesseract PSM 6+7 dual mode**: PSM 7 (single line) fails when ROI crop contains partial text from adjacent lines. Now tries PSM 6 (text block) first, then PSM 7. Both with digit whitelist.
- **Amount whitelist includes `$`**: Prevents `$` symbol being misread as `5` by Tesseract (e.g., `37.86$` was read as `37.865`).
- **EasyOCR fallback with 4x upscale + inverted**: If Tesseract fails on all preprocessing methods, falls back to EasyOCR at 4x scale, also tries inverted image.
- **Field ROI debug logging**: Logs crop dimensions for each field (`Field ROI [amount]: {...} → crop 202x51`) for easier debugging.
- **Backward compatible**: Flows without `field_rois` use existing single ROI or fullscreen path. No migration needed.
- **Tested**: ABA ARM-01 17/17 (100%), ACLEDA 8/9 (89%), WINGBANK 8/9 (89%) on historical screenshots (excluding known camera buffer issues).

### OCR Image Enhancement
- **CLAHE + 2x upscale before OCR**: When ROI is configured, the cropped region is converted to grayscale, enhanced with CLAHE (Contrast Limited Adaptive Histogram Equalization), then upscaled 2x with bicubic interpolation. Sharper text edges and higher contrast improve EasyOCR accuracy, especially for small digits like `9.19` that were previously misread as `9.9`.

### OCR ROI Visual Selector
- **OCR Region of Interest**: OCR_VERIFY steps now support ROI cropping — only the selected area of the phone screen is sent to OCR, reducing noise and improving accuracy.
- **Visual ROI selector in Builder**: "Select on Photo" button captures a snapshot, displays it in a modal with crosshair cursor. User draws a rectangle to define the OCR region. Percentages auto-calculated and filled into the form.
- **Backend**: `ocr.py verify_configurable` crops the rotated frame by ROI percentages before running OCR. Full screenshot is still saved for debugging.
- **Snapshot endpoint**: New `POST /api/opencv/snapshot` returns base64 JPEG without saving to disk.

### Camera Concurrency + OCR Matching
- **Camera release after capture**: `capture_fresh()` now closes the camera immediately after reading a frame, reducing the exclusive lock window from "entire task duration" to ~400ms. Multi-arm concurrent photo requests no longer block for minutes.
- **Account number leading-zero match**: OCR verification now also tries matching the account number with leading zeros stripped (e.g., `012501402` also matches as `12501402`). Fixes false failures when bank apps display accounts without leading zeros or with space formatting.

### Code Review Fixes (Claude Round 2)
- **Transactions "All" fix**: Selecting "All" now sends `limit=0`, backend treats 0 as "no limit" (capped at 5000). Previously "All" silently returned only 50 rows.
- **install_tunnel.ps1 path fallback**: cloudflared path now auto-detected via `Get-Command`, falls back to Program Files (x86) then Program Files.

### Deployment
- **FastAPI binds to 127.0.0.1**: External access only through Cloudflare Tunnel. Localhost-only prevents LAN exposure of unauthenticated management endpoints.
- **Cloudflare Tunnel via NSSM**: `cloudflared service install` has LocalSystem config path issues. Tunnel now runs as NSSM service (`CF-Tunnel`) under user account, reading config from `~/.cloudflared/config.yml`. See DD-015.

### Code Review Fixes (CODEX + Claude)
- **create_arm rollback**: Worker start failure now auto-sets arm to `active=0, status='offline'`, preventing "accepted but never processed" tasks.
- **PAS_API_URL empty short-circuit**: `callback_result` returns None immediately if URL is empty, avoiding 50s retry block per task when `.env` is misconfigured.
- **reset_arm non-blocking**: Hardware calls now run through worker's thread pool executor instead of blocking the event loop.
- **Transaction indexes**: Added `idx_station_id` and `idx_bank_app_id` on `transactions` table for JOIN performance at scale.
- **Stall photo preserves receipt**: Stall screenshot only used when no PHOTO step receipt exists. Previously, stall photo would overwrite the actual bank receipt.

### Dashboard
- **Service status monitor**: Dashboard shows MySQL, Arm WCF, Cloudflare Tunnel, and WA uptime status. Auto-refreshes every 30 seconds.
- **Removed redundant nav buttons** from dashboard bottom.

### PAS Callback Retry
- **Automatic retry with backoff**: `callback_result` now retries up to 3 times on failure (5s, 15s, 30s intervals). Handles network blips and temporary PAS outages without losing callbacks. After all retries exhausted, returns None (caller leaves `callback_sent_at` as NULL for manual reconciliation).

### Audit Fixes (Round 5)
- **Resume restores arms.status**: `resume_arm` now writes `status='idle'` alongside `active=1`. Fixes regression where stall set `status='offline'` but resume only set `active=1`, causing new withdrawal requests to be rejected with "arm offline".
- **_fail_queued_tasks callback check**: Queued task batch rejection now checks `callback_result` return value before writing `callback_sent_at`, consistent with main flow paths.

### Audit Fixes (Round 4)
- **PAS callback HTTP status check**: `callback_result` now returns None (treated as failure) when PAS responds with non-2xx status code. Previously, 4xx/5xx responses with valid JSON body were treated as success, causing `callback_sent_at` to be written even though PAS rejected the request.
- **reorder_steps transaction**: UPDATE loop now wrapped in explicit DB transaction. If any UPDATE fails mid-loop, all changes roll back instead of leaving partial reorder state.
- **Audit report cleanup**: Consolidated 4 audit reports into single `AUDIT_REPORT_4.md`.

### Audit Fixes (Round 3)
- **PAS callback_sent_at consistency**: `callback_sent_at` now only written when `callback_result` returns a valid response. If PAS callback fails (network error, 500, etc.), `callback_sent_at` stays NULL so the transaction can be identified as "not yet delivered" for retry/reconciliation.
- **Resume status fix**: `resume_arm` no longer force-writes `arms.status='idle'`. Only sets `active=1`; worker manages its own status transitions to avoid momentary idle/busy flicker.

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
