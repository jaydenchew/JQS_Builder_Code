# New Machine Installation Guide

End-to-end steps to bring a fresh Windows machine from bare OS to running production WA Unified System with 1+ arms connected. Follow in order; do not skip verification.

Target reader: deployment engineer setting up arm N on a new computer. Expected time: 45-60 minutes on first run, 20-25 minutes once familiar.

For the overview of what each piece does, read [README.md](README.md) and [deploy/README.md](deploy/README.md) first.

---

## Prerequisites

### Hardware (verify before starting)

- Windows 10/11 (64-bit)
- Mechanical arm(s) with USB-serial adapter (CH340 chipset typical)
- USB webcam(s), one per arm, positioned over the phone stage
- Phone(s) on stage(s), powered on, unlocked, with bank apps installed
- Calibration card (50x50mm crosshair card shipped by the arm vendor)

### Required software (install first, in this order)

1. **Git for Windows** - https://git-scm.com/download/win
2. **Python 3.11 (64-bit)** - https://www.python.org/downloads/release/python-3119/
   - Install to default `C:\Program Files\Python311\`
   - Check "Add Python to PATH" during install
3. **Docker Desktop** - https://www.docker.com/products/docker-desktop
   - Start it and wait for "Engine running" before proceeding
4. **Cloudflared** - https://github.com/cloudflare/cloudflared/releases/latest
   - Download `cloudflared-windows-amd64.exe`, rename to `cloudflared.exe`
   - Place in `C:\Program Files (x86)\cloudflared\` (install_tunnel.ps1 looks there)
   - Add that path to system PATH
5. **CH340 driver** (if using CH340 USB-serial adapters, check Device Manager)
   - Driver vendor: http://www.wch-ic.com/downloads/CH341SER_EXE.html
   - Version tested: 3.9.2024.9 (2024-09-16 by `wch.cn`). Mismatches between machines have caused WCF `open_port` to return `0` instead of a valid handle.

### Pre-flight check

Open a PowerShell (regular, not admin) and run:

```powershell
git --version
python --version      # should print 3.11.x
docker --version
docker ps             # should not error; Docker Desktop must be running
cloudflared --version
```

If any command fails, fix it before continuing.

---

## Step 1: Clone the repo

```powershell
cd C:\Users\<your-username>\Desktop
git clone https://github.com/jaydenchew/JQS_Builder_Code.git
cd JQS_Builder_Code
```

After clone, confirm these folders exist (they hold tracked binaries essential to install):

- `arm_service/service/WindowsService1.exe` and `Dll1.dll`
- `arm_service/VC_redist.x86.exe`
- `deploy/nssm.exe`, `deploy/tesseract-setup.exe`
- `models/craft_mlt_25k.pth`, `models/english_g2.pth`

If any are missing, `git lfs` might be blocking them; run `git lfs pull` or reclone.

---

## Step 2: Install the Arm WCF Service

This is the vendor-supplied service that talks to the arm over COM. Without it, Python cannot move the arm.

```powershell
# 1. Install VC++ Redistributable (required by Dll1.dll)
arm_service\VC_redist.x86.exe /quiet /norestart

# 2. Register the Windows Service
# Right-click arm_service\service\安装.bat -> Run as Administrator
```

**Verify** in a browser or curl:

```
http://127.0.0.1:8082/MyWcfService/getstring?duankou=COM6&hco=0&daima=0
```

Replace `COM6` with the actual COM port of an arm you have connected. Expected response: a positive integer handle like `"2448"`. Response of `"0"` means WCF can see the port but nothing is responding on the other end (arm powered off or cable loose). A negative number means the port is already in use.

Also verify the Windows Service is present and running:

```powershell
Get-Service JxbService
# STATUS should be Running
```

---

## Step 3: Install Tesseract OCR

Required for the random PIN keypad recognition flow.

```powershell
deploy\tesseract-setup.exe
```

Install to the default path `C:\Program Files\Tesseract-OCR\` (the code looks there).

Verify:

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
```

---

## Step 4: Start MySQL (Docker)

```powershell
docker-compose up -d
```

Wait about 30 seconds for MySQL to initialize. First run automatically executes `db/schema.sql` to create tables.

Verify:

