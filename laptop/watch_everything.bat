@echo off
setlocal
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher - watch everything
if exist share.txt del share.txt
echo This laptop will now watch ALL models by itself (use this if the other laptops are off).
echo.
echo Restarting the watcher...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vinted_watch\.py|run_watcher\.bat' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
start "" /min "%~dp0run_watcher.bat"
echo Done. You'll get "Vinted watcher started" on your phone in about 30 seconds.
pause
