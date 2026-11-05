# Vinted Watcher

Checks your Vinted searches about once a minute and sends an instant phone alert
(with photo, price and a tap-to-open link) the moment a new listing appears.

## Setup (10 minutes)

1. **Install Python 3.9+**, then in a terminal:
   ```
   pip install curl_cffi
   ```
   (`curl_cffi` makes requests look like Chrome so Vinted blocks you less. If it won't
   install, `pip install requests` works too.)

2. **Phone alerts – easiest option: ntfy (free, no account)**
   - Install the **ntfy** app (iOS / Android).
   - Tap **+**, subscribe to the same topic name as `ntfy_topic` in `config.json`.
   - Change that topic to something random – anyone who knows the name can read it.
   - On iPhone, allow notifications for ntfy.

   **Optional: Telegram** – message @BotFather → `/newbot` → copy the token.
   Send your bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": ...}`.
   Put both in `config.json`.

3. **Add your searches**
   On vinted.co.uk, set up the search exactly how you want it (keywords, category,
   brand, condition, max price), then copy the URL from the address bar into
   `config.json` under `searches`. Add as many as you like.

4. **Test, then run**
   ```
   python vinted_watch.py --test
   python vinted_watch.py
   ```
   The first pass just records what's already listed; after that, only genuinely
   new items alert you.

## Settings

| Setting | What it does |
|---|---|
| `poll_seconds` | How often each round runs. Keep ≥ 45 or Vinted may rate-limit you. |
| `max_age_minutes` | Ignore "new to you" items that are actually old listings being bumped. |
| `exclude_words` | Skip titles containing these (global, or per search). |
| `notify_on_start` | `true` = alert for everything on the very first pass too. |

## Keeping it running 24/7

It only works while it's running. Options:
- Leave it running on a PC/laptop that doesn't sleep.
- A Raspberry Pi at home.
- A cheap VPS (~£4/month, e.g. Hetzner) – run it inside `screen` or as a systemd service.

## Good to know

- Vinted has no public API; this uses the same endpoint their website uses. If Vinted
  changes it, the script may need a small tweak.
- It never logs into your account, so your account isn't at risk – worst case your IP
  gets temporarily blocked if you poll too aggressively. Vinted's terms discourage
  automated access, so keep it gentle and for your own use.
- If you see repeated 403 errors, install `curl_cffi`, slow `poll_seconds` down, or
  run it from a different network.
