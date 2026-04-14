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

### Run

**Option A — As Windows Service (recommended for production):**
```bash
cloudflared service install
# Starts automatically on boot
```

Manage:
```bash
# In services.msc → "Cloudflare Tunnel"
# Or:
sc start cloudflared
sc stop cloudflared
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
2. **WA-Unified** (NSSM) — auto-starts, waits for DB on startup
3. **Cloudflare Tunnel** — auto-starts if installed as service

All three are Windows services and auto-start on boot.

## 4. Troubleshooting

| Problem | Check |
|---------|-------|
| Service won't start | `deploy/logs/service_stderr.log` — look for DB connection errors |
| PAS can't reach endpoint | Is Cloudflare Tunnel running? Check `cloudflared tunnel info` |
| 401 on /process-withdrawal | Check `.env` has correct `WA_API_KEY` and `WA_TENANT_ID` |
| 503 on /process-withdrawal | `WA_API_KEY` or `WA_TENANT_ID` is empty in `.env` |
| Arm not responding | Check COM port in Settings, try restart service |
| Camera black/stale | Service restart resets camera; check USB connection |
