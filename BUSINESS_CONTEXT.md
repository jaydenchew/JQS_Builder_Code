# Business Context — WA Unified System

## What This System Does

This is a **Withdrawal Automation (WA)** system that uses robotic arms to physically operate mobile phones, executing bank transfers on behalf of users. It replaces manual human operators who would otherwise tap through banking apps to process withdrawal requests.

### Why Robotic Arms Instead of APIs?

Many banks in Cambodia do not offer open banking APIs. The only way to programmatically execute transfers through these banks is to physically interact with their mobile apps — tap buttons, type account numbers, swipe to confirm, and capture receipt screenshots.

### System Components

```
PAS (Payment Aggregation System)
  │
  │  HTTP: POST /process-withdrawal
  ▼
WA Unified System (this codebase)
  ├── FastAPI server (single process)
  ├── ArmWorker × N (one per arm)
  ├── Builder UI (flow recording & configuration)
  └── Dashboard (monitoring & control)
  │
  ▼
Physical Hardware
  ├── Robotic Arm × N (uArm Swift Pro, via COM port)
  ├── USB Camera × N (one per arm, views phone screen)
  └── Mobile Phone × N (one per station, with banking apps installed)
```

## PAS Integration Protocol

### Inbound: PAS → WA

PAS sends withdrawal requests:

```
POST /process-withdrawal
Headers: X-Api-Key, X-Tenant-ID
Body: {
  process_id, currency_code, amount,
  pay_from_bank_code, pay_from_account_no,
  pay_to_bank_code, pay_to_account_no, pay_to_account_name
}
```

WA responds immediately with acceptance or rejection (does not wait for execution).

### Outbound: WA → PAS

After execution completes, WA calls back PAS with the result:

```
POST {PAS_API_URL}/process-withdrawal
Body: multipart/form-data {
  process_id, status, transaction_datetime,
  receipt (JPEG file, optional)
}
```

**Status codes:**

| Status | Meaning | When |
|--------|---------|------|
| 1 | Success | Transfer completed, OCR verified receipt |
| 2 | Failed | OCR detected failure keywords on receipt screen |
| 3 | In Review | OCR detected review/pending keywords on receipt |
| 4 | Stall | Any step failed, needs human inspection |

Callback includes retry: up to 3 attempts with 5s/15s/30s backoff. If all fail, `callback_sent_at` stays NULL for manual reconciliation.

### Status Query

PAS can check transaction status:
```
GET /status/{process_id}
```

## Transfer Types

### SAME Bank Transfer
- `pay_from_bank_code == pay_to_bank_code`
- Example: ABA to ABA
- Flow navigates within the same banking app

### INTER Bank Transfer (Interbank)
- `pay_from_bank_code != pay_to_bank_code`
- Example: ACLEDA to ABA
- Flow uses the sending bank's app, navigates to interbank/local transfer section
- Requires `bank_name_mappings` table: maps destination bank code to search text (e.g., `ABA` → search "aba" → select "ABA Bank")
- Flow steps have `_inter` suffix to keep coordinates separate from SAME flows (different screens, different button positions)

### Handler Flows (Popup Handling)
- Some apps show popups (promotions, notifications) after login
- CHECK_SCREEN step detects unexpected screens by comparing to a reference image
- If mismatch detected, runs a "handler flow" (e.g., `ACLEDA_AFTER_POPUP`) to dismiss the popup
- Handler flow has its own `bank_code` (e.g., `ACLEDA_AFTER_POPUP`) and its own coordinates in `ui_elements`
- After handler completes, CHECK_SCREEN retries the comparison

## Physical Deployment Model

### One Arm = One Phone = One Station = One Camera

```
ARM-01 (arm_id=2) ─── Station_1 (station_id=2) ─── Phone with ABA, ACLEDA, WINGBANK apps
  └── Camera 0 (USB camera pointed at phone)
  └── COM6 (serial port to robotic arm)

ARM-02 (arm_id=3) ─── Station_1 (station_id=3) ─── Phone with same apps
  └── Camera 1
  └── COM5

ARM-03 (arm_id=4) ─── Station_1 (station_id=4) ─── Phone with same apps
  └── Camera 2
  └── COM4
```

### Database Relationships

```
arms → stations → phones → bank_apps
                         → ui_elements (coordinates per bank per station)
                         → keymaps (keyboard key positions)
                         → keyboard_configs (multi-page keyboard JSON)
                         → swipe_actions (swipe start/end positions)
                         → calibrations (pixel-to-arm coordinate transform)
```

### Task Routing

When PAS sends a request for bank_code=ACLEDA, account_no=123:
1. Find `bank_apps` where `bank_code='ACLEDA' AND account_no='123' AND status='active'`
2. This gives `station_id` → `arm_id`
3. Task is queued for that specific arm's worker

## Builder: How Flows Are Created

### Recording a Flow

1. Pause the arm on Dashboard
2. Open Builder (Recorder page)
3. Connect to the arm
4. Select bank and transfer type (SAME/INTER)
5. For each step:
   - Move arm to position using camera view
   - Click to record coordinate
   - Set step name, action type, delays
6. Save flow → writes `flow_steps` + `ui_elements` + `keymaps`

### Action Types

| Type | What It Does |
|------|-------------|
| CLICK | Arm taps a screen position |
| TYPE | Arm types text using recorded keyboard positions |
| SWIPE | Arm swipes from point A to point B |
| PHOTO | Arm moves to camera position, captures screenshot |
| OCR_VERIFY | Captures screenshot, OCR reads text, verifies account/amount |
| CHECK_SCREEN | Captures screenshot, compares to reference image |
| ARM_MOVE | Arm moves to a position (no tap) |

### Coordinate System

- Every CLICK/PHOTO/OCR_VERIFY/CHECK_SCREEN step uses `step_name` as `ui_element_key`
- Coordinates stored in `ui_elements` table: `(bank_code, station_id, element_key) → (x, y)`
- Each step has independent coordinates; SAME and INTER flows use `_inter` suffix to avoid conflicts
- Camera position for stall photos is separate: `stations.stall_photo_x/y`

## Operations

### When an Arm Stalls

1. A step fails during execution
2. System captures a stall photo (full phone screen)
3. Callbacks PAS with status=4 + screenshot
4. All queued tasks for this arm are auto-rejected (status=4 to PAS)
5. Arm goes offline and pauses
6. **Human must**: check phone screen, resolve the issue, then Resume on Dashboard

### Adding a New Bank

1. Install the banking app on all phones
2. In Builder: create flow template (SAME and/or INTER)
3. Record all steps with coordinates
4. Record keyboards (password, account number, amount)
5. If interbank: add entries to `bank_name_mappings`
6. If popup handling needed: create handler flow template
7. Add `bank_apps` entries in Settings for each station

### Adding a New Arm

1. Connect hardware (arm via USB/COM, camera via USB)
2. In Settings: create arm entry with COM port and camera ID
3. Create station linked to the arm
4. Run calibration (3-point auto-calibrate)
5. Copy flows from existing arm (Builder → Copy → select target arm)
6. Adjust coordinates using logo position offsets
7. Add phone and bank_apps entries
