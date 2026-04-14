# Arm WCF Service

Windows Service that controls the mechanical arm via HTTP API.
Must be installed and running before the WA system can operate.

## Install

1. Install VC++ Redistributable (if not already): run `VC_redist.x86.exe`
2. Install the service: **right-click** `service/安装.bat` → **Run as Administrator**
3. The service starts automatically and listens on `http://127.0.0.1:8082/MyWcfService/getstring`

## Uninstall

Right-click `service/卸载.bat` → Run as Administrator

## Verify

Open browser: `http://127.0.0.1:8082/MyWcfService/getstring?duankou=COM6&hco=0&daima=0`
- If service is running, you'll get a response (resource number or error)
- If not running, connection refused

## API

```
GET http://127.0.0.1:8082/MyWcfService/getstring?duankou={COM}&hco={resource}&daima={command}
```

| Call | duankou | hco | daima | Purpose |
|------|---------|-----|-------|---------|
| Open port | COM6 | 0 | 0 | Returns resource number |
| Move | 0 | {resource} | x50y60 | Move to position |
| Press | 0 | {resource} | z10 | Press pen down |
| Lift | 0 | {resource} | z0 | Lift pen |
| Close | 0 | {resource} | 0 | Close port |

## Files

```
arm_service/
├── VC_redist.x86.exe       VC++ runtime (install first if needed)
├── service/
│   ├── WindowsService1.exe  The WCF service executable
│   ├── Dll1.dll             Arm control library
│   ├── 安装.bat              Install script (run as admin)
│   └── 卸载.bat              Uninstall script (run as admin)
└── examples/                API call examples in various languages
```
