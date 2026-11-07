@echo off
setlocal
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher - E laptop
> share.txt echo E
echo This is now the E laptop. It watches: iPhone 14.
echo.
echo Restarting the watcher...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vinted_watch\.py|run_watcher\.bat' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
start "" /min "%~dp0run_watcher.bat"
echo Done. You'll get "Vinted watcher started (E laptop)" on your phone in about 30 seconds.
pause
