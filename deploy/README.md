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
  - hostname: wa.yourdomain.com
    path: /api/monitor/export/daily-summary
    service: http://localhost:9000
  - service: http_status:404
```

**Security**: Only the withdrawal/status/health endpoints plus the authenticated daily report export are exposed. Dashboard, Builder, Settings, and all configuration APIs are NOT accessible from the internet — only from localhost.

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

### Multi-machine deployment (additional machines on the same Cloudflare account)

When deploying a second (or third) machine, each one needs its own tunnel and hostname. The first machine used whatever `<TUNNEL_NAME>` + `<HOSTNAME>` you chose in the primary setup (for example, `wa-system` + `wa.yourdomain.com`). Additional machines must pick distinct names.

Decide per machine (example naming scheme):
- Primary:   `<TUNNEL_NAME>` = `wa-system`,  `<HOSTNAME>` = `wa.yourdomain.com`
- Machine 2: `<TUNNEL_NAME>` = `wa2-system`, `<HOSTNAME>` = `wa2.yourdomain.com`
- Machine 3: `<TUNNEL_NAME>` = `wa3-system`, `<HOSTNAME>` = `wa3.yourdomain.com`

The naming is your own convention — any unique string on the Cloudflare account works. The code does not read these names; `install_tunnel.ps1` only reads `$HOSTNAME` and auto-discovers whichever tunnel credentials JSON is sitting in `%USERPROFILE%\.cloudflared\`.

**On the new machine (Administrator PowerShell):**

```powershell
# 1. One-time Cloudflare auth (browser popup)
cloudflared tunnel login

# 2. Create a NEW tunnel with your chosen distinct name
cloudflared tunnel create <TUNNEL_NAME>

# 3. Route your chosen hostname to the new tunnel.
#    If <HOSTNAME> was previously pointed at another tunnel on your
#    Cloudflare account (common when reusing subdomains), you MUST add
#    --overwrite-dns or the route stays pointing at the old tunnel:
cloudflared tunnel route dns --overwrite-dns <TUNNEL_NAME> <HOSTNAME>
```

**Then edit `deploy/install_tunnel.ps1` line 20:**

```powershell
$HOSTNAME = "<HOSTNAME>"   # your chosen hostname, e.g. wa2.yourdomain.com
```

**Then run:** right-click `deploy/install_tunnel.bat` → Run as Administrator.

Verify: `curl https://<HOSTNAME>/health` returns `{"status": "ok"}`.

**Common pitfalls:**
- `<HOSTNAME> is already configured to route to your tunnel tunnelID=<old-uuid>` during step 3 means the hostname was previously routed to another tunnel on your account. Re-run with `--overwrite-dns` to force re-route.
- `nssm.exe: Can't open service!` red text on first install is **harmless** — the install script tries to stop/remove an existing service before creating a fresh one; on a clean machine the stop/remove just has nothing to act on, but NSSM prints to stderr anyway. As long as the final line says `Service status: RUNNING`, it succeeded.
- `Cannot establish a connection to the service control manager: Access is denied` means PowerShell wasn't launched as Administrator. Close it and open a new PowerShell with **Run as Administrator**.
- `.cloudflared/` directory has multiple `.json` files from previous setups — the install script picks the first one alphabetically. If that's not the tunnel you just created, delete the stale credentials files or the config will point at the wrong tunnel.

## 3. Service Startup Order

On machine boot, services should start in this order:

1. **Docker** (MySQL + Mosquitto MQTT) — auto-starts via Docker Desktop
2. **WA-Unified** (NSSM) — auto-starts, binds to 127.0.0.1:9000
3. **CF-Tunnel** (NSSM) — auto-starts, connects localhost:9000 to Cloudflare edge

All three are Windows services and auto-start on boot. The Mosquitto container (`wa-mosquitto`) is part of the same `docker-compose.yml` as MySQL — it only matters if smart plugs are in use (see section 5).

## 4. Smart Plug Broker (Mosquitto MQTT)

The smart plug feature uses Eclipse Mosquitto running as the `wa-mosquitto` Docker container, listening on `0.0.0.0:1883` (no auth, plain TCP). This is intentionally a LAN-only deployment — the broker is not exposed through Cloudflare Tunnel.

### What `install_service.bat` configures automatically

- Opens **TCP 1883** in Windows Firewall for `Private+Domain` profiles. Without this rule the container listens but LAN-side plugs are silently blocked at the host edge. Idempotent — re-running the installer just re-creates the rule.
- To verify: `netsh advfirewall firewall show rule name="Mosquitto MQTT 1883"`.
- To remove: `netsh advfirewall firewall delete rule name="Mosquitto MQTT 1883"`.

### Where operators get the MQTT settings to type into a new plug

`http://localhost:9000/settings` shows a blue banner above the stations tree with:
- the host's auto-detected LAN IP,
- port `1883`,
- the per-plug topic patterns (`GemeOpen/<client-id>/sub`, `GemeOpen/<client-id>/pub`),
- a note that the vendor App labels Subscribe / Publish in reverse compared to MQTT convention — copy verbatim, don't try to swap.

The banner reads from `GET /api/monitor/mqtt-broker` (auto-detect via UDP-socket-to-8.8.8.8 trick).

### Verifying a plug responds

```powershell
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9000/api/monitor/plug-test/plug01/off
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:9000/api/monitor/plug-test/plug01/on
```

`{success: true, connected: true}` = plug physically toggled. `{success: false, connected: true}` = broker is up but plug is offline / wrong client_id / wrong topic.

### Live monitoring

```powershell
# Tail broker logs (which plugs connected, when they last reported)
docker logs --tail 100 -f wa-mosquitto

# Subscribe to all plug topics live
docker exec wa-mosquitto sh -c "mosquitto_sub -v -t 'GemeOpen/#'"

# WA-side failure counters
Invoke-RestMethod /api/monitor/plug-status

# Smart plug subsystem health
Invoke-RestMethod /api/monitor/services
# Look for the smart_plug entry — online: true means MQTT connected
```

Full design / wire format / topic conventions: `.agent/plans/SMART_PLUG_SPEC.md`.

## 5. Troubleshooting

| Problem | Check |
|---------|-------|
| Service won't start | `deploy/logs/service_stderr.log` — look for DB connection errors |
| PAS can't reach endpoint | Is CF-Tunnel running? `nssm status CF-Tunnel` or check services.msc |
| 401 on /process-withdrawal | Check `.env` has correct `WA_API_KEY` and `WA_TENANT_ID` |
| 503 on /process-withdrawal | `WA_API_KEY` or `WA_TENANT_ID` is empty in `.env` |
| Arm not responding | Check COM port in Settings, try restart service |
| Camera black/stale | Service restart resets camera; check USB connection |
| Plug doesn't toggle, `connected: false` | Broker (wa-mosquitto) down or WA can't reach `127.0.0.1:1883`. `docker ps` should show `wa-mosquitto`; `docker restart wa-mosquitto` if it crashed |
| Plug doesn't toggle, `connected: true` | Plug is offline or wrong client_id / Wi-Fi / topic. Tail `docker logs wa-mosquitto` for the plug's `connected as <id>` line |
| `plug-test` from another LAN host fails | Firewall rule missing. `netsh advfirewall firewall show rule name="Mosquitto MQTT 1883"` |
| Banner on Settings page shows no host | `/api/monitor/mqtt-broker` returned no LAN IP (multi-homed host, no default route). Use `ipconfig` manually |
