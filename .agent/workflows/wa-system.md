---
name: wa-system
description: How to work with the WA Unified System. Read this first before making any changes.
---

# WA Unified System — Agent Skill

## Before You Start

This is a physical RPA system — mechanical arms tapping on real phones to do bank transfers. Code changes can cause real financial impact. Read the documentation before modifying anything.

## Required Reading (in order)

1. **`BUSINESS_CONTEXT.md`** — What the system does, why it exists, PAS protocol, transfer types, physical deployment, operations guide. **Read this first.**

2. **`DESIGN_DECISIONS.md`** — 14 Architecture Decision Records explaining choices that may look like bugs but are intentional. **Read before flagging anything as a bug.**

3. **`ARCHITECTURE_PLAN.md`** — Technical architecture: execution flow, camera design, UI element coordinates, stall handling, non-blocking model, PAS callbacks.

4. **`API_SPEC.md`** — Complete API specification for PAS integration: request/response formats, status codes, callback protocol, retry behavior, supported banks.

5. **`README.md`** — Installation, deployment, Cloudflare Tunnel setup, service management.

6. **`CHANGELOG.md`** — Full change history with dates.

## Key Constraints

- **Single worker per arm** — no task locking needed, WorkerManager guarantees this
- **No automatic retry** — failed transfers are never retried (might cause double payment)
- **Camera reopens for each capture** — DSHOW buffer issue, see DD-008
- **SAME/INTER flows use `_inter` suffix** — prevents coordinate conflicts, see DD-009
- **Auth only on PAS endpoints** — other endpoints protected by network boundary (localhost + Tunnel)
- **`ui_element_key = step_name`** — all action types use step_name, not shared keys

## When Modifying Code

1. Check `DESIGN_DECISIONS.md` to see if the behavior you're changing is intentional
2. Check `CHANGELOG.md` to understand why things are the way they are
3. Never run migration scripts on the live database without understanding the full impact
4. Test with Builder before running real transactions
5. Update documentation (`CHANGELOG.md` at minimum) after changes

## File Map

| Area | Key Files |
|------|-----------|
| Core execution | `app/arm_worker.py`, `app/actions.py` |
| Worker lifecycle | `app/worker_manager.py` |
| PAS integration | `app/routers/withdrawal.py`, `app/pas_client.py` |
| Camera | `app/camera.py` (capture_fresh = reopen camera) |
| Keyboard typing | `app/keyboard_engine.py`, `app/actions.py` (CHAR_ALIASES) |
| OCR | `app/ocr.py`, `app/screen_checker.py` |
| Builder UI | `static/recorder.html` |
| Dashboard | `static/index.html` |
| Database | `db/schema.sql` (14 tables) |
