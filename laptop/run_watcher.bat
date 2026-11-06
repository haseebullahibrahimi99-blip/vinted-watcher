@echo off
setlocal
cd /d "%~dp0"
title Vinted Watcher (keep this window open - minimise it)
set "PYTHONIOENCODING=utf-8"
set "PY=py -3"
py -3 --version >nul 2>&1 || set "PY=python"

rem Wait a little after sign-in so Wi-Fi is connected
timeout /t 20 /nobreak >nul

set "TOPIC="
for /f "usebackq delims=" %%T in (`%PY% -c "import json;print(json.load(open('config.json',encoding='utf-8')).get('ntfy_topic',''))"`) do set "TOPIC=%%T"
if defined TOPIC curl -s -H "Title: Vinted watcher started" -H "Tags: white_check_mark" -d "Watching Vinted UK from your laptop." "https://ntfy.sh/%TOPIC%" >nul 2>&1

:loop
echo %date% %time% === watcher starting === >> watcher.log
echo Vinted Watcher is running. Minimise this window - do not close it.
%PY% vinted_watch.py >> watcher.log 2>&1
echo %date% %time% === watcher stopped - restarting in 30 seconds === >> watcher.log
timeout /t 30 /nobreak >nul
goto loop