```powershell
docker ps
# Should show wa-unified-mysql running

docker exec wa-unified-mysql mysql -uroot -pwa_unified_2026 -e "SHOW DATABASES;"
# Should list wa_db
```

If you see an old `builder-mysql` container occupying port 3308, stop it: `docker stop builder-mysql`.

---

## Step 5: Configure `.env`

Copy and edit:

```powershell
Copy-Item .env.example .env
notepad .env
```

Required keys on every machine:

- `DB_PASSWORD=wa_unified_2026` (matches docker-compose.yml)
- `WA_API_KEY` and `WA_TENANT_ID` — set to match what PAS will send. If empty, the protected endpoints return 503.
- `PAS_API_URL`, `PAS_API_KEY`, `PAS_TENANT_ID` — for callbacks back to PAS.

Per-machine defaults (only used before the arms table is populated):

- `ARM_COM_PORT=COM6` (fallback)
- `CAMERA_ID=0` (fallback)

These are only read when a request lacks `arm_id`. Once the arms table has rows, each worker uses its own per-arm values.

---

## Step 6: Install the WA Service (creates venv + NSSM)

Right-click `deploy\install_service.bat` -> **Run as Administrator**. The script:

1. Creates `venv\` if missing using `C:\Program Files\Python311\python.exe`
2. Installs `requirements.txt` into the venv
3. Pre-downloads EasyOCR models into `models\` (already in repo, but this is a safety net; expect `EasyOCR models OK` line)
4. Registers Windows service `WA-Unified` via NSSM on port 9000
5. Configures log rotation (10MB / daily) at `deploy\logs\`
6. Starts the service

If it aborts on the pip step, check `requirements.txt` download errors (network? proxy?). You can re-run the script; it's idempotent.

**Verify**:

```powershell
curl http://127.0.0.1:9000/health
# Should return JSON with status: ok
```

If the service starts but `/health` fails, check `deploy\logs\service_stderr.log` for the actual error (typical: DB password mismatch, arm service unreachable, camera busy).

---

## Step 7: Install Cloudflare Tunnel

Only needed if this machine receives PAS callbacks from the public internet. Skip for dev / offline setups.

### Pick your names first

Before running any command, decide these two values for this machine. They are **your** choices based on the domain you own and your own naming convention:

- `<TUNNEL_NAME>` - the Cloudflare tunnel identifier (internal, any string). Example conventions: `wa-system`, `wa-main`, `acme-arm-01`. Must be **unique per machine on the same Cloudflare account**.
- `<HOSTNAME>` - the public FQDN that PAS will call. Example: `wa.yourdomain.com`, `withdrawal.acme.io`, `arm-prod-1.api.yourdomain.com`. Must resolve to a zone you control in Cloudflare.

Examples below use placeholders - replace `<TUNNEL_NAME>` and `<HOSTNAME>` with your actual values.

### First-time setup on this Cloudflare account (one-time per machine)

```powershell
# Opens browser for Cloudflare login. Downloads cert.pem to ~/.cloudflared/
cloudflared tunnel login

# Create a tunnel with your chosen name (must be unique on this CF account).
cloudflared tunnel create <TUNNEL_NAME>

# Route your chosen hostname to this tunnel. Use --overwrite-dns if the
# hostname was previously routed to another tunnel on this Cloudflare account.
cloudflared tunnel route dns <TUNNEL_NAME> <HOSTNAME>
```

### Edit `deploy\install_tunnel.ps1`

Open the file and change line 20 to your hostname:

```powershell
$HOSTNAME = "<HOSTNAME>"   # e.g. "wa.yourdomain.com"
```

The script does NOT read the tunnel name - it finds whichever `.json` credentials file is present in `%USERPROFILE%\.cloudflared\`, which is whatever tunnel you just created via `tunnel create`. If you have multiple tunnel credentials in that directory (from previous setups), delete the stale ones or the script may pick the wrong tunnel.

### Install as Windows service

```
Right-click deploy\install_tunnel.bat -> Run as Administrator
```

The script will:
1. Verify admin + nssm + cloudflared + credentials
2. Write `%USERPROFILE%\.cloudflared\config.yml`
3. Register `CF-Tunnel` as a Windows Service
4. Start it
5. Assert it reached RUNNING state (throws if not)

### Verify

```powershell
curl https://<HOSTNAME>/health
# Should return the same JSON as localhost:9000/health
```

### Cloudflare dashboard settings (critical - without these PAS gets 403)

Go to Cloudflare Dashboard -> your zone -> **Security -> Settings**:

- **Browser Integrity Check** -> OFF (blocks non-browser User-Agents like PAS)
- **Bot Fight Mode** -> OFF (same reason)

These settings apply to the entire zone. If you need browser protection on other subdomains, use WAF rules to create an exception specifically for `<HOSTNAME>`.

See `deploy/README.md` Multi-machine section for pitfalls when reusing hostnames across tunnels.

---

## Step 8: First-time application configuration (Builder UI)

Open `http://localhost:9000/` in a browser. The Dashboard will likely be empty. Configure in this order:

