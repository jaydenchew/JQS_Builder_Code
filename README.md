# WA Unified System

Builder UI + Withdrawal Automation + Multi-Arm Workers — single FastAPI process, port 9000.

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

### Step 3: Start Database

```bash
docker-compose up -d
```

Wait ~30s for MySQL init. Docker auto-runs `db/schema.sql` + `db/seed.sql`.

> If old `builder-mysql` is on port 3308: `docker stop builder-mysql`

### Step 4: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Start System

**Option A — Manual (development):**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 9000
```

**Option B — Windows Service (production):**
```
1. Download nssm.exe from https://nssm.cc/download → put in deploy/
2. Right-click deploy/install_service.bat → Run as Administrator
3. Service auto-starts on boot, auto-restarts on crash
```

See `deploy/README.md` for service management commands.

### Step 6: Access

| Page | URL |
|------|-----|
| Dashboard | http://localhost:9000/ |
| Flow Builder | http://localhost:9000/recorder |
| Transactions | http://localhost:9000/transactions |
| Settings | http://localhost:9000/settings |
| API Docs | http://localhost:9000/docs |

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
# Wait 30s — schema.sql + seed.sql auto-execute on fresh volume
```

## Architecture

```
FastAPI (port 9000)
├── Builder UI (Dashboard / Flow Builder / Transactions / Settings)
├── WA API (POST /process-withdrawal, GET /status, GET /health)
├── Monitor API + WebSocket
└── WorkerManager
    ├── ArmWorker #1 (ThreadPoolExecutor + ArmClient + Camera)
    ├── ArmWorker #2
    └── ... (dynamically added)
```

See `ARCHITECTURE_PLAN.md` for full technical details.

## Database (15 tables)

| Table | Purpose |
|-------|---------|
| arms | Machines (com_port, camera_id, active) |
| stations | Stations per arm |
| phones, bank_apps | Phones and bank accounts per station |
| transactions, transaction_logs | Transaction records + step logs |
| flow_templates | Flow definitions (bound to arm_id) |
| flow_steps | Steps within flows |
| ui_elements, keymaps, swipe_actions | Coordinates per station |
| keyboard_configs | Multi-page keyboard definitions |
| bank_name_mappings | Cross-bank transfer name mappings |
| calibrations | Camera-to-arm transform data per station |

## PAS Callback Status

| status | Meaning | DB status | Arm behavior |
|--------|---------|-----------|-------------|
| 1 | Success | `success` | Continue |
| 2 | Fail (receipt check determined) | `failed` | Continue |
| 3 | In Review (receipt check) | `failed` | Continue |
| 4 | Stall (any step failure) | `stall` | Offline + pause, manual inspection required |

## Key API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/process-withdrawal` | POST | Receive withdrawal request |
| `/status/{process_id}` | GET | Query transaction status |
| `/health` | GET | Health check |
| `/api/monitor/ws` | WS | Real-time status push |
| `/api/monitor/logs/ws` | WS | Real-time log streaming |
| `/api/monitor/pause\|resume\|offline/{arm_id}` | POST | Machine control |
| `/api/calibration/auto-calibrate` | POST | 3-point auto calibration |
| `/api/banks/templates/{id}/copy` | POST | Copy flow to another arm |

## Configuration

All config in `.env`. Per-arm hardware config stored in `arms` database table.

## File Structure

```
Builder_JQS_Code/
├── docker-compose.yml      MySQL container
├── .env                    Configuration
├── requirements.txt        Python dependencies
├── README.md               This file
├── ARCHITECTURE_PLAN.md    Technical architecture
├── CHANGELOG.md            Change history
├── arm_service/            Arm WCF Windows Service
├── deploy/                 NSSM service scripts
├── db/                     Schema + seed + scripts
├── app/                    FastAPI application
├── static/                 Frontend (HTML/CSS/JS)
└── references/             CHECK_SCREEN reference images
```
