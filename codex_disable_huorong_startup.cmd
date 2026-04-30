@echo off
setlocal
set LOG=%TEMP%\codex_disable_huorong_startup.log
echo [%date% %time%] begin>"%LOG%"

echo [1] stop HipsTray>>"%LOG%"
taskkill /IM HipsTray.exe /F>>"%LOG%" 2>&1

echo [2] stop HipsDaemon>>"%LOG%"
sc stop HipsDaemon>>"%LOG%" 2>&1

echo [3] disable HipsDaemon service startup>>"%LOG%"
sc config HipsDaemon start= disabled>>"%LOG%" 2>&1

echo [4] delete HKLM Run Sysdiag>>"%LOG%"
reg delete "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v Sysdiag /f>>"%LOG%" 2>&1

echo [5] disable StartupApproved Sysdiag>>"%LOG%"
reg add "HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v Sysdiag /t REG_BINARY /d 030000000000000000000000 /f>>"%LOG%" 2>&1

echo [6] query results>>"%LOG%"
reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\Run" /v Sysdiag>>"%LOG%" 2>&1
reg query "HKLM\Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run" /v Sysdiag>>"%LOG%" 2>&1
sc qc HipsDaemon>>"%LOG%" 2>&1
sc query HipsDaemon>>"%LOG%" 2>&1

echo [%date% %time%] end>>"%LOG%"
type "%LOG%"
endlocal
