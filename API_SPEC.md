# WA API Specification

> Version: 1.0
> Base URL: `https://wa.evolution-x.io`
> Last updated: 2026-04-14

---

## Authentication

All requests to WA must include these headers:

| Header | Value |
|--------|-------|
| `X-Tenant-ID` | `apexnova` |
| `X-Api-Key` | _(provided separately)_ |

Missing or invalid credentials return `401 Unauthorized`.
If WA server auth is not configured, returns `503 Service Unavailable`.

---

## 1. Trigger Withdrawal (PAS → WA)

Initiates a withdrawal automation task.

```
POST /process-withdrawal
Content-Type: application/json
```

### Request

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `process_id` | Integer | Yes | Unique withdrawal process ID (assigned by PAS) |
| `currency_code` | String | Yes | Currency: `USD`, `KHR`, etc. |
| `amount` | Float | Yes | Transfer amount (must be > 0) |
| `pay_from_bank_code` | String | Yes | Source bank code (e.g., `ABA`, `ACLEDA`, `WINGBANK`) |
| `pay_from_account_no` | String | Yes | Source account number (must be registered in WA) |
| `pay_to_bank_code` | String | Yes | Destination bank code |
| `pay_to_account_no` | String | Yes | Destination account number |
| `pay_to_account_name` | String | Yes | Destination account holder name |

### Response

```json
// Success — task accepted and queued
{
  "status": true,
  "message": "Withdrawal Request Accepted",
  "data": null
}

// Failure — task rejected (not queued)
{
  "status": false,
  "message": "<reason>",
  "data": null
}
```

### Rejection Reasons

| Message | Cause |
|---------|-------|
| `Duplicate process_id` | This process_id has already been submitted |
| `Self-transfer rejected: sender and receiver are the same account` | Same bank + same account on both sides |
| `Bank app not found for given bank_code + account_no` | Source account not registered in WA system |
| `Assigned arm is offline or inactive` | The machine handling this account is down |

### Notes

- Response is **immediate** — WA does not wait for the transfer to complete
- Actual result is delivered asynchronously via **callback** (see section 2)
- Each `process_id` can only be submitted once

---

## 2. Withdrawal Result Callback (WA → PAS)

After WA finishes processing (success or failure), it calls back PAS with the result.

```
POST {PAS_API_URL}/process-withdrawal
Content-Type: multipart/form-data
```

### Request

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `process_id` | Integer | Yes | The original process ID from PAS |
| `status` | Integer | Yes | Result status code (see table below) |
| `transaction_datetime` | String | Yes | Completion time, format: `YYYY-MM-DD HH:MM:SS`, timezone: **UTC+0** |
| `receipt` | File (JPEG) | No | Receipt screenshot (max 5MB). Included for status 1/2/3/4 when available |

### Status Codes

| Status | Meaning | Description |
|--------|---------|-------------|
| `1` | **Success** | Transfer completed successfully. Receipt screenshot attached. |
| `2` | **Failed** | Transfer was attempted but bank app showed failure (detected via OCR on receipt screen). |
| `3` | **In Review** | Transfer was submitted but bank shows "pending" or "in review" status. |
| `4` | **Stall** | Automation failed at some step (before or during transfer). Machine paused for human inspection. May or may not have receipt. |

### Retry Behavior

- WA retries callback up to **3 times** on failure
- Retry intervals: **5 seconds → 15 seconds → 30 seconds**
- If all retries fail, WA records the transaction as "callback not sent"
- PAS should implement its own timeout mechanism (e.g., if no callback received within 30 minutes, query `/status/{process_id}`)

### When Status 4 (Stall) Occurs

- All queued tasks for the same machine are also automatically rejected with status `4`
- The machine goes offline and requires manual inspection
- PAS should not re-send the same `process_id` — instead, create a new withdrawal with a new `process_id` after the issue is resolved

---

## 3. Query Transaction Status (PAS → WA)

Check the current status of a withdrawal.

```
GET /status/{process_id}
```

### Response

