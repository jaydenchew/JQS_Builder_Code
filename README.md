# WA Unified System

Builder UI + Withdrawal Automation + Multi-Arm Workers — single FastAPI process, port 9000.

For business context and why this system exists, see `BUSINESS_CONTEXT.md`.
For technical architecture, see `ARCHITECTURE_PLAN.md`.
For design decisions that may look unusual, see `DESIGN_DECISIONS.md`.

**Setting up a new machine? Use [INSTALL.md](INSTALL.md)** — a detailed step-by-step
guide with prerequisites, hardware checks, calibration, and a verification
checklist. The condensed version below is for reference only.

## Full Installation (New Machine)

### Step 1: Install Arm WCF Service

```
1. Run arm_service/VC_redist.x86.exe (VC++ runtime)
2. Right-click arm_service/service/安装.bat → Run as Administrator
3. Verify: open http://127.0.0.1:8082/MyWcfService/getstring?duankou=COM6&hco=0&daima=0
```

### Step 2: Install Tesseract OCR (for random PIN keypad)

```
1. Run deploy/tesseract-setup.exe (or download from https://github.com/tesseract-ocr/tesseract/releases)
2. Install to C:\Program Files\Tesseract-OCR (default)
3. Verify: tesseract --version
```

### Step 3: Install Cloudflare Tunnel (for PAS connectivity)

```
1. Download cloudflared from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
2. Run: cloudflared tunnel login  (authorize in browser)
3. Run: cloudflared tunnel create wa-system
4. Run: cloudflared tunnel route dns wa-system wa.yourdomain.com
5. Right-click deploy/install_tunnel.bat → Run as Administrator
```

The script auto-creates `config.yml` and installs as Windows service. See `deploy/README.md` for details.

### Step 4: Start Database

```bash
docker-compose up -d
```

Wait ~30s for MySQL init. Docker auto-runs `db/schema.sql`.

> If old `builder-mysql` is on port 3308: `docker stop builder-mysql`

### Step 5: Configure Environment

Copy `.env.example` to `.env` and fill in:

```env
# Required
DB_PASSWORD=wa_unified_2026

# PAS Integration (WA → PAS callbacks)
PAS_API_URL=https://apisix.mxlpmsstaging.com/service/payment/api/external
PAS_API_KEY=your_pas_api_key
PAS_TENANT_ID=apexnova

# WA API Auth (PAS → WA requests)
WA_API_KEY=your_wa_api_key
WA_TENANT_ID=apexnova
```

**Important**: If `WA_API_KEY` or `WA_TENANT_ID` is empty, protected endpoints return 503.

### Step 6: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 7: Start System

**Option A — Manual (development):**
```bash
uvicorn app.main:app --host 127.0.0.1 --port 9000
```

**Option B — Windows Service (production):**
```
1. Download nssm.exe from https://nssm.cc/download → put in deploy/
2. Right-click deploy/install_service.bat → Run as Administrator
3. Service auto-starts on boot, auto-restarts on crash
```

See `deploy/README.md` for service management commands.

### Step 8: Access

| Page | URL |
|------|-----|
| Dashboard | http://localhost:9000/ |
| Flow Builder | http://localhost:9000/recorder |
| Transactions | http://localhost:9000/transactions |
| Settings | http://localhost:9000/settings |
| API Docs | http://localhost:9000/docs |

## Cloudflare Tunnel Configuration

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: wa-system
credentials-file: C:\Users\<your-user>\.cloudflared\<tunnel-id>.json

