#!/usr/bin/env python3
"""
Vinted new-listing watcher -> instant phone notifications (ntfy and/or Telegram).

Usage:
    python vinted_watch.py          # run the watcher
    python vinted_watch.py --test   # send a test notification and exit
"""
import json
import os
import random
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

try:
    from curl_cffi import requests as http  # impersonates Chrome -> far fewer blocks
    SESSION_KW = {"impersonate": "chrome"}
except ImportError:
    import requests as http
    SESSION_KW = {}

BASE = Path(__file__).parent
CONFIG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
SEEN_FILE = BASE / "seen.json"
# Secrets can come from environment variables (used on GitHub) instead of config.json
if os.environ.get("NTFY_TOPIC"):
    CONFIG["ntfy_topic"] = os.environ["NTFY_TOPIC"]
if os.environ.get("TELEGRAM_BOT_TOKEN"):
    CONFIG["telegram"] = {"bot_token": os.environ["TELEGRAM_BOT_TOKEN"],
                          "chat_id": os.environ.get("TELEGRAM_CHAT_ID", "")}
DOMAIN = CONFIG.get("domain", "www.vinted.co.uk")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


class RateLimited(Exception):
    pass


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


# ---------- turning a browser search URL into API parameters ----------

def url_to_params(search_url):
    """Paste any Vinted search URL from your browser; this converts its filters."""
    q = parse_qs(urlparse(search_url).query)
    params = {}
    for key, vals in q.items():
        if key.endswith("[]"):                       # e.g. catalog[]=..., brand_ids[]=...
            name = key[:-2]
            if name == "catalog":
                name = "catalog_ids"
            params[name] = ",".join(vals)
        elif key in ("search_text", "price_from", "price_to", "currency"):
            params[key] = vals[0]
    params.update(order="newest_first", per_page=CONFIG.get("per_page", 24), page=1)
    return params


# ---------- Vinted client ----------

class Vinted:
    def __init__(self):
        self.new_session()

    def new_session(self):
        self.s = http.Session(**SESSION_KW)
        if not SESSION_KW:  # plain requests: pretend to be a browser
            self.s.headers["User-Agent"] = UA
        self.s.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-GB,en;q=0.9",
        })
        # Visiting the homepage gives us the anonymous cookies the API needs
        r = self.s.get(f"https://{DOMAIN}/", timeout=20)
        log(f"New Vinted session (status {r.status_code})")

    def search(self, params):
        for _ in range(2):
            r = self.s.get(f"https://{DOMAIN}/api/v2/catalog/items",
                           params=params, timeout=20)
            if r.status_code == 200:
                return r.json().get("items", [])
            if r.status_code in (401, 403):
                log(f"Got {r.status_code}, refreshing session")
                time.sleep(5)
                self.new_session()
                continue
            if r.status_code == 429:
                raise RateLimited()
            r.raise_for_status()
        return []


# ---------- item helpers ----------

def price_of(item):
    p = item.get("price")
    if isinstance(p, dict):
        amount, cur = p.get("amount"), p.get("currency_code", "")
    else:
        amount, cur = p, item.get("currency", "")
    return f"{amount} {cur}".strip()


def age_minutes(item):
    """Minutes since the main photo was uploaded (≈ when it was listed)."""
    ts = ((item.get("photo") or {}).get("high_resolution") or {}).get("timestamp")
    return (time.time() - ts) / 60 if ts else None


# ---------- notifications ----------