### 8.1 Add arms

Go to `/settings` -> **Arms** section. Click **Add Arm**:

- `name`: human-readable (e.g., ARM-01)
- `com_port`: COM port of the arm (e.g., COM6). Check Device Manager -> Ports if unsure.
- `service_url`: leave as default `http://127.0.0.1:8082/MyWcfService/getstring`
- `z_down`: 10 (default press depth)
- `camera_id`: OpenCV device index of this arm's camera (0, 1, 2, ...). Click **Scan Cameras** for a list.
- `active`: TRUE

Save. Dashboard should now show the arm card. If camera_id is wrong, the preview will be from a different camera -- use Dashboard -> Verify button to check each arm.

### 8.2 Add stations

Settings -> **Stations** -> for each station connected to an arm:

- `arm_id`: which arm owns this station
- `name`: human-readable

### 8.3 Add phones and bank apps

Settings -> **Phones** and **Bank Apps** -> populate per station.

### 8.4 Restart the WA service

After major settings changes (especially adding arms or changing `camera_id`), restart so workers pick up the new DB:

```powershell
nssm restart WA-Unified
```

---

## Step 9: Calibrate each station

Every station needs a one-time calibration mapping camera pixels to arm coordinates. This uses the 50x50mm fiducial calibration card shipped with the arm.

Open Builder (`/recorder`), pick an arm and station, connect the arm and open the camera, then click **Calibrate**.

The 3-step flow:

1. **Capture photo**: place the card on the phone stage with its printed edges **roughly parallel** to the arm's X/Y axes. Jog the arm so the whole inner black square is in view. Click `Capture Photo`.

2. **Click 4 corners**: on the photo, click the corners of the **inner black square** in order: Top-Left -> Top-Right -> Bottom-Right -> Bottom-Left. Markers appear colored. A green crosshair overlay shows the predicted center (geometric mean of the 4 corners).

3. **Align pen to crosshair**: use the jog panel inside the modal (0.1 / 1 / 5 mm step) or arrow keys to move the arm. Optionally click **Press** to lower the pen and verify the tip physically touches the printed crosshair, then **Lift**. Click **Set Pen Reference & Save**.

**Acceptance criteria** on the result screen:

- `Status: OK` (if `poor_precision`, DB did NOT save; redo)
- `RMSE < 1mm` (ideal; up to 2mm accepted but above 1mm means click imprecision)
- `Per-anchor error` roughly equal across TL/TR/BR/BL (symmetric = good)
- `anisotropy < 1.1` (X/Y scale uniform)
- `rotation` close to 0, 90, 180, or 270 depending on camera mount (any angle is fine, just consistent)

Repeat for every station.

See [DESIGN_DECISIONS.md DD-023](DESIGN_DECISIONS.md) for why this replaces the old 3-point method.

---

## Step 10: Record flows (per bank)

This is bank-specific business logic; not covered here in detail. In short:

- Builder -> **Flows** -> create a template per bank + transfer type
- For each flow, record the steps (CLICK / TYPE / SWIPE / PHOTO / OCR_VERIFY / CHECK_SCREEN)
- Each CLICK / SWIPE / TYPE references a `ui_element_key` or `swipe_key` whose coordinates are per-bank per-station (Settings -> Coordinates)

See [CHECK_SCREEN_OPS.md](CHECK_SCREEN_OPS.md) for the screen-verification step operations guide.

---

## Step 11: End-to-end test

Trigger one real withdrawal via PAS, or use the API directly:

