@echo off
:: Install WA Unified System as Windows Service using NSSM
:: *** Run as Administrator ***
::
:: Uses project venv so Local System sees uvicorn (not your per-user site-packages).

set SERVICE_NAME=WA-Unified
set APP_DIR=%~dp0..
set NSSM=%~dp0nssm.exe
set BASE_PY=C:\Program Files\Python311\python.exe
set "VENV_PY=%APP_DIR%\venv\Scripts\python.exe"

echo ============================================
echo  WA Unified System - Service Install
echo ============================================

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Run this script as Administrator!
    echo Right-click - Run as Administrator
    pause
    exit /b 1
)

if not exist "%NSSM%" (
    echo ERROR: nssm.exe not found at %NSSM%
    pause
    exit /b 1
)
if not exist "%BASE_PY%" (
    echo ERROR: Python not found at %BASE_PY%
    echo Edit BASE_PY in this script to your python.exe path
    pause
    exit /b 1
)

echo App dir: %APP_DIR%
echo Base Python: %BASE_PY%

if not exist "%VENV_PY%" (
    echo Creating venv...
    "%BASE_PY%" -m venv "%APP_DIR%\venv"
    if errorlevel 1 (
        echo ERROR: Failed to create venv.
        pause
        exit /b 1
    )
)

:: Install VC++ x64 Redistributable first — required by PyTorch (EasyOCR dependency).
:: Without it, importing torch raises WinError 126 (c10.dll not found) and
:: OCR steps fail at runtime. The x86 version (arm_service\VC_redist.x86.exe)
:: satisfies the WCF arm service DLL but NOT PyTorch which is 64-bit.
echo Installing VC++ x64 Redistributable (required by PyTorch/EasyOCR)...
set "VC_X64=%APP_DIR%\arm_service\VC_redist.x64.exe"
if exist "%VC_X64%" (
    "%VC_X64%" /quiet /norestart
    echo VC++ x64 installed.
) else (
    echo WARNING: arm_service\VC_redist.x64.exe not found.
    echo Downloading from Microsoft...
    powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vc_redist.x64.exe' -OutFile '%VC_X64%'"
    if exist "%VC_X64%" (
        "%VC_X64%" /quiet /norestart
        echo VC++ x64 downloaded and installed.
    ) else (
        echo ERROR: Could not download VC++ x64. Install manually from:
        echo   https://aka.ms/vs/17/release/vc_redist.x64.exe
        echo Then re-run this script.
        pause
        exit /b 1
    )
)

echo Updating venv dependencies...
"%VENV_PY%" -m pip install -q --upgrade pip
"%VENV_PY%" -m pip install -q -r "%APP_DIR%\requirements.txt"
if errorlevel 1 (
    echo ERROR: pip install failed.
    pause
    exit /b 1
)

:: Verify torch loads correctly before proceeding.
echo Verifying PyTorch installation...
"%VENV_PY%" -c "import torch; print('PyTorch OK:', torch.__version__)"
if errorlevel 1 (
    echo ERROR: PyTorch failed to load. This is usually caused by missing VC++ x64.
    echo The script already attempted to install it above. Try rebooting and re-running.
    pause
    exit /b 1
)

:: Pre-download EasyOCR models into project-local directory (not user home)
set "MODEL_DIR=%APP_DIR%\models"
if not exist "%MODEL_DIR%" mkdir "%MODEL_DIR%"
echo Pre-downloading EasyOCR models to %MODEL_DIR% ...
set PYTHONIOENCODING=utf-8
"%VENV_PY%" -c "import easyocr; easyocr.Reader(['en'], gpu=False, model_storage_directory=r'%MODEL_DIR%'); print('EasyOCR models OK')"
echo Service Python: %VENV_PY%

%NSSM% stop %SERVICE_NAME% >nul 2>&1
%NSSM% remove %SERVICE_NAME% confirm >nul 2>&1

%NSSM% install %SERVICE_NAME% "%VENV_PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 9000
%NSSM% set %SERVICE_NAME% AppDirectory "%APP_DIR%"
%NSSM% set %SERVICE_NAME% DisplayName "WA Unified System"
%NSSM% set %SERVICE_NAME% Description "Withdrawal Automation - Builder + Multi-Arm Workers"
%NSSM% set %SERVICE_NAME% Start SERVICE_AUTO_START
%NSSM% set %SERVICE_NAME% AppStdout "%APP_DIR%\deploy\logs\service_stdout.log"
%NSSM% set %SERVICE_NAME% AppStderr "%APP_DIR%\deploy\logs\service_stderr.log"
%NSSM% set %SERVICE_NAME% AppRotateFiles 1
%NSSM% set %SERVICE_NAME% AppRotateOnline 1
%NSSM% set %SERVICE_NAME% AppRotateSeconds 86400
%NSSM% set %SERVICE_NAME% AppRotateBytes 10485760
%NSSM% set %SERVICE_NAME% AppEnvironmentExtra PYTHONIOENCODING=utf-8

if not exist "%APP_DIR%\deploy\logs" mkdir "%APP_DIR%\deploy\logs"

%NSSM% start %SERVICE_NAME%

echo.
echo ============================================
echo  Service "%SERVICE_NAME%" installed and started!
echo  Logs: deploy\logs\
echo  Manage: services.msc
echo ============================================
pause
