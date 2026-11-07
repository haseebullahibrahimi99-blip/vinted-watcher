VINTED WATCHER - LAPTOP VERSION
===============================

SETUP (once)
1. Unzip this folder somewhere permanent, e.g. Documents\VintedWatcher
   (don't run it from inside the zip or from Downloads you might clear).
2. Double-click setup.bat.
   - If Windows shows "Windows protected your PC": click "More info" -> "Run anyway".
   - If it installs Python, close the window and double-click setup.bat again.
3. You should get a test alert on your phone, then "Vinted watcher started".

DAILY USE
- Keep the laptop plugged in and connected to Wi-Fi. The lid can be closed.
- It starts by itself whenever you sign in to Windows.
- view_log.bat    -> see what it's doing right now
- stop_watcher.bat -> stop it
- run_watcher.bat -> start it again without restarting

THREE LAPTOPS (H = home, E and I = shops)
- Set up each laptop the same way (setup.bat), then double-click ONE of:
    this_is_H_laptop.bat  -> watches iPhone 13 and 16
    this_is_E_laptop.bat  -> watches iPhone 14
    this_is_I_laptop.bat  -> watches iPhone 15
- Each laptop must be on its OWN internet connection.
- If the other laptops are off for a while, double-click watch_everything.bat
  on the one that is on.

CHANGING MODELS / PRICES
- Open config.json in Notepad, edit the "models" list, save,
  then run stop_watcher.bat and run_watcher.bat.

IF ALERTS STOP
- Check the laptop is on, awake and online.
- After a Windows update restart you must sign in once - you'll get
  "Vinted watcher started" on your phone when it's running again.