```json
{
  "process_id": 12345,
  "status": "success",
  "error_message": null,
  "created_at": "2026-04-14 08:00:00",
  "started_at": "2026-04-14 08:00:05",
  "finished_at": "2026-04-14 08:01:30"
}
```

### Status Values

| Value | Meaning |
|-------|---------|
| `not_found` | No transaction with this process_id |
| `queued` | Waiting to be processed |
| `running` | Currently being executed |
| `success` | Completed successfully (callback status=1) |
| `failed` | Failed as determined by receipt OCR (callback status=2 or 3) |
| `stall` | Automation error, needs manual inspection (callback status=4) |

---

## 4. Health Check

Check if WA system is operational. No authentication required.

```
GET /health
```

### Response

```json
{
  "status": "ok",
  "arm_status": "ARM-01:idle, ARM-02:idle, ARM-03:idle",
  "db_connected": true,
  "details": null
}
```

| Field | Description |
|-------|-------------|
| `status` | `ok` or `error` |
| `arm_status` | Comma-separated list of machine statuses |
| `db_connected` | Whether database is reachable |
| `details` | Error details (only when status=error) |

---

## Supported Banks

### Source Banks (pay_from)

Banks with apps installed and configured on WA machines:

| Bank Code | Bank Name | Region |
|-----------|-----------|--------|
| `ABA` | ABA Bank | Cambodia |
| `ACLEDA` | ACLEDA Bank | Cambodia |
| `WINGBANK` | WING Bank | Cambodia |
| `CIMB` | CIMB Bank | Malaysia |
| `MBB` | Maybank | Malaysia |

### Destination Banks (pay_to)

For **same-bank transfers**: destination bank must match source bank.

For **interbank transfers**: destination can be any bank listed below per source bank.

#### ACLEDA Interbank Destinations (59 banks)

| Bank Code | Display Name |
|-----------|-------------|
| `ABA` | ABA Bank |
| `AEON` | Aeon Specialized Bank |
| `ALPHA` | Alpha Commercial Bank PLC |
| `AMK` | AMK Microfinance Plc. |
| `AMRET` | Amret Plc. |
| `APD` | APD Bank |
| `ARDB` | ARDB Bank |
| `ASIAWEI` | Asia Wei Luy |
| `BOCHK` | Bank of China (Hong Kong) |
| `BIDC` | BIDC Bank |
| `BONGLOY` | BongLoy |
| `BOOYOUNG` | Booyoung Khmer Bank |
| `BRED` | BRED Bank (Cambodia) Plc |
| `BRIDGE` | BRIDGE Bank |
| `CAB` | Cambodia Asia Bank |
| `CPB` | Cambodia Post Bank Plc |
| `CAMPU` | Cambodian Public Bank Plc |
| `CANADIA` | Canadia Bank Plc |
| `CATHAY` | CATHAY UNITED BANK |
| `CCU` | CCU Commercial Bank PLC. |
| `CHIEF` | Chief (Cambodia) Commercial |
| `CHIPMONG` | Chip Mong Commercial Bank plc |
| `CIMB` | CIMB |
| `COOLCASH` | Cool Cash Plc |
| `DARASAKOR` | Dara Sakor Pay PLC |
| `DGB` | DGB Bank |
| `EMONEY` | EMoney |
| `FCB` | First Commercial Bank |
| `FTB` | Foreign Trade Bank of Cambodia |
| `HATTHA` | Hattha Bank Plc |
| `HENGFENG` | Heng Feng (Cambodia) Bank |
| `HLB` | Hong Leong Bank (Cambodia) |
| `IBANK` | IBANK (CAMBODIA) PLC. |
| `ICBC` | ICBC |
| `JTRUST` | J Trust Royal Bank Plc. |
| `KBPRASAC` | KB PRASAC Bank Plc |
| `KESS` | Kess Innovation Plc. |
| `LANTON` | Lanton Pay |
| `LOLC` | LOLC (Cambodia) Plc. |
| `LYHOUR` | LYHOUR VELUY |
| `MAYBANK` | Maybank Cambodia Plc |
| `MBBANK` | MB BANK (CAMBODIA) PLC |
| `MOHANOKOR` | MOHANOKOR MFI Plc |
| `ORIENTAL` | Oriental Bank |
| `PEAK` | PEAK WEALTH BANK PLC |
| `PHILLIP` | Phillip Bank Plc |
| `PPCB` | Phnom Penh Commercial Bank |
| `PIPAY` | Pi Pay Plc. |
| `RHB` | RHB BANK(CAMBODIA) Plc. |
| `SACOMBANK` | Sacombank Cambodia |
| `SATHAPANA` | Sathapana Bank Plc |
| `SBI` | SBI LY HOUR Bank Plc. |
| `SHINHAN` | Shinhan Bank Cambodia Plc |
| `TRUEMONEY` | TrueMoney Cambodia |
| `UPAY` | U-Pay Digital Plc |
| `UCB` | Union Commercial Bank Plc |
| `VATTANAC` | Vattanac Bank |
| `WINGBANK` | WING BANK |
| `WOORI` | Woori Bank (Cambodia) Plc. |

