@echo off
setlocal
cd /d "%~dp0"
if not exist vinted_watch.py if exist ..\vinted_watch.py cd ..
title Vinted Watcher - setup
echo ==========================================
echo   Vinted Watcher - one-time laptop setup
echo ==========================================
echo.

rem ---------- 1. Python ----------
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY python --version >nul 2>&1 && set "PY=python"
if defined PY goto have_python

echo [1/5] Python is not installed - installing it now (this can take a few minutes)...
winget install -e --id Python.Python.3.12 --source winget --scope user --accept-package-agreements --accept-source-agreements
if errorlevel 1 goto python_manual
echo.
echo Python is installed. CLOSE this window and double-click setup.bat again.
pause
exit /b 0

:python_manual
echo.
echo Could not install Python automatically.
echo Opening python.org - download it, and TICK "Add Python to PATH" when installing.
echo Then double-click setup.bat again.
start "" https://www.python.org/downloads/
pause
exit /b 1

:have_python
echo [1/5] Python found.

rem ---------- 2. Packages ----------
echo [2/5] Installing the packages the watcher needs...
%PY% -m pip install --upgrade --quiet curl_cffi requests
if errorlevel 1 (
  echo Package install failed. Check the laptop is online and run setup.bat again.
  pause
  exit /b 1
)

rem ---------- 3. ntfy topic ----------
set "TOPIC="
for /f "usebackq delims=" %%T in (`%PY% -c "import json;print(json.load(open('config.json',encoding='utf-8')).get('ntfy_topic',''))"`) do set "TOPIC=%%T"
if defined TOPIC goto have_topic
echo.
set /p "TOPIC=Type your ntfy topic name (the one in your ntfy app) and press Enter: "
%PY% -c "import json,sys;p='config.json';c=json.load(open(p,encoding='utf-8'));c['ntfy_topic']=sys.argv[1];json.dump(c,open(p,'w',encoding='utf-8'),indent=2,ensure_ascii=False)" "%TOPIC%"
:have_topic
echo [3/5] Alerts will go to ntfy topic: %TOPIC%

rem ---------- 4. Keep the laptop awake when plugged in ----------
echo [4/5] Setting the laptop to never sleep while plugged in...
powercfg /change standby-timeout-ac 0 >nul
powercfg /change hibernate-timeout-ac 0 >nul
powercfg /change monitor-timeout-ac 5 >nul
rem Closing the lid does nothing when plugged in
powercfg /setacvalueindex SCHEME_CURRENT SUB_BUTTONS LIDACTION 0 >nul 2>&1
powercfg /setactive SCHEME_CURRENT >nul 2>&1

rem ---------- 5. Start automatically ----------
echo [5/5] Making the watcher start every time you sign in...
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%STARTUP%\Vinted Watcher.bat" echo @start "" /min "%~dp0run_watcher.bat"

echo.
echo Sending a test alert to your phone...
set "PYTHONIOENCODING=utf-8"
%PY% vinted_watch.py --test

echo.
echo Starting the watcher now (a small minimised window called "Vinted Watcher").
start "" /min "%~dp0run_watcher.bat"

echo.
echo ==========================================
echo   Done! Keep the laptop plugged in.
echo   - view_log.bat  : see what it's doing
echo   - stop_watcher.bat : stop it
echo ==========================================
pause
