# Deployment — NSSM Windows Service

## Setup

1. Download NSSM from https://nssm.cc/download
2. Extract `nssm.exe` (64-bit) into this `deploy/` folder
3. Run `install_service.bat` **as Administrator**

## Manage

| Action | Command |
|--------|---------|
| Start | `nssm start WA-Unified` |
| Stop | `nssm stop WA-Unified` |
| Restart | `nssm restart WA-Unified` |
| Edit config | `nssm edit WA-Unified` |
| View status | `nssm status WA-Unified` |
| Open GUI | `services.msc` → find "WA Unified System" |

## Logs

Service stdout/stderr: `deploy/logs/service_stdout.log` and `service_stderr.log`
Auto-rotated at 10MB.

## Uninstall

Run `uninstall_service.bat` as Administrator.
