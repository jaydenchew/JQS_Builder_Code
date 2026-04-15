# Stress Test Report — 2026-04-15

> Test scope: Process ID 86-141 (56 transactions)
> Arms: ARM-01 (station 2), ARM-02 (station 3)
> Banks: ABA, ACLEDA, WINGBANK (all same-bank transfers)
> Concurrent: 2 arms running simultaneously

## Summary

| Metric | Value |
|--------|-------|
| Total transactions | 56 |
| Success | 28 (50.0%) |
| Stall (arm paused) | 6 (10.7%) |
| Failed (queued tasks auto-rejected) | 22 (39.3%) |
| Callbacks sent | 56/56 (100%) |

**Note**: The 22 "failed" transactions were NOT execution failures — they were queued tasks that got auto-rejected when their assigned arm stalled on a previous task. Only 6 transactions actually stalled during execution.

**Adjusted success rate (excluding auto-rejected)**: 28 success out of 34 actually executed = **82.4%**

## Performance

| Metric | Value |
|--------|-------|
| Average execution time (success) | 97.6s |
| Fastest | 88.0s (WINGBANK on ARM-02) |
| Slowest | 107.0s (ACLEDA on ARM-02) |

## Success Rate by ARM + Bank

| ARM / Bank | Total | Success | Stall | Auto-rejected | Success Rate |
|------------|-------|---------|-------|---------------|-------------|
| ARM-01 / ABA | 10 | 5 | 2 | 3 | 50% |
| ARM-01 / ACLEDA | 6 | 1 | 1 | 4 | 17% |
| ARM-01 / WINGBANK | 7 | 4 | 0 | 3 | 57% |
| ARM-02 / ABA | 8 | 6 | 0 | 2 | 75% |
| ARM-02 / ACLEDA | 11 | 5 | 2 | 4 | 45% |
| ARM-02 / WINGBANK | 14 | 7 | 1 | 6 | 50% |

## Stall Analysis (6 incidents)

| PID | ARM | Bank | Error | Root Cause |
|-----|-----|------|-------|------------|
| 90 | ARM-01 | ABA | OCR verification failed | OCR misread `9.19` as `9.9` — EasyOCR digit recognition error on small text |
| 92 | ARM-02 | WINGBANK | OCR verification failed | OCR misread amount — same OCR accuracy issue |
| 114 | ARM-02 | ACLEDA | Step execution failed | CHECK_SCREEN handler flow error |
| 125 | ARM-01 | ABA | OCR verification failed | OCR misread amount — same as p90 |
| 134 | ARM-01 | ACLEDA | Step execution failed | CHECK_SCREEN failed (score 0.66→0.34→0.34). Camera conflict with Recorder stream + ARM-02 concurrent capture caused incorrect frames |
| 140 | ARM-02 | ACLEDA | OCR verification failed | Camera 1 reopen failed. Recorder stream held Camera 0, DSHOW blocked Camera 1 from opening |

## Root Causes

### 1. OCR Accuracy (3 stalls — p90, p92, p125)
- EasyOCR misreads small digits (e.g., `9.19` → `9.9`)
- Image enhancement (CLAHE + 2x upscale) added mid-test, improved later runs
- ROI cropping configured for all arms, reduces OCR noise
- **Mitigation applied**: Account leading-zero match, image enhancement, ROI crop

### 2. Camera Concurrency / Recorder Conflict (2 stalls — p134, p140)
- Builder Recorder was open during stress test, holding Camera 0 stream
- DSHOW only allows one camera active at a time on some USB controllers
- Worker `capture_fresh` (open→capture→close) conflicts with Recorder `capture_frame` (kept open)
- **Mitigation pending**: Recorder should release camera when worker needs it (KNOWN_ISSUES backlog)

### 3. CHECK_SCREEN + Handler Flow (1 stall — p114)
- Popup appeared, handler ran but didn't resolve, CHECK_SCREEN failed after 3 retries
- Possibly related to camera concurrency (incorrect frame captured)

## Cascade Effect

When one arm stalls, all its queued tasks are auto-rejected (status=4 to PAS). This is by design (DD-011) — a stalled arm cannot safely process more tasks. But it amplifies the failure count:

- 6 actual stalls → triggered 22 auto-rejections
- PAS disables the bank group for the stalled arm, preventing new tasks
- Human operator resumes arm after inspection → PAS re-enables bank group

## Recommendations

1. **Do not open Builder Recorder during production runs** — it blocks camera for all arms
2. **Consider adding camera conflict detection** — if Recorder is streaming, warn or auto-pause stream during worker capture
3. **OCR accuracy is the primary improvement area** — ROI + enhancement help but small digits remain challenging
4. **OCR failure should not always stall** — proposed new status code for OCR mismatch (backlog)
