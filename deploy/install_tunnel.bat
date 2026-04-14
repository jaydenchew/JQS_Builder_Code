@echo off
REM Launcher for install_tunnel.ps1 — Run as Administrator
REM Prerequisites (manual):
REM   1. cloudflared tunnel login
REM   2. cloudflared tunnel create wa-system
REM   3. cloudflared tunnel route dns wa-system wa.evolution-x.io
powershell -ExecutionPolicy Bypass -File "%~dp0install_tunnel.ps1"
pause
