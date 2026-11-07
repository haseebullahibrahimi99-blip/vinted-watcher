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
import re
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

API_HOST = DOMAIN.replace("www.", "api.", 1)   # www.vinted.co.uk -> api.vinted.co.uk

# Old filter names -> names used by Vinted's new (Sept 2026) catalogue API
ATTR_MAP = {"catalog_ids": "catalog", "status_ids": "status", "brand_ids": "brand",
            "size_ids": "size", "color_ids": "color", "material_ids": "material"}


def to_new_params(params):
    out = {}
    for k, v in params.items():
        if v in (None, ""):
            continue                      # the new API rejects empty filters
        out[f"attribute_ids[{ATTR_MAP[k]}]" if k in ATTR_MAP else k] = v
    return out


def find_item_list(data):
    """Find the list of listings inside any JSON shape."""
    if isinstance(data, list):
        if data and all(isinstance(x, dict) for x in data) and \
                any(("id" in x or "item_id" in x) for x in data):
            return data
        for x in data:
            found = find_item_list(x)
            if found:
                return found
    elif isinstance(data, dict):
        for key in ("items", "data", "results", "catalog_items"):
            if key in data:
                found = find_item_list(data[key])
                if found:
                    return found
        for v in data.values():
            if isinstance(v, (list, dict)):
                found = find_item_list(v)
                if found:
                    return found
    return None


def absolute(url):
    if not url:
        return None
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return f"https://{DOMAIN}{url}"
    return url


def normalize(i):
    """Turn a listing from any Vinted format into one standard shape."""
    box = i.get("item_box") or {}
    photo = i.get("photo")
    if not isinstance(photo, dict):
        photos = i.get("photos") or []
        photo = photos[0] if photos and isinstance(photos[0], dict) else {}
    img = photo.get("url") or i.get("image") or i.get("thumbnail") or i.get("image_url")
    if isinstance(img, list):
        img = img[0] if img else None
    if isinstance(img, dict):
        img = img.get("url")
    item_id = i.get("id") or i.get("item_id")
    title = i.get("title") or i.get("name") or box.get("first_line") or "(no title)"
    return {
        "id": str(item_id),
        "title": title,
        "price": i.get("price") or i.get("total_item_price"),
        "currency": i.get("currency"),
        "url": absolute(i.get("url") or i.get("path")) or f"https://{DOMAIN}/items/{item_id}",
        "photo": {"url": absolute(img), "high_resolution": photo.get("high_resolution")},
        "brand_title": i.get("brand_title") or (box.get("first_line") if box.get("first_line") != title else None),
        "size_title": i.get("size_title") or box.get("second_line"),
        "status": i.get("status") if isinstance(i.get("status"), str) else None,
        "user": i.get("user") if isinstance(i.get("user"), dict)
                else i.get("seller") if isinstance(i.get("seller"), dict)
                else {"id": i.get("user_id") or i.get("seller_id")},
    }


def parse_ld_json(html):
    """Backup method: read listings embedded in the normal catalogue web page."""
    items = []
    for block in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block)
        except Exception:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
                continue
            if not isinstance(d, dict):
                continue
            if d.get("@type") == "ItemList":
                for el in d.get("itemListElement", []):
                    prod = el.get("item", el) if isinstance(el, dict) else {}
                    url = prod.get("url") or el.get("url", "")
                    m = re.search(r"/items/(\d+)", url or "")
                    if not m:
                        continue
                    offers = prod.get("offers") or {}
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    items.append(normalize({
                        "id": m.group(1), "title": prod.get("name"), "url": url,
                        "image": prod.get("image"),
                        "price": offers.get("price"), "currency": offers.get("priceCurrency"),
                    }))
            else:
                stack.extend(v for v in d.values() if isinstance(v, (list, dict)))
    return items


