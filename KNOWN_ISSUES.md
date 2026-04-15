# Known Issues — Verified from Code Reviews

> Source: CODEX_CODE_REVIEW.md + CLAUDE_CODE_REVIEW.md (2026-04-14)
> Verified against live codebase. Each issue confirmed with file/line evidence.

---

## Won't Fix (Confirmed by business owner)

- **C1. Password logged in plaintext** — Even if masked in logs, passwords are accessible in the DB (Docker MySQL). System is on a dedicated machine with no external access. Masking adds complexity without real security benefit.
- **H2. Tool scripts hardcode DB password** — These are local utility scripts for data migration, not production code. DB password is also in `.env` on the same machine.
- **H3. `list_bank_apps` returns plaintext password/pin** — Intentional. Employees need to see credentials in Settings page for configuration and troubleshooting. System is internal-only (localhost).
- **H1. Dashboard innerHTML XSS** — Internal network only (DD-001). Attacker = employee with Builder access = already has full system access anyway.

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

- [ ] **M2. OCR receipt keyword priority can cause misjudgment**
  - Scenario: Bank receipt screen simultaneously shows "Review" and "Failed" text. Keywords checked in order success→review→failed, first match wins. Could report "review" when it should be "failed".
  - Action: collect real receipt screenshots from different banks to verify. Fix if confirmed.

- [ ] **M4. `saveFlow()` delete-then-insert is non-transactional**
  - Scenario: Editing an 18-step flow in Builder. Frontend deletes all 18 old steps, then inserts new ones one by one. If network disconnects after inserting step 10, the flow has only 10 steps in DB. Next execution runs 10 steps then finishes — transfer may be incomplete.
  - Probability: very low (Builder runs on localhost), but theoretically possible.
  - Fix when ready: create backend `replace_flow_steps` endpoint with single transaction.

---

## Notes

- Issues from audit rounds 1-7 have already been fixed and are not listed here.
- "Won't Fix" items are business decisions confirmed by the system owner.
- Design decisions are documented in `DESIGN_DECISIONS.md`.
