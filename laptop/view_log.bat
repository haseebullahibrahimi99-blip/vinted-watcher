@echo off
cd /d "%~dp0"
title Vinted Watcher - live log (close this window any time, the watcher keeps running)
if not exist watcher.log (
  echo No log yet - the watcher has not started. Double-click setup.bat or run_watcher.bat.
  pause
  exit /b
)
powershell -NoProfile -Command "Get-Content -Path 'watcher.log' -Tail 40 -Wait -Encoding UTF8"
