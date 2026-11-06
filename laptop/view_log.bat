@echo off
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher - live log (close this window any time, the watcher keeps running)
if not exist watcher.log (
  echo No log yet - the watcher has not started. Double-click setup.bat or run_watcher.bat.
  pause
  exit /b
)
powershell -NoProfile -Command "Get-Content -Path (Join-Path (Get-Location) "watcher.log") -Tail 40 -Wait -Encoding UTF8"
