# ============================================================
#  Cloudflare Tunnel Setup for WA Unified System
#  Run as Administrator (via install_tunnel.bat)
#
#  Prerequisites (manual, one-time):
#    1. cloudflared tunnel login       (authorize in browser)
#    2. cloudflared tunnel create wa-system
#    3. cloudflared tunnel route dns wa-system wa.evolution-x.io
#
#  For additional machines (e.g., wa2 / wa3 on separate hardware):
#    - Change $HOSTNAME below (e.g., "wa2.evolution-x.io")
#    - Use a distinct tunnel name in the commands above (e.g., wa2-system)
#    - If the hostname was previously routed to another tunnel,
#      append --overwrite-dns to step 3
#    - See deploy/README.md section "Multi-machine deployment"
# ============================================================

$ErrorActionPreference = "Stop"
$HOSTNAME = "wa.evolution-x.io"
$SERVICE_NAME = "CF-Tunnel"
$CF_EXE = (Get-Command cloudflared -ErrorAction SilentlyContinue).Source
if (-not $CF_EXE) {
    foreach ($p in @(
        "C:\Program Files\cloudflared\cloudflared.exe",
        "C:\Program Files (x86)\cloudflared\cloudflared.exe"
    )) {
        if (Test-Path $p) { $CF_EXE = $p; break }
    }
}
$NSSM = Join-Path $PSScriptRoot "nssm.exe"
$CF_DIR = Join-Path $env:USERPROFILE ".cloudflared"

# --- Checks ---
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).
    IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: Administrator access is required." -ForegroundColor Red
    Write-Host "Please right-click install_tunnel.bat and choose 'Run as Administrator'."
    exit 1
}
if (-not (Test-Path $NSSM)) {
    Write-Host "ERROR: nssm.exe not found at $NSSM" -ForegroundColor Red
    Write-Host "Download from https://nssm.cc/download and put in deploy/"
    exit 1
}
if (-not (Test-Path $CF_EXE)) {
    Write-Host "ERROR: cloudflared.exe not found at $CF_EXE" -ForegroundColor Red
    Write-Host "Download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    exit 1
}
if (-not (Test-Path $CF_DIR)) {
    Write-Host "ERROR: $CF_DIR not found." -ForegroundColor Red
    Write-Host "Run these commands first:"
    Write-Host "  cloudflared tunnel login"
    Write-Host "  cloudflared tunnel create wa-system"
    Write-Host "  cloudflared tunnel route dns wa-system $HOSTNAME"
    exit 1
}

# --- Find credentials JSON ---
$jsonFiles = Get-ChildItem "$CF_DIR\*.json" -ErrorAction SilentlyContinue
if ($jsonFiles.Count -eq 0) {
    Write-Host "ERROR: No tunnel credentials (.json) found in $CF_DIR" -ForegroundColor Red
    Write-Host "Run: cloudflared tunnel create wa-system"
    exit 1
}
$credFile = $jsonFiles[0].FullName
$tunnelId = $jsonFiles[0].BaseName
Write-Host "Credentials: $credFile"
Write-Host "Tunnel ID:   $tunnelId"

# --- Create config.yml ---
$configPath = Join-Path $CF_DIR "config.yml"
$configContent = @"
tunnel: $tunnelId
credentials-file: $credFile

ingress:
  - hostname: $HOSTNAME
    path: /process-withdrawal
    service: http://localhost:9000
  - hostname: $HOSTNAME
    path: /status/*
    service: http://localhost:9000
  - hostname: $HOSTNAME
    path: /health
    service: http://localhost:9000
  - hostname: $HOSTNAME
    path: /api/monitor/export/daily-summary
    service: http://localhost:9000
  - service: http_status:404
"@

[System.IO.File]::WriteAllText($configPath, $configContent, [System.Text.Encoding]::UTF8)
Write-Host "`nConfig written to: $configPath" -ForegroundColor Green
Write-Host $configContent
Write-Host ""

# --- Install NSSM service ---
Write-Host "Installing service: $SERVICE_NAME ..." -ForegroundColor Cyan

# On first install, service may not exist yet. Skip stop/remove in that case
# (original script always ran them and spewed "Can't open service!" as red noise).
$existingService = Get-Service -Name $SERVICE_NAME -ErrorAction SilentlyContinue
if ($existingService) {
    # nssm stop returns error when already stopped, so stop only when running.
    if ($existingService.Status -eq "Running") {
        & $NSSM stop $SERVICE_NAME 2>$null | Out-Null
    } else {
        Write-Host "Existing service is not running, skip stop." -ForegroundColor DarkGray
    }
    & $NSSM remove $SERVICE_NAME confirm 2>$null | Out-Null
} else {
    Write-Host "Service not installed yet, proceeding with fresh install." -ForegroundColor DarkGray
}

& $NSSM install $SERVICE_NAME "`"$CF_EXE`"" tunnel --config "`"$configPath`"" run $tunnelId
if ($LASTEXITCODE -ne 0) {
    throw "NSSM install failed. Please verify admin permissions and nssm.exe."
}
& $NSSM set $SERVICE_NAME DisplayName "Cloudflare Tunnel (WA)"
& $NSSM set $SERVICE_NAME Description "Routes https://$HOSTNAME to localhost:9000"
& $NSSM set $SERVICE_NAME Start SERVICE_AUTO_START
& $NSSM set $SERVICE_NAME ObjectName ".\$env:USERNAME"

Write-Host "`nStarting service..." -ForegroundColor Cyan
& $NSSM start $SERVICE_NAME
if ($LASTEXITCODE -ne 0) {
    throw "NSSM start failed. Check service account/password permissions."
}
Start-Sleep 5

$state = (sc.exe query $SERVICE_NAME | Select-String "STATE").ToString().Trim()
if ($state -notmatch "RUNNING") {
    throw "Service did not reach RUNNING state. Current state: $state"
}
Write-Host "`nService status: $state"

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "  Cloudflare Tunnel installed: $SERVICE_NAME"
Write-Host "  URL: https://$HOSTNAME"
Write-Host "  Config: $configPath"
Write-Host ""
Write-Host "  IMPORTANT - Cloudflare Dashboard settings:" -ForegroundColor Yellow
Write-Host "    Security > Settings > Browser Integrity Check > OFF"
Write-Host "    Security > Settings > Bot Fight Mode > OFF"
Write-Host ""
Write-Host "  Test: curl https://$HOSTNAME/health"
Write-Host "============================================================" -ForegroundColor Green
