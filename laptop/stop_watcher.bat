@echo off
echo Stopping the Vinted Watcher...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vinted_watch\.py|run_watcher\.bat' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
echo Stopped. It will start again next time you sign in.
echo (To start it now without restarting, double-click run_watcher.bat.)
pause