class Vinted:
    def __init__(self):
        self.method_logged = False
        self.new_session()

    def new_session(self):
        self.s = http.Session(**SESSION_KW)
        if not SESSION_KW:  # plain requests: pretend to be a browser
            self.s.headers["User-Agent"] = UA
        self.s.headers.update({"Accept-Language": "en-GB,en;q=0.9"})
        # Visiting the homepage gives us the anonymous token the API needs
        r = self.s.get(f"https://{DOMAIN}/", timeout=20)
        self.token = self.cookie("access_token_web")
        self.anon = r.headers.get("x-anon-id") or self.cookie("anon_id")
        m = re.search(r'"CSRF_TOKEN\\?"\s*:\s*\\?"([^"\\]+)', r.text or "") or \
            re.search(r'name="csrf-token"\s+content="([^"]+)"', r.text or "")
        self.csrf = m.group(1) if m else None
        log(f"New Vinted session (status {r.status_code}, token {'yes' if self.token else 'no'})")

    def cookie(self, name):
        try:
            for c in self.s.cookies.jar:
                if c.name == name:
                    return c.value
        except Exception:
            pass
        try:
            return self.s.cookies.get(name)
        except Exception:
            return None

    def api_headers(self):
        h = {"Accept": "application/json, text/plain, */*",
             "Origin": f"https://{DOMAIN}", "Referer": f"https://{DOMAIN}/catalog"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        if self.anon:
            h["X-Anon-Id"] = self.anon
        if self.csrf:
            h["X-Csrf-Token"] = self.csrf
        return h

    # ----- seller reviews -----
    REVIEW_RES = [re.compile(p) for p in (
        r'\\?"feedback_count\\?"\s*:\s*(\d+)',
        r'\\?"reviews_count\\?"\s*:\s*(\d+)',
        r'"reviewCount"\s*:\s*"?(\d+)',
    )]

    def seller_reviews(self, item):
        """Number of reviews the seller has, or None if it can't be found."""
        u = item.get("user") or {}
        for k in ("feedback_count", "reviews_count"):
            if isinstance(u.get(k), int):
                return u[k]
        uid = u.get("id")
        cache = self.__dict__.setdefault("review_cache", {})
        key = uid or f"item{item['id']}"
        if key in cache:
            return cache[key]
        count = None
        # 1) seller profile API
        if uid:
            try:
                r = self.s.get(f"https://{DOMAIN}/api/v2/users/{uid}",
                               headers=self.api_headers(), timeout=20)
                if r.status_code == 200:
                    d = r.json()
                    d = d.get("user", d)
                    for k in ("feedback_count", "reviews_count"):
                        if isinstance(d.get(k), int):
                            count = d[k]
                            break
            except Exception:
                pass
        # 2) the listing / profile web page (seller info is embedded in it)
        pages = [item.get("url")] + ([f"https://{DOMAIN}/member/{uid}"] if uid else [])
        for page in pages:
            if count is not None or not page:
                break
            try:
                r = self.s.get(page, headers={"Accept": "text/html"}, timeout=20)
                if r.status_code == 200:
                    for rx in self.REVIEW_RES:
                        m = rx.search(r.text)
                        if m:
                            count = int(m.group(1))
                            break
            except Exception:
                pass
        cache[key] = count
        return count

    def used(self, how):
        if not self.method_logged:
            log(f"Getting listings via: {how}")
            self.method_logged = True

    def search(self, params):
        # 1) New catalogue API (Sept 2026)
        for _ in range(3):
            r = self.s.get(f"https://{API_HOST}/svc-catalogue/items",
                           params=to_new_params(params), headers=self.api_headers(), timeout=20)
            if r.status_code == 200:
                items = find_item_list(r.json())
                if items is not None:
                    self.used("new API")
                    return [normalize(i) for i in items]
                log(f"New API answered but no items found. Keys: {list(r.json())[:10]}")
                break
            if r.status_code in (401, 403):
                log(f"New API {r.status_code}, refreshing session")
                time.sleep(5)
                self.new_session()
                continue
            if r.status_code == 429:
                raise RateLimited()
            log(f"New API {r.status_code}: {r.text[:200]!r}")
            break

        # 2) Old API (in case it comes back)
        r = self.s.get(f"https://{DOMAIN}/api/v2/catalog/items", params=params,
                       headers=self.api_headers(), timeout=20)
        if r.status_code == 200:
            self.used("old API")
            return [normalize(i) for i in r.json().get("items", [])]
        if r.status_code == 429:
            raise RateLimited()

        # 3) Normal catalogue web page
        page_params = {k: v for k, v in params.items()
                       if k in ("search_text", "order", "price_from", "price_to", "currency")}
        r = self.s.get(f"https://{DOMAIN}/catalog", params=page_params,
                       headers={"Accept": "text/html"}, timeout=20)
        if r.status_code == 429:
            raise RateLimited()
        items = parse_ld_json(r.text) if r.status_code == 200 else []
        if items:
            self.used("catalogue web page")
            return items
        raise RuntimeError(f"all methods failed (web page status {r.status_code})")


# ---------- item helpers ----------

# Vinted shows prices in the server's local currency (GitHub's servers are in
# the US, so USD). Approximate rates to turn them back into pounds.
TO_GBP = {"GBP": 1.0, "USD": CONFIG.get("usd_to_gbp", 0.77), "EUR": CONFIG.get("eur_to_gbp", 0.86)}


def raw_price(item):
    p = item.get("price")
    if isinstance(p, dict):
        amount = p.get("amount") or p.get("value")
        cur = p.get("currency_code") or p.get("currency") or ""
    else:
        amount, cur = p, item.get("currency") or ""
    try:
        amount = float(str(amount).replace(",", "."))
    except (TypeError, ValueError):
        amount = None
    return amount, (cur or "GBP").upper()


def gbp_of(item):
    amount, cur = raw_price(item)
    if amount is None or cur not in TO_GBP:
        return amount
    return amount * TO_GBP[cur]


def price_of(item):
    amount, cur = raw_price(item)
    if amount is None:
        return "price n/a"
    if cur == "GBP":
        return f"£{amount:g}" if amount == int(amount) else f"£{amount:.2f}"
    gbp = gbp_of(item)
    sym = {"USD": "$", "EUR": "€"}.get(cur, cur + " ")
    return f"≈£{gbp:.0f} ({sym}{amount:g})"


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
            r = http.post("https://ntfy.sh/", json=payload, timeout=15)
            if r.status_code != 200:
                log(f"ntfy refused ({r.status_code}): {r.text[:150]!r}")
                if "attach" in payload:          # retry without the photo
                    payload.pop("attach")
                    r = http.post("https://ntfy.sh/", json=payload, timeout=15)
                    log(f"ntfy retry without photo: {r.status_code}")
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


# ---------- accessory filter ----------

# "128GB", "256 gb", "1TB" -> almost always a real device, not an accessory
STORAGE_RE = re.compile(r"(?<!\d)\d{2,4}\s?(gb|tb)", re.I)   # also matches "Gen256GBWiFi"


def skip_reason(item, excl, min_price, require=()):
    title = (item.get("title") or "").lower()
    if require and not any(w in title for w in require):
        return f"title doesn't mention {'/'.join(require)}"
    amount = gbp_of(item)
    if min_price and amount is not None and amount < min_price:
        return f"under £{min_price:g}"
    for w in excl:
        if re.search(r"\b" + re.escape(w) + r"\b", title):
            if STORAGE_RE.search(title):
                return None          # e.g. "iPhone 13 128GB + case" -> keep
            return f"word '{w}'"
    return None


# ---------- seen-items memory ----------

def load_seen():
    """seen.json holds the listing ids already handled and which searches are primed."""
    try:
        d = json.loads(SEEN_FILE.read_text())
    except Exception:
        return set(), set()
    if isinstance(d, list):                      # older format: just ids
        return set(map(str, d)), set()
    return set(map(str, d.get("ids", []))), set(d.get("primed", []))


def save_seen(seen, primed):
    SEEN_FILE.write_text(json.dumps({"ids": list(seen)[-8000:], "primed": sorted(primed)}))


# ---------- iPhone model detection ----------

MODEL_RE = re.compile(r"i\s*phone\s*(1[0-9])\s*(pro\s*max|pro|plus|mini|max|\+)?", re.I)


def model_of(title):
    """'Apple iPhone 15 Pro Max 256GB' -> 'iPhone 15 Pro Max'"""
    t = re.sub(r"promax", "pro max", title or "", flags=re.I)
    m = MODEL_RE.search(t)
    if not m:
        return None
    variant = re.sub(r"\s+", " ", (m.group(2) or "").lower()).strip()
    variant = {"max": "pro max", "+": "plus"}.get(variant, variant)
    return " ".join(["iPhone", m.group(1)] + ([variant.title()] if variant else []))


def build_searches():
    """One Vinted search per iPhone generation; each listing is then matched to
    the exact model and checked against that model's own price range."""
    models = {m["name"].strip(): (float(m["min"]), float(m["max"])) for m in CONFIG["models"]}
    groups = {}
    for name, (lo, hi) in models.items():
        gen = re.search(r"\d+", name).group()
        g = groups.setdefault(gen, [lo, hi])
        g[0], g[1] = min(g[0], lo), max(g[1], hi)
    searches = []
    for gen, (lo, hi) in sorted(groups.items()):
        # Loose limits sent to Vinted (works whether it reads them as £ or $);
        # the exact £ range per model is checked afterwards.
        params = {"search_text": f"iphone {gen}", "order": "newest_first",
                  "price_from": int(lo * 0.75), "price_to": int(hi * 1.35 + 1),
                  "per_page": CONFIG.get("per_page", 96), "page": 1}
        searches.append((f"iPhone {gen}", params))
    return models, searches


# ---------- main loop ----------

def main():
    if "--test" in sys.argv:
        notify("Test", {"id": 0, "title": "iPhone 14 Pro 128GB (test)",
                        "price": {"amount": "199.00", "currency_code": "GBP"},
                        "url": f"https://{DOMAIN}/", "status": "Very good"})
        log("Test notification sent - check your phone.")
        return

    excl = [w.lower() for w in CONFIG.get("exclude_words", [])]
    models, searches = build_searches()
    # Sharing the work between several laptops: share.txt (or "share" in
    # config.json) holds e.g. "1/2" = this is laptop 1 of 2.
    share = str(CONFIG.get("share") or "").strip()
    share_file = BASE / "share.txt"
    if not share and share_file.exists():
        share = share_file.read_text(encoding="utf-8").strip()
    m = re.fullmatch(r"(\d+)\s*/\s*(\d+)", share)
    if m and 1 <= int(m.group(1)) <= int(m.group(2)) > 1:
        k, n = int(m.group(1)), int(m.group(2))
        searches = searches[k - 1::n]
        log(f"This is laptop {k} of {n}: watching {', '.join(nm for nm, _ in searches)}")
        models = {name: rng for name, rng in models.items()
                  if any(name.startswith(nm) for nm, _ in searches)}
    min_reviews = int(CONFIG.get("min_seller_reviews", 0) or 0)
    alert_if_unknown = CONFIG.get("alert_if_reviews_unknown", True)
    # One Vinted request every `seconds_between_checks` seconds, taking turns
    # through the searches (4 searches x 3s = each model checked every ~12s).
    base_gap = float(CONFIG.get("seconds_between_checks", 2))
    gap = base_gap
    calm_since = time.time()

    end_time = None
    if "--minutes" in sys.argv:
        end_time = time.time() + float(sys.argv[sys.argv.index("--minutes") + 1]) * 60

    seen, primed = load_seen()
    save_seen(seen, primed)  # make sure the file always exists (so GitHub can save it)
    backoff = 0
    v = Vinted()
    log(f"Watching {len(models)} models in {len(searches)} searches; one check every "
        f"~{base_gap:g}s (each model every ~{base_gap * len(searches):g}s); "
        f"seller must have >= {min_reviews} review(s)")

    turn = 0
    while end_time is None or time.time() < end_time:
        name, params = searches[turn % len(searches)]
        turn += 1
        started = time.time()
        try:
            items = v.search(params)
        except RateLimited:
            backoff = min(backoff * 2 or 60, 900)
            gap = min(gap * 2, 60)
            calm_since = time.time()
            log(f"Rate limited by Vinted - pausing {backoff}s, then checking every {gap:g}s")
            time.sleep(backoff)
            continue
        except Exception as e:
            log(f"Error on '{name}': {e}")
            time.sleep(max(gap, 10))
            continue
        backoff = 0
        # after 10 calm minutes, creep back towards full speed
        if gap > base_gap and time.time() - calm_since > 600:
            gap = max(base_gap, gap / 2)
            calm_since = time.time()
            log(f"Speeding back up: one check every {gap:g}s")

        new = [i for i in items if i["id"] not in seen]
        if name in primed and new:
            log(f"'{name}': {len(items)} fetched, {len(new)} new")
        for item in reversed(new):  # oldest first
            seen.add(item["id"])
            if name not in primed:
                continue                      # first look: just remember what exists
            title = item.get("title") or ""
            model = model_of(title)
            if model not in models:
                log(f"skip (model {model or '?'} not on list): {title}")
                continue
            lo, hi = models[model]
            gbp = gbp_of(item)
            if gbp is not None and not (lo <= gbp <= hi):
                log(f"skip ({model} {price_of(item)} outside £{lo:g}-£{hi:g}): {title}")
                continue
            reason = skip_reason(item, excl, 0)
            if reason:
                log(f"skip ({reason}): {title} - {price_of(item)}")
                continue
            note = ""
            if min_reviews:
                reviews = v.seller_reviews(item)
                if reviews is None:
                    if not alert_if_unknown:
                        log(f"skip (seller reviews unknown): {title}")
                        continue
                    note = "⚠️ seller reviews not checked"
                elif reviews < min_reviews:
                    log(f"skip (seller has {reviews} reviews): {title} - {price_of(item)}")
                    continue
                else:
                    note = f"⭐ seller has {reviews} review{'s' if reviews != 1 else ''}"
            if note:
                item["status"] = " · ".join(x for x in (item.get("status"), note) if x)
            log(f"NEW [{model}] {title} - {price_of(item)} {note}")
            notify(model, item)

        if name not in primed:
            log(f"'{name}': recorded {len(items)} existing listings")
            primed.add(name)
        save_seen(seen, primed)
        # wait so that checks are ~gap seconds apart (with a little randomness)
        wait = gap * random.uniform(0.8, 1.3) - (time.time() - started)
        if wait > 0:
            if end_time and time.time() + wait >= end_time:
                break
            time.sleep(wait)
    log("Run finished.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("Stopped.")
