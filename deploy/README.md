# Deployment Guide

## 1. NSSM Windows Service (WA System)

### Setup
1. Download NSSM from https://nssm.cc/download
2. Extract `nssm.exe` (64-bit) into this `deploy/` folder
3. Run `install_service.bat` **as Administrator**

### Manage

| Action | Command |
|--------|---------|
| Start | `nssm start WA-Unified` |
| Stop | `nssm stop WA-Unified` |
| Restart | `nssm restart WA-Unified` |
| Edit config | `nssm edit WA-Unified` |
| View status | `nssm status WA-Unified` |
| Open GUI | `services.msc` → find "WA Unified System" |

### Logs

Service stdout/stderr: `deploy/logs/service_stdout.log` and `service_stderr.log`

Log rotation (configured in install_service.bat):
- `AppRotateOnline 1` — rotate while service is running
- `AppRotateSeconds 86400` — rotate daily
- `AppRotateBytes 10485760` — rotate at 10MB

### Uninstall

Run `uninstall_service.bat` as Administrator.

## 2. Cloudflare Tunnel (PAS Connectivity)

### Why Cloudflare Tunnel?

The WA system runs on a local machine without a public IP. Cloudflare Tunnel creates a secure outbound connection from the machine to Cloudflare's edge, giving PAS a stable HTTPS endpoint to send withdrawal requests.

### First-time Setup

```bash
# 1. Login to Cloudflare (opens browser)
cloudflared tunnel login

# 2. Create tunnel
cloudflared tunnel create wa-system

# 3. Add DNS route (replace with your domain)
cloudflared tunnel route dns wa-system wa.yourdomain.com
```

### Configuration

Create `C:\Users\<your-user>\.cloudflared\config.yml`:

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

**Security**: Only 3 paths are exposed. Dashboard, Builder, Settings, and all configuration APIs are NOT accessible from the internet — only from localhost.

### Cloudflare Security Settings (Required)

Go to Cloudflare Dashboard → your domain → **Security → Settings**:

1. **Browser Integrity Check** → Turn **OFF**
   - This blocks API requests without browser-like User-Agent headers
   - PAS sends programmatic requests (not browser traffic), so this must be off
   - Without this, PAS gets `403 (error code 1010)` from Cloudflare edge

2. **Bot Fight Mode** → Keep **OFF**
   - Same reason — API clients are not bots

These settings apply to the entire domain. If you need browser protection on other subdomains, use WAF rules to create an exception specifically for `wa.yourdomain.com`.

### Run

**Option A — As Windows Service via NSSM (recommended for production):**

`cloudflared service install` runs as LocalSystem which cannot access user-directory config files. Use NSSM instead (same as WA service):

```bash
# Install (run as Administrator)
nssm install CF-Tunnel "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --config "C:\Users\<your-user>\.cloudflared\config.yml" run wa-system
nssm set CF-Tunnel DisplayName "Cloudflare Tunnel (WA)"
nssm set CF-Tunnel ObjectName ".\<your-user>"
nssm start CF-Tunnel
```

Manage:
```bash
nssm start CF-Tunnel
nssm stop CF-Tunnel
nssm restart CF-Tunnel
# Or in services.msc → "Cloudflare Tunnel (WA)"
```

**Option B — Manual (development):**
```bash
cloudflared tunnel run wa-system
```

### Verify

```bash
curl https://wa.yourdomain.com/health -H "X-Api-Key: YOUR_KEY" -H "X-Tenant-ID: apexnova"
```

Should return `{"status": "ok", ...}`.

### ngrok (Testing Only)

For quick testing without Cloudflare setup:
```bash
ngrok http 9000
```
URL changes on every restart. Not suitable for production.

## 3. Service Startup Order

On machine boot, services should start in this order:

1. **Docker** (MySQL) — auto-starts via Docker Desktop
2. **WA-Unified** (NSSM) — auto-starts, binds to 127.0.0.1:9000
3. **CF-Tunnel** (NSSM) — auto-starts, connects localhost:9000 to Cloudflare edge

All three are Windows services and auto-start on boot.

## 4. Troubleshooting

| Problem | Check |
|---------|-------|
| Service won't start | `deploy/logs/service_stderr.log` — look for DB connection errors |
| PAS can't reach endpoint | Is CF-Tunnel running? `nssm status CF-Tunnel` or check services.msc |
| 401 on /process-withdrawal | Check `.env` has correct `WA_API_KEY` and `WA_TENANT_ID` |
| 503 on /process-withdrawal | `WA_API_KEY` or `WA_TENANT_ID` is empty in `.env` |
| Arm not responding | Check COM port in Settings, try restart service |
| Camera black/stale | Service restart resets camera; check USB connection |
