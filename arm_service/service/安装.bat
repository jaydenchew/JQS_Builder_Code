C:\Windows\Microsoft.NET\Framework\v4.0.30319\InstallUtil.exe %~dp0WindowsService1.exe
sc failure JxbService reset=0 actions=restart/5
net start JxbService
pause
