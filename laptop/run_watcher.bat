@echo off
setlocal
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher (keep this window open - minimise it)
set "PYTHONIOENCODING=utf-8"
set "PY=py -3"
py -3 --version >nul 2>&1 || set "PY=python"
set "CODE_URL=https://raw.githubusercontent.com/haseebullahibrahimi99-blip/vinted-watcher/main/vinted_watch.py"

rem Wait a little after sign-in so Wi-Fi is connected
timeout /t 20 /nobreak >nul

set "TOPIC="
for /f "usebackq delims=" %%T in (`%PY% -c "import json;print(json.load(open('config.json',encoding='utf-8')).get('ntfy_topic',''))"`) do set "TOPIC=%%T"
set "WHO=laptop"
if exist share.txt set /p WHO=<share.txt
if exist share.txt set "WHO=%WHO: =% laptop"
if defined TOPIC curl -s -H "Title: Vinted watcher started (%WHO%)" -H "Tags: white_check_mark" -d "Watching Vinted UK from the %WHO%." "https://ntfy.sh/%TOPIC%" >nul 2>&1

:loop
rem Keep the log from growing forever
for %%A in (watcher.log) do if %%~zA GTR 5000000 move /y watcher.log watcher.old.log >nul

rem Get the newest watcher code from GitHub (only used if it downloads cleanly)
curl -fsSL -o vinted_watch.new "%CODE_URL%" >nul 2>&1
if exist vinted_watch.new (
  %PY% -c "import ast,sys;ast.parse(open(sys.argv[1],encoding='utf-8').read())" vinted_watch.new >nul 2>&1 && (
    fc /b vinted_watch.new vinted_watch.py >nul 2>&1 || echo %date% %time% === updated watcher code from GitHub === >> watcher.log
    move /y vinted_watch.new vinted_watch.py >nul
  ) || del vinted_watch.new
)

echo %date% %time% === watcher starting === >> watcher.log
echo Vinted Watcher is running. Minimise this window - do not close it.
rem Restarts every 6 hours to pick up any updates
%PY% vinted_watch.py --minutes 360 >> watcher.log 2>&1
echo %date% %time% === watcher restarting in 10 seconds === >> watcher.log
timeout /t 10 /nobreak >nul
goto loop