def notify(search_name, item):
    title = item.get("title", "(no title)")
    price = price_of(item)
    link = item.get("url") or f"https://{DOMAIN}/items/{item['id']}"
    photo = (item.get("photo") or {}).get("url")
    extra = " · ".join(str(x) for x in (item.get("brand_title"),
                                        item.get("size_title"),
                                        item.get("status")) if x)
    text = f"🆕 [{search_name}] {title}\n💷 {price}\n{extra}\n{link}"

    # ntfy (easiest: free app, no account)
    topic = CONFIG.get("ntfy_topic")
    if topic:
        payload = {"topic": topic, "title": f"{search_name}: {price}",
                   "message": f"{title}\n{extra}", "click": link,
                   "priority": 5, "tags": ["iphone"]}
        if photo:
            payload["attach"] = photo
        try:
            http.post("https://ntfy.sh/", json=payload, timeout=15)
        except Exception as e:
            log(f"ntfy failed: {e}")

    # Telegram (optional)
    tg = CONFIG.get("telegram", {})
    if tg.get("bot_token") and tg.get("chat_id"):
        api = f"https://api.telegram.org/bot{tg['bot_token']}"
        try:
            ok = False
            if photo:
                r = http.post(f"{api}/sendPhoto", timeout=15,
                              data={"chat_id": tg["chat_id"], "photo": photo, "caption": text})
                ok = r.status_code == 200
            if not ok:
                http.post(f"{api}/sendMessage", timeout=15,
                          data={"chat_id": tg["chat_id"], "text": text})
        except Exception as e:
            log(f"Telegram failed: {e}")


# ---------- seen-items memory ----------

def load_seen():
    try:
        return set(json.loads(SEEN_FILE.read_text()))
    except Exception:
        return set()


def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)[-5000:]))


# ---------- main loop ----------

def main():
    if "--test" in sys.argv:
        notify("Test", {"id": 0, "title": "iPhone 14 Pro 128GB (test)",
                        "price": {"amount": "299.00", "currency_code": "GBP"},
                        "url": f"https://{DOMAIN}/", "status": "Very good"})
        log("Test notification sent - check your phone.")
        return

    global_excl = [w.lower() for w in CONFIG.get("exclude_words", [])]
    searches = [(s["name"], url_to_params(s["url"]),
                 global_excl + [w.lower() for w in s.get("exclude_words", [])])
                for s in CONFIG["searches"]]
    delay = CONFIG.get("poll_seconds", 60)
    max_age = CONFIG.get("max_age_minutes")
    notify_on_start = CONFIG.get("notify_on_start", False)

    # --minutes N : stop after N minutes (used by the GitHub schedule)
    end_time = None
    if "--minutes" in sys.argv:
        end_time = time.time() + float(sys.argv[sys.argv.index("--minutes") + 1]) * 60

    seen = load_seen()
    # First ever run only records existing items. If we already have history
    # (e.g. restored on GitHub), alert straight away.
    primed = {n for n, _, _ in searches} if seen else set()
    backoff = 0
    v = Vinted()
    log(f"Watching {len(searches)} search(es) every ~{delay}s")

    while end_time is None or time.time() < end_time:
        for name, params, excl in searches:
            try:
                items = v.search(params)
            except RateLimited:
                backoff = min(backoff * 2 or 120, 900)
                log(f"Rate limited by Vinted, pausing {backoff}s")
                time.sleep(backoff)
                continue
            except Exception as e:
                log(f"Error on '{name}': {e}")
                continue
            backoff = 0

            new = [i for i in items if i.get("id") not in seen]
            for item in reversed(new):  # oldest first
                seen.add(item["id"])
                if name not in primed and not notify_on_start:
                    continue
                title = item.get("title", "").lower()
                if any(w in title for w in excl):
                    continue
                age = age_minutes(item)
                if max_age and age is not None and age > max_age:
                    continue  # an old listing that was just bumped
                log(f"NEW [{name}] {item.get('title')} - {price_of(item)}")
                notify(name, item)

            if name not in primed:
                log(f"'{name}': recorded {len(items)} existing listings")
            primed.add(name)
            save_seen(seen)
            time.sleep(random.uniform(2, 5))

        pause = delay + random.uniform(0, delay * 0.3)
        if end_time and time.time() + pause >= end_time:
            break
        time.sleep(pause)
    log("Run finished.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
