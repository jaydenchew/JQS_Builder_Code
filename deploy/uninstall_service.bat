@echo off
:: Uninstall WA Unified System Windows Service
:: Run as Administrator

set SERVICE_NAME=WA-Unified
set NSSM=%~dp0nssm.exe

echo Stopping service...
%NSSM% stop %SERVICE_NAME%

echo Removing service...
%NSSM% remove %SERVICE_NAME% confirm

echo.
echo Service "%SERVICE_NAME%" removed.
pause
