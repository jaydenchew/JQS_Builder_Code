@echo off
REM ============================================================
REM  Cloudflare Tunnel Setup for WA Unified System
REM  Run as Administrator after completing prerequisites below.
REM
REM  Prerequisites (manual, one-time):
REM    1. Install cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
REM    2. Run: cloudflared tunnel login  (authorize in browser)
REM    3. Run: cloudflared tunnel create wa-system  (note the tunnel ID)
REM    4. Run: cloudflared tunnel route dns wa-system wa.evolution-x.io
REM
REM  Then run this script as Administrator.
REM ============================================================

setlocal enabledelayedexpansion

REM --- Configuration ---
set HOSTNAME=wa.evolution-x.io
set SERVICE_NAME=CF-Tunnel
set CF_EXE=C:\Program Files (x86)\cloudflared\cloudflared.exe
set NSSM=%~dp0nssm.exe
set CF_DIR=%USERPROFILE%\.cloudflared

REM --- Check nssm.exe ---
if not exist "%NSSM%" (
    echo ERROR: nssm.exe not found in %~dp0
    echo Download from https://nssm.cc/download and put nssm.exe in deploy/
    pause
    exit /b 1
)

REM --- Check cloudflared ---
if not exist "%CF_EXE%" (
    echo ERROR: cloudflared.exe not found at %CF_EXE%
    echo Download from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/
    pause
    exit /b 1
)

REM --- Check .cloudflared directory ---
if not exist "%CF_DIR%" (
    echo ERROR: %CF_DIR% not found.
    echo Run these commands first:
    echo   cloudflared tunnel login
    echo   cloudflared tunnel create wa-system
    echo   cloudflared tunnel route dns wa-system %HOSTNAME%
    pause
    exit /b 1
)

REM --- Find tunnel credentials JSON ---
set CRED_FILE=
for %%f in ("%CF_DIR%\*.json") do (
    set CRED_FILE=%%f
)
if "%CRED_FILE%"=="" (
    echo ERROR: No tunnel credentials (.json) found in %CF_DIR%
    echo Run: cloudflared tunnel create wa-system
    pause
    exit /b 1
)
echo Found credentials: %CRED_FILE%

REM --- Find tunnel ID from filename ---
for %%f in ("%CRED_FILE%") do set TUNNEL_ID=%%~nf
echo Tunnel ID: %TUNNEL_ID%

REM --- Create config.yml ---
set CONFIG=%CF_DIR%\config.yml
echo Creating %CONFIG%...

(
echo tunnel: %TUNNEL_ID%
echo credentials-file: %CRED_FILE%
echo.
echo ingress:
echo   - hostname: %HOSTNAME%
echo     path: /process-withdrawal
echo     service: http://localhost:9000
echo   - hostname: %HOSTNAME%
echo     path: /status/*
echo     service: http://localhost:9000
echo   - hostname: %HOSTNAME%
echo     path: /health
echo     service: http://localhost:9000
echo   - service: http_status:404
) > "%CONFIG%"

echo Config written:
type "%CONFIG%"
echo.

REM --- Install NSSM service ---
echo Installing %SERVICE_NAME% service...

%NSSM% stop %SERVICE_NAME% >nul 2>&1
%NSSM% remove %SERVICE_NAME% confirm >nul 2>&1

%NSSM% install %SERVICE_NAME% "%CF_EXE%" tunnel --config "%CONFIG%" run %TUNNEL_ID%
%NSSM% set %SERVICE_NAME% DisplayName "Cloudflare Tunnel (WA)"
%NSSM% set %SERVICE_NAME% Description "Cloudflare Tunnel for WA Unified System - routes %HOSTNAME% to localhost:9000"
%NSSM% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM% set %SERVICE_NAME% ObjectName ".\%USERNAME%"

echo.
echo Starting service...
%NSSM% start %SERVICE_NAME%

timeout /t 5 /nobreak >nul

sc query %SERVICE_NAME% | findstr STATE
echo.
echo ============================================================
echo  Cloudflare Tunnel installed as Windows service: %SERVICE_NAME%
echo  Hostname: https://%HOSTNAME%
echo  Config: %CONFIG%
echo.
echo  IMPORTANT: Go to Cloudflare Dashboard:
echo    Security ^> Settings ^> Browser Integrity Check ^> OFF
echo    Security ^> Settings ^> Bot Fight Mode ^> OFF
echo.
echo  Test: curl https://%HOSTNAME%/health
echo ============================================================
pause
