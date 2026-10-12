"""Refresh docs/tournaments.json with upcoming Bengaluru badminton tournaments from Playo.

Reads Playo's public community-events pages (the same data the website shows), keeps
badminton tournaments only, and writes a small JSON file that docs/tournaments.html
renders. Runs inside the existing 15-minute workflow but only refreshes when the file
is older than ~2 days. A failed fetch never overwrites the previous file.
"""
import html
import json
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

LIST_URLS = [
    "https://playo.co/experiences/bangalore/event/badminton",
    "https://playo.co/experiences/bangalore/event/all",
]
DETAIL_URL = "https://playo.co/experience-details/{key}"
BADMINTON = "SP5"
MAX_SPORTS = 3  # mass multi-sport events (e.g. Decathlon kids' days) list 170+ sports
REFRESH_AFTER = timedelta(hours=47, minutes=30)

IST = timezone(timedelta(hours=5, minutes=30))
PATH = os.getenv("TOURNAMENTS_PATH") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "docs", "tournaments.json")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; badminton-court-checker)"}

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
MONTH_WORD = re.compile(
    r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b", re.I)


def get_next_data(url):
    resp = requests.get(url, headers=HEADERS, timeout=25)
    resp.raise_for_status()
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not m:
        raise RuntimeError(f"no embedded data on {url} (page layout changed?)")
    return json.loads(m.group(1))["props"]["pageProps"]


def parse_date_range(text):
    """'24th & 25th October 2026' -> ('2026-10-24', '2026-10-25'); (None, None) if unclear."""
    if not text:
        return None, None
    months = {MONTHS[m.lower()[:3]] for m in MONTH_WORD.findall(text)}
    year = re.search(r"\b(20\d{2})\b", text)
    if len(months) != 1 or not year:
        return None, None
    days = [int(d) for d in re.findall(r"(?<!\d)(\d{1,2})(?!\d)", re.sub(r"\b20\d{2}\b", "", text))
            if 1 <= int(d) <= 31]
    if not days:
        return None, None
    try:
        y, mo = int(year.group(1)), months.pop()
        return date(y, mo, min(days)).isoformat(), date(y, mo, max(days)).isoformat()
    except ValueError:
        return None, None


def clean_text(value, limit):
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",;:- ")
    return cut + "..."


def clean_lines(value, limit):
    """Like clean_text but keeps line breaks (fee tables read badly when flattened)."""
    raw = re.sub(r"\s*\n\s*", " ", str(value or ""))  # source newlines are just whitespace in HTML
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</div>", "\n", raw)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    out = []
    for line in (re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")):
        if line:
            out.append(line)
        elif out and out[-1]:
            out.append("")
    text = "\n".join(out).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    cut = cut.rsplit("\n", 1)[0] if "\n" in cut else cut.rsplit(" ", 1)[0]
    return cut.rstrip(",;:- \n") + "..."


def playo_url(url):
    return url if isinstance(url, str) and re.match(r"^https://playo\.co/", url) else None


def listing_items(page_props):
    data = page_props["listData"]["data"]
    items = data.get("exploreListing", [])
    declared = next((int(t.get("headerCount", 0)) for t in data.get("tabHeadersMetadata", [])
                     if t.get("categoryType") == "event"), len(items))
    return items, declared


def is_badminton_tournament(item):
    sports = item.get("sports") or []
    return (item.get("tag") == "Tournament" and BADMINTON in sports
            and len(sports) <= MAX_SPORTS and item.get("activeKey"))


def build_event(item, detail):
    start, end = parse_date_range(item.get("dateStr"))
    iso = (detail or {}).get("date")
    if isinstance(iso, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", iso):
        start = iso
    if not start:
        return None
    if not end or end < start:
        end = start

    blocks = (detail or {}).get("infoData") or []
    overview = next((b.get("value") for b in blocks if "overview" in str(b.get("key", "")).lower()),
                    blocks[0].get("value") if blocks else "")
    fee = next((b.get("value") for b in blocks if "fee" in str(b.get("key", "")).lower()), "")
    register = None
    for fn in (detail or {}).get("functionData") or []:
        if "register" in str(fn.get("caption", "")).lower():
            register = playo_url(fn.get("content"))
            break

    return {
        "id": item["id"],
        "name": clean_text(item.get("name"), 120),
        "venue": clean_text((detail or {}).get("location") or item.get("address"), 120),
        "date": start,
        "end_date": end,
        "date_label": clean_text(item.get("dateStr"), 60),
        "timing": clean_text(item.get("timing"), 40),
        "summary": clean_text(overview, 240),
        "entry_fee": clean_lines(fee, 400),
        "url": DETAIL_URL.format(key=item["activeKey"]),
        "register_url": register,
    }


def load_existing():
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return None


def main():
    now = datetime.now(IST)
    existing = load_existing()
    if existing and not os.getenv("FORCE") and existing.get("fetched_at"):
        try:
            age = now - datetime.fromisoformat(existing["fetched_at"])
            if timedelta(0) <= age < REFRESH_AFTER:
                print(f"tournaments: fresh ({age.total_seconds() / 3600:.1f}h old), skipping")
                return 0
        except ValueError:
            pass

    seen, picked, truncated = {}, [], False
    for i, url in enumerate(LIST_URLS):
        items, declared = listing_items(get_next_data(url))
        if i == 0 and declared > len(items):
            truncated = True
        for item in items:
            if item.get("id") not in seen and is_badminton_tournament(item):
                seen[item["id"]] = True
                picked.append(item)

    today = now.date().isoformat()
    events = []
    for item in picked:
        try:
            time.sleep(1)
            detail = get_next_data(DETAIL_URL.format(key=item["activeKey"]))["data"]["list"][0]
        except Exception as exc:  # one broken event page must not lose the rest
            print(f"tournaments: detail failed for one event ({type(exc).__name__}), using listing only")
            detail = None
        event = build_event(item, detail)
        if event and event["end_date"] >= today:
            events.append(event)
    events.sort(key=lambda e: (e["date"], e["name"]))

    out = {
        "fetched_at": now.isoformat(timespec="minutes"),
        "source": "Playo community events, Bengaluru",
        "source_url": LIST_URLS[0],
        "truncated": truncated,
        "events": events,
    }
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, PATH)
    print(f"tournaments: wrote {len(events)} upcoming event(s)" + (" (listing may be truncated)" if truncated else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