```powershell
curl -X POST http://localhost:9000/process-withdrawal `
  -H "X-Api-Key: <WA_API_KEY>" `
  -H "X-Tenant-ID: <WA_TENANT_ID>" `
  -H "Content-Type: application/json" `
  -d '{ "process_id": 1, ... }'
```

Monitor:

- Dashboard (`/`) shows the arm go from idle -> busy
- Live Logs show each step executing
- Transactions (`/transactions`) records the final result

If the arm stalls, check `stall_reason` on the arm card and drill into the transaction for the step that failed.

---

## Verification checklist (all must pass)

Step | Command / Action | Expected
---|---|---
Git, Python, Docker, cloudflared | `xxx --version` | All print version info
Arm WCF | `curl http://127.0.0.1:8082/MyWcfService/getstring?duankou=COM6&hco=0&daima=0` | Positive integer
Tesseract | `tesseract --version` | Prints version
MySQL | `docker ps` | `wa-unified-mysql` running
WA Service | `curl http://127.0.0.1:9000/health` | `{"status": "ok"}`
NSSM services | `sc query WA-Unified` / `sc query CF-Tunnel` | RUNNING
Public tunnel | `curl https://<HOSTNAME>/health` | `{"status": "ok"}`
Builder | Open `http://localhost:9000/recorder` | Page loads, arms visible
Each arm connects | Click "Connect Arm" in Builder | Green dot, no error
Each camera | Click "Open Camera" | Live preview
Each station calibrated | Settings -> Stations shows "Calibrated" dot | Green
Flow runs | Trigger a test transaction | Reaches completion or a meaningful stall reason (not "unknown")

---

## Troubleshooting

### `curl http://127.0.0.1:8082/MyWcfService/getstring?...` returns `0`

The WCF service can open the port but gets no response from the arm. Check:
- Arm powered on?
- USB-serial cable seated on both ends?
- CH340 driver matches the version in the field-tested fleet (3.9.2024.9)?
- Right COM port number (Device Manager)?

### Builder "Connect Arm" shows "COM in use", then 2nd click says "Connected" but arm doesn't move

Already fixed in commit 9d84be9. Make sure your local repo includes this fix (`git log --oneline | grep open_port`).

### Calibration produces `Status: poor_precision` repeatedly

- Card placed with edges not parallel to arm X/Y -> RMSE > 2mm, redo with better alignment
- 4 corner clicks imprecise -> zoom Builder to 150% with Ctrl++ and reclick
- Severe camera tilt causing perspective distortion -> physically adjust camera mount; if unfixable, each station will have systematic error that RMSE may flag

### `nssm.exe: Can't open service!` in red during `install_tunnel.bat`

Harmless. The script tries to stop/remove any existing CF-Tunnel service first; on a clean machine that command fails because no service exists. As long as the final line says `Service status: RUNNING`, the install succeeded.

### Dashboard shows camera from a different arm

You probably changed `camera_id` in Settings without restarting the service. Run `nssm restart WA-Unified`. Per DD (implicit in worker_manager), workers only reread `camera_id` at start.

### Tunnel auto-deployed to the wrong tunnel (old UUID)

Cloudflare keeps the DNS -> tunnel binding on their side. If you previously routed `<HOSTNAME>` to a different tunnel, re-run with `--overwrite-dns`:

```powershell
cloudflared tunnel route dns --overwrite-dns <TUNNEL_NAME> <HOSTNAME>
```

See [deploy/README.md - Multi-machine deployment](deploy/README.md) for full hostname/tunnel isolation details.

---

## Backup & restore

After the machine is configured, export the seed data periodically:

```powershell
py db\export_seed.py
```

Restore on a new machine (before Step 10):

```powershell
docker-compose down -v
docker-compose up -d
Start-Sleep 30
py db\export_seed.py --import
```

Note: `db/seed.sql` is in `.gitignore` because it contains real credentials. Transport via secure channel only.

---

## Where to get help

- Service won't start -> `deploy\logs\service_stderr.log`
- Cloudflare tunnel -> `deploy\logs\` (via NSSM) or `services.msc` -> CF-Tunnel -> "Recent events"
- WCF arm service (JxbService) -> Windows Event Viewer -> Application log
- MySQL -> `docker logs wa-unified-mysql`
- Algorithm decisions -> `DESIGN_DECISIONS.md` (DD-001 through DD-023)
- Feature history -> `CHANGELOG.md`
