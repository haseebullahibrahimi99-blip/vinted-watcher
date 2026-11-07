@echo off
setlocal
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher - laptop number
echo ==========================================
echo   Share the watching between laptops
echo ==========================================
echo.
echo Use this when the watcher runs on more than one laptop
echo (on DIFFERENT internet connections, e.g. home and shop).
echo Each laptop watches different iPhone models, so there are no duplicate alerts.
echo.
set "TOTAL="
set /p "TOTAL=How many laptops run the watcher in total? (type 1 to undo sharing): "
if "%TOTAL%"=="1" (
  if exist share.txt del share.txt
  echo This laptop will watch ALL models again.
  goto restart
)
set "NUM="
set /p "NUM=Which number is THIS laptop? (e.g. home = 1, shop = 2): "
> share.txt echo %NUM%/%TOTAL%
echo Saved: this is laptop %NUM% of %TOTAL%.

:restart
echo.
echo Restarting the watcher...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'vinted_watch\.py|run_watcher\.bat' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
start "" /min "%~dp0run_watcher.bat"
echo Done. In about 30 seconds, view_log will show which models this laptop watches.
pause