#### CIMB Interbank Destinations (21 banks — Malaysia)

| Bank Code | Display Name |
|-----------|-------------|
| `AFFIN` | Affin Bank Berhad |
| `ABMB` | Alliance Bank Malaysia Berhad |
| `AMMB` | AmBank (M) Berhad |
| `BIMB` | Bank Islam Malaysia Berhad |
| `BKRM` | Bank Kerjasama Rakyat Malaysia Berhad |
| `BMMB` | Bank Muamalat Malaysia Berhad |
| `BOC` | Bank of China |
| `AGRO` | Bank Pertanian Malaysia Berhad |
| `BSN` | Bank Simpanan Nasional |
| `CITI` | Citibank Berhad |
| `GX` | GX Bank |
| `HLB` | Hong Leong Bank Berhad |
| `HSBC` | Hongkong Bank Malaysia Berhad |
| `MBB` | Malayan Banking Berhad / Maybank |
| `OCBC` | OCBC |
| `PBE` | Public Bank Berhad |
| `RHB` | RHB Bank |
| `RYTB` | RYT Bank |
| `SCB` | Standard Chartered Bank Malaysia Berhad |
| `TNG` | Touch N Go |
| `UOB` | United Overseas Bank Limited |

#### MBB (Maybank) Interbank Destinations (1 bank — Malaysia)

| Bank Code | Display Name |
|-----------|-------------|
| `CIMB` | Cimb Bank |

---

## Flow Diagram

```
PAS                          WA System                       Banking App
 │                              │                               │
 │  POST /process-withdrawal    │                               │
 │─────────────────────────────>│                               │
 │  {"status":true}             │                               │
 │<─────────────────────────────│                               │
 │                              │  [Queue task]                 │
 │                              │  [Open banking app]           │
 │                              │─────────────────────────────>│
 │                              │  [Enter details, confirm]     │
 │                              │─────────────────────────────>│
 │                              │  [Capture receipt photo]      │
 │                              │  [OCR verify]                 │
 │                              │                               │
 │  POST callback               │                               │
 │  {status, receipt}           │                               │
 │<─────────────────────────────│                               │
 │                              │  [Close app, ready for next]  │
```

---

## Error Handling Summary

| Scenario | WA Behavior | PAS Should |
|----------|-------------|------------|
| Request accepted | Returns `status:true` immediately | Wait for callback |
| Duplicate process_id | Returns `status:false` | Do not retry same process_id |
| Bank app not found | Returns `status:false`, records as failed | Check WA configuration |
| Arm offline | Returns `status:false`, records as failed | Retry later or use different account |
| Transfer succeeds | Callback `status=1` with receipt | Mark as complete |
| Transfer fails (OCR) | Callback `status=2` with receipt | Mark as failed, investigate |
| Transfer pending (OCR) | Callback `status=3` with receipt | Wait or manually check |
| Automation error | Callback `status=4`, arm pauses | Do not resend; wait for WA operator to resolve |
| Callback fails | WA retries 3x (5s/15s/30s) | If no callback in 30min, query `/status/{process_id}` |