ingress:
  - hostname: wa.yourdomain.com
    path: /process-withdrawal
    service: http://localhost:9000
  - hostname: wa.yourdomain.com
    path: /status/*
    service: http://localhost:9000
  - hostname: wa.yourdomain.com
    path: /health
    service: http://localhost:9000
  - service: http_status:404
```

Only 3 paths are exposed to the internet. All other endpoints (Dashboard, Builder, Settings, etc.) are only accessible from localhost.

**Important Cloudflare settings** (without these, PAS gets 403):
- Security → Settings → **Browser Integrity Check** → OFF
- Security → Settings → **Bot Fight Mode** → OFF

**Install as service:** Run `deploy/install_tunnel.bat` as Administrator. It auto-creates config and installs the NSSM service.

**Or run manually (development):**
```bash
cloudflared tunnel run wa-system
```

Give `https://wa.yourdomain.com` to PAS as the callback endpoint.

## Backup & Restore

### Export current data (run periodically)
```bash
py db/export_seed.py
```
Exports all config tables from running database to `db/seed.sql`.

### Restore from backup
```bash
docker-compose down -v
docker-compose up -d
# Wait 30s — schema.sql auto-executes on fresh volume
# Then import seed: py db/export_seed.py --import
```

## Architecture

```
Internet (PAS)
  │
  │  Cloudflare Tunnel (only /process-withdrawal, /status/*, /health)
  ▼
FastAPI (port 9000, localhost only in production)
├── Builder UI (Dashboard / Flow Builder / Transactions / Settings)
├── WA API (POST /process-withdrawal, GET /status, GET /health)
├── Monitor API + WebSocket
└── WorkerManager
    ├── ArmWorker #1 (ThreadPoolExecutor + ArmClient + Camera)
    ├── ArmWorker #2
    └── ... (dynamically added from DB)
```

See `ARCHITECTURE_PLAN.md` for full technical details.

## Database (14 tables)

| Table | Purpose |
|-------|---------|
| arms | Machines (com_port, camera_id, active) |
| stations | Stations per arm |
| phones, bank_apps | Phones and bank accounts per station |
| transactions, transaction_logs | Transaction records + step logs |
| flow_templates | Flow definitions (bound to arm_id + transfer_type) |
| flow_steps | Steps within flows |
| ui_elements, keymaps, swipe_actions | Coordinates per bank per station |
| keyboard_configs | Multi-page keyboard definitions (JSON) |
| bank_name_mappings | Interbank transfer: bank code → search text |
| calibrations | Camera-to-arm transform data per station |

## PAS Integration

### Request: PAS → WA
```
POST /process-withdrawal
Headers: X-Api-Key, X-Tenant-ID, Content-Type: application/json
Body: { process_id, currency_code, amount, pay_from_bank_code, pay_from_account_no,
        pay_to_bank_code, pay_to_account_no, pay_to_account_name }
```

### Callback: WA → PAS
```
POST {PAS_API_URL}/process-withdrawal
Body: multipart/form-data { process_id, status, transaction_datetime, receipt.jpg }
Retry: up to 3 times (5s/15s/30s backoff)
```

### Status Codes

| status | Meaning | DB status | Arm behavior |
|--------|---------|-----------|-------------|
| 1 | Success | `success` | Continue |
| 2 | Fail (receipt check) | `failed` | Continue |
| 3 | In Review (receipt check) | `failed` | Continue |
| 4 | Stall (any step failure) | `stall` | Offline + pause, queued tasks auto-rejected |

## Key API Endpoints

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/process-withdrawal` | POST | API key | Receive withdrawal request |
| `/status/{process_id}` | GET | API key | Query transaction status |
| `/health` | GET | API key | Health check |
| `/api/monitor/ws` | WS | None (localhost) | Real-time status push |
| `/api/monitor/logs/ws` | WS | None (localhost) | Real-time log streaming |
| `/api/monitor/pause\|resume\|offline/{arm_id}` | POST | None (localhost) | Machine control |

## Documentation

| File | Content |
|------|---------|
| `README.md` | This file — installation and quick reference |
| `ARCHITECTURE_PLAN.md` | Technical architecture, module interactions, camera design |
| `BUSINESS_CONTEXT.md` | Business context, PAS protocol, operations guide |
| `DESIGN_DECISIONS.md` | 14 ADRs — why things are built the way they are |
| `CHANGELOG.md` | All changes with dates |
| `AUDIT_REPORT_7.md` | Latest code audit report |

## File Structure

```
Builder_JQS_Code/
├── docker-compose.yml      MySQL container
├── .env                    Configuration (not in git)
├── requirements.txt        Python dependencies
├── README.md               This file
├── ARCHITECTURE_PLAN.md    Technical architecture
├── BUSINESS_CONTEXT.md     Business context & operations
├── DESIGN_DECISIONS.md     Architecture Decision Records
├── CHANGELOG.md            Change history
├── AUDIT_REPORT_7.md       Latest audit report
├── arm_service/            Arm WCF Windows Service
├── deploy/                 NSSM service scripts + tools
├── db/                     Schema + seed + export script
├── app/                    FastAPI application
├── static/                 Frontend (HTML/CSS/JS)
├── references/             CHECK_SCREEN reference images (per arm)
└── tools/                  Utility scripts
```
