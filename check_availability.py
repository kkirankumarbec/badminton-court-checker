import json
import os
import re
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import requests

VENUE_ID = "2b413335-e49f-4241-9ebd-c2d95606b286"
VENUE_NAME = "Badmintonium Academy, Doddathoguru, Electronic City"
SPORT_ID = "SP5"  # Badminton
BOOKING_URL = f"https://playo.co/booking?venueId={VENUE_ID}"

WEEKDAY_HOURS = [19, 20, 21]  # 7 PM, 8 PM, 9 PM slots - shown for Mon-Fri
WEEKEND_HOURS = [8, 9]        # 8 AM, 9 AM slots - shown for Sat/Sun
DAYS_AHEAD = 3                # show today + the next 2 days
ALERT_THRESHOLD = 2           # courts remaining that triggers an alert

VENUE_LAT = 12.852            # approximate, Doddathoguru area
VENUE_LON = 77.664
RAIN_CAUTION_PCT = 40         # % chance around a slot that shows "Rain possible"
RAIN_LIKELY_PCT = 60          # % chance around a slot that shows "Rain likely"
RAIN_HEAVY_MM = 2.5           # mm in an hour that counts as "Rain likely" at any %
RAIN_ALERT_DAYS = 2           # email for today + tomorrow only

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()


def parse_recipients(raw):
    seen, out = set(), []
    for addr in re.split(r"[,;\s]+", raw or ""):
        if "@" in addr and addr.lower() not in seen:
            seen.add(addr.lower())
            out.append(addr)
    return out


# NOTIFY_EMAIL may hold several comma-separated addresses; the first is the owner.
RECIPIENTS = (parse_recipients(os.getenv("NOTIFY_EMAIL", ""))
              or parse_recipients(GMAIL_ADDRESS))

RAIN_LABELS = {0: "Low rain chance", 1: "Rain possible", 2: "Rain likely"}
RAIN_ADVICE = {
    1: "Check the sky before you book.",
    2: "Think twice before booking, and leave early if you do.",
}

IST = timezone(timedelta(hours=5, minutes=30))
BASE_DIR = os.path.dirname(__file__)
PAGE_PATH = os.path.join(BASE_DIR, "docs", "index.html")
STATE_PATH = os.path.join(BASE_DIR, "alert_state.json")


def send_email(subject, body, owner_only=False):
    recipients = RECIPIENTS[:1] if owner_only else RECIPIENTS
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and recipients):
        print("Email not configured (GMAIL_ADDRESS / GMAIL_APP_PASSWORD / "
              "NOTIFY_EMAIL missing) - skipping email:", subject)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(recipients)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        refused = server.sendmail(GMAIL_ADDRESS, recipients, msg.as_string())
    # Never print addresses: GitHub only masks the whole secret string in public logs.
    print(f"Email sent to {len(recipients) - len(refused)} of {len(recipients)} recipient(s)")


def fetch_availability(date_str):
    url = (
        "https://api.playo.io/booking-lab-public/availability/v1/"
        f"{VENUE_ID}/{SPORT_ID}/{date_str}"
    )
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if data.get("requestStatus") != 1:
        raise RuntimeError(f"Unexpected API response: {data}")
    return data["data"]["courtInfo"]


def fetch_rain_forecast():
    """Return {"YYYY-MM-DD|hour": (chance %, mm, weather code)}, or None if the forecast failed.

    Rain must never stop the court check, so every failure ends up as None.
    """
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": VENUE_LAT,
                "longitude": VENUE_LON,
                "hourly": "precipitation_probability,precipitation,weather_code",
                "timezone": "Asia/Kolkata",
                "forecast_days": 7,
            },
            timeout=15,
        )
        resp.raise_for_status()
        hourly = resp.json()["hourly"]
        forecast = {}
        for stamp, chance, mm, code in zip(hourly["time"], hourly["precipitation_probability"],
                                           hourly["precipitation"], hourly["weather_code"]):
            if chance is not None or mm is not None:
                date_str, clock = stamp.split("T")
                forecast[f"{date_str}|{int(clock[:2])}"] = (chance or 0, mm or 0, code)
        if not forecast:
            raise ValueError("forecast had no hourly data")
        return forecast
    except Exception as exc:
        print(f"Rain forecast unavailable ({type(exc).__name__}) - continuing without it")
        return None


def slot_rain(forecast, date_str, hour):
    """Worst rain from the hour before a slot to the hour after it.

    Includes travel time: rain while getting there or going home matters as
    much as rain during play. Returns None when there is no forecast data.
    """
    if forecast is None:
        return None
    points = [forecast[f"{date_str}|{h}"] for h in (hour - 1, hour, hour + 1)
              if f"{date_str}|{h}" in forecast]
    if not points:
        return None
    chance = max(p[0] for p in points)
    mm = max(p[1] for p in points)
    codes = [p[2] for p in points if p[2] is not None]
    sky = max(codes) if codes else None  # higher codes are cloudier
    if chance >= RAIN_LIKELY_PCT or mm >= RAIN_HEAVY_MM:
        level = 2
    elif chance >= RAIN_CAUTION_PCT:
        level = 1
    else:
        level = 0
    return {"level": level, "chance": chance, "mm": mm, "sky": sky}


def add_rain(groups, forecast):
    """Attach per-slot rain and the day's worst level to each group."""
    for g in groups:
        g["rain"] = {h: slot_rain(forecast, g["date_str"], h) for h in g["hourly"]}
        known = [r for r in g["rain"].values() if r]
        g["rain_level"] = max((r["level"] for r in known), default=0)
        g["rain_hours"] = [h for h, r in g["rain"].items()
                           if r and r["level"] == g["rain_level"]]
        skies = [r["sky"] for r in known if r["sky"] is not None]
        g["sky"] = max(skies) if skies else None


def sky_text(sky):
    if sky is None:
        return "No rain expected"
    if sky <= 1:
        return "Clear sky, no rain expected"
    if sky == 2:
        return "Partly cloudy, no rain expected"
    if sky in (45, 48):
        return "Foggy, no rain expected"
    return "Cloudy, no rain expected"


def rain_slots_text(group):
    """Join back-to-back slots: 7, 8 and 9 PM reads as "7:00 PM to 10:00 PM"."""
    runs = []
    for h in sorted(group["rain_hours"]):
        if runs and runs[-1][1] == h:
            runs[-1][1] = h + 1
        else:
            runs.append([h, h + 1])
    return ", ".join(f"{fmt_hour(a)} to {fmt_hour(b)}" for a, b in runs)


def rain_detail(group):
    worst = max((group["rain"][h] for h in group["rain_hours"]), key=lambda r: r["chance"])
    return f"{worst['chance']}% chance, up to {worst['mm']:g} mm in an hour"


def newly_rainy_days(groups, state, now):
    """Dates to email about. One email per date, and again only if it gets worse."""
    today = now.date()
    newly_rainy = []
    for g in groups:
        days_away = (datetime.strptime(g["date_str"], "%Y-%m-%d").date() - today).days
        if days_away >= RAIN_ALERT_DAYS or g.get("rain_level", 0) < 1:
            continue
        key = f"{g['date_str']}|rain"
        if g["rain_level"] > state.get(key, 0):
            newly_rainy.append(g)
            state[key] = g["rain_level"]
    return newly_rainy


def fmt_hour(hour):
    return datetime(2000, 1, 1, hour % 24).strftime("%I:%M %p").lstrip("0")


def hourly_availability(date_str, hours):
    courts = fetch_availability(date_str)
    total = len(courts)
    hourly = {h: 0 for h in hours}
    for court in courts:
        for slot in court["slotInfo"]:
            hour = int(slot["time"].split(":")[0])
            if hour in hourly and slot["status"] == 1:
                hourly[hour] += 1
    return hourly, total


def build_group(label, date_label, date_str, hours):
    """Fetch one date's availability. Returns a dict describing the group."""
    hourly, total = hourly_availability(date_str, hours)
    low = {h: n for h, n in hourly.items() if n <= ALERT_THRESHOLD}
    return {
        "label": label,
        "date_label": date_label,
        "date_str": date_str,
        "hourly": hourly,
        "total": total,
        "low": low,
    }


def group_text(group):
    lines = [
        f"  {fmt_hour(h)} - {fmt_hour(h + 1)}: {n} of {group['total']} courts free"
        + (f" ({RAIN_LABELS[r['level']]}, {r['chance']}%)"
           if (r := group.get("rain", {}).get(h)) and r["level"] else "")
        for h, n in group["hourly"].items()
    ]
    return f"{group['label']}:\n" + "\n".join(lines)


def day_label(now, d, offset):
    if offset == 0:
        return f"Today ({d.strftime('%A, %d %b')})"
    if offset == 1:
        return f"Tomorrow ({d.strftime('%A, %d %b')})"
    return f"{d.strftime('%A')} ({d.strftime('%d %b')})"


def collect_groups(now):
    """Build availability groups for the next DAYS_AHEAD days that still have slots.

    Each day shows whichever hours are relevant to it: evening slots
    (7-10 PM) for a weekday, morning slots (8-10 AM) for a weekend day.
    A slot that has already started is dropped (Playo keeps reporting the
    original availability for past hours, which would show stale rows and
    fire false alerts). A day with nothing left is skipped, and the window
    moves on to the next day so you still see DAYS_AHEAD days.
    """
    groups = []
    for offset in range(DAYS_AHEAD + 7):
        if len(groups) == DAYS_AHEAD:
            break
        d = now + timedelta(days=offset)
        hours = WEEKDAY_HOURS if d.weekday() <= 4 else WEEKEND_HOURS
        hours = [h for h in hours
                 if d.replace(hour=h, minute=0, second=0, microsecond=0) > now]
        if not hours:
            continue
        groups.append(build_group(
            day_label(now, d, offset),
            d.strftime("%A, %d %b %Y"),
            d.strftime("%Y-%m-%d"),
            hours,
        ))
    return groups


def load_state():
    try:
        with open(STATE_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return {}


def save_state(state):
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2, sort_keys=True)


def newly_low_slots(groups, state, today_str):
    """Diff each group's low slots against the saved state.

    Returns the list of (date_label, hour, available, total) entries that
    just crossed into "low" since the last run, and mutates `state` in
    place: a slot is remembered while it stays low, and forgotten (so it
    can alert again later) once it recovers above the threshold. Stale
    entries for past dates are dropped.
    """
    state = {k: v for k, v in state.items() if k.split("|", 1)[0] >= today_str}
    newly_low = []

    for g in groups:
        for h, n in g["hourly"].items():
            key = f"{g['date_str']}|{h}"
            if n <= ALERT_THRESHOLD:
                if key not in state:
                    newly_low.append((g["date_label"], h, n, g["total"]))
                state[key] = True
            else:
                state.pop(key, None)

    return newly_low, state


def render_html(groups, now, forecast=True):
    def status_class(n, total):
        if n <= ALERT_THRESHOLD:
            return "low"
        if n <= total // 2:
            return "mid"
        return "ok"

    def rain_tag(g, h):
        r = g.get("rain", {}).get(h)
        if not r or not r["level"]:
            return ""
        return f'<span class="rain-tag r{r["level"]}">Rain {r["chance"]}%</span>'

    def rain_banner(g):
        level = g.get("rain_level", 0)
        if not g.get("rain_hours"):
            return ""
        if not level:
            return (f'<div class="rain-box r0"><strong>{sky_text(g["sky"])}</strong> '
                    f'around {rain_slots_text(g)}.</div>')
        return (f'<div class="rain-box r{level}"><strong>{RAIN_LABELS[level]}</strong> '
                f'around {rain_slots_text(g)}. {RAIN_ADVICE[level]}</div>')

    cards = []
    for g in groups:
        rows = "".join(
            f'<tr class="{status_class(n, g["total"])}" '
            f'data-start="{g["date_str"]}T{h:02d}:00:00+05:30">'
            f'<td>{fmt_hour(h)} - {fmt_hour(h + 1)}{rain_tag(g, h)}</td>'
            f'<td>{n} of {g["total"]} free</td>'
            f"</tr>"
            for h, n in g["hourly"].items()
        )
        cards.append(
            f'<section class="card"><h2>{g["label"]}</h2>{rain_banner(g)}'
            f"<table>{rows}</table></section>"
        )
    body_html = "\n".join(cards)

    rain_note = ("Rain forecast covers the hour before to the hour after each slot"
                 if forecast is not None else "Rain forecast unavailable right now")

    updated = now.strftime("%A, %d %b %Y - %I:%M %p").replace(" 0", " ") + " IST"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Badmintonium Court Availability</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    max-width: 480px; margin: 0 auto; padding: 24px 16px 48px;
    background: #f7f7f8; color: #1a1a1a;
  }}
  h1 {{ font-size: 1.25rem; margin-bottom: 4px; }}
  .subtitle {{ color: #666; font-size: 0.9rem; margin-bottom: 20px; }}
  .card {{
    background: #fff; border-radius: 12px; padding: 16px 18px;
    margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08);
  }}
  .card h2 {{ font-size: 1rem; margin: 0 0 10px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.95rem; }}
  td {{ padding: 8px 0; border-top: 1px solid #eee; }}
  td:last-child {{ text-align: right; font-weight: 600; }}
  tr:first-child td {{ border-top: none; }}
  tr.ok td:last-child {{ color: #1a7f37; }}
  tr.mid td:last-child {{ color: #b35900; }}
  tr.low td:last-child {{ color: #c62828; }}
  .rain-box {{
    font-size: 0.88rem; line-height: 1.4; padding: 10px 12px;
    border-radius: 8px; margin: 0 0 10px; border-left: 4px solid;
  }}
  .rain-box.r0 {{ background: #e9f5ec; border-color: #1a7f37; color: #14572a; }}
  .rain-box.r1 {{ background: #e8f1fb; border-color: #4a86c7; color: #1f4f82; }}
  .rain-box.r2 {{ background: #dbe7f7; border-color: #1f5fa8; color: #123d70; }}
  .rain-tag {{
    display: table; margin-top: 3px; padding: 1px 6px; border-radius: 6px;
    font-size: 0.72rem; font-weight: 600; white-space: nowrap;
  }}
  .rain-tag.r1 {{ background: #e8f1fb; color: #1f4f82; }}
  .rain-tag.r2 {{ background: #1f5fa8; color: #fff; }}
  .book {{
    display: block; text-align: center; background: #1a7f37; color: #fff;
    text-decoration: none; padding: 12px; border-radius: 10px;
    font-weight: 600; margin: 20px 0 10px;
  }}
  .split {{
    display: block; text-align: center; background: #fff; color: #1a7f37;
    text-decoration: none; padding: 12px; border-radius: 10px;
    font-weight: 600; margin: 0 0 10px; border: 1px solid #1a7f37;
  }}
  .dues, .tourn {{
    display: block; text-align: center; background: #fff; color: #555;
    text-decoration: none; padding: 12px; border-radius: 10px;
    font-weight: 600; margin: 0 0 10px; border: 1px solid #ccc;
  }}
  .tourn {{ margin-bottom: 20px; }}
  footer {{ color: #999; font-size: 0.8rem; text-align: center; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #17181a; color: #eee; }}
    .card {{ background: #232427; box-shadow: none; }}
    td {{ border-top-color: #333; }}
    .subtitle, footer {{ color: #999; }}
    .split, .dues, .tourn {{ background: #232427; }}
    .dues, .tourn {{ color: #ccc; border-color: #444; }}
    .rain-box.r0 {{ background: #1c2f23; color: #c9ecd3; }}
    .rain-box.r1, .rain-box.r2 {{ background: #1d2c3f; color: #cfe2f7; }}
    .rain-tag.r1 {{ background: #1d2c3f; color: #cfe2f7; }}
  }}
</style>
</head>
<body>
  <h1>Badmintonium Academy</h1>
  <div class="subtitle">Doddathoguru, Electronic City - court availability</div>
  {body_html}
  <div class="subtitle" id="empty" hidden>No upcoming slots right now - the next refresh will add the next day.</div>
  <a class="book" href="{BOOKING_URL}">Book on Playo</a>
  <a class="split" href="split.html">Split today's cost</a>
  <a class="dues" href="dues.html">Clear dues</a>
  <a class="tourn" href="tournaments.html">Tournaments this week</a>
  <footer>
    Last updated {updated}<br>
    {rain_note}<br>
    Live - refreshes every 15 minutes via GitHub Actions
  </footer>
  <script>
    // Between refreshes, hide slots that have started since the page was built.
    (function () {{
      var now = Date.now();
      document.querySelectorAll('tr[data-start]').forEach(function (tr) {{
        if (Date.parse(tr.getAttribute('data-start')) <= now) tr.remove();
      }});
      document.querySelectorAll('section.card').forEach(function (s) {{
        if (!s.querySelector('tr')) s.remove();
      }});
      if (!document.querySelector('section.card')) document.getElementById('empty').hidden = false;
    }})();
  </script>
</body>
</html>
"""


def write_page(groups, now, forecast):
    os.makedirs(os.path.dirname(PAGE_PATH), exist_ok=True)
    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(render_html(groups, now, forecast))
    print("Wrote", PAGE_PATH)


def main():
    now = datetime.now(IST)
    groups = collect_groups(now)
    forecast = fetch_rain_forecast()
    add_rain(groups, forecast)

    write_page(groups, now, forecast)

    report_body = (
        f"Court availability at {VENUE_NAME}:\n\n"
        + "\n\n".join(group_text(g) for g in groups)
        + f"\n\nBook now: {BOOKING_URL}"
    )
    print(report_body)

    state = load_state()
    newly_low, state = newly_low_slots(groups, state, now.strftime("%Y-%m-%d"))
    newly_rainy = newly_rainy_days(groups, state, now)
    save_state(state)

    if newly_low:
        lines = [
            f"Only {n} of {total} courts left for {fmt_hour(h)}-{fmt_hour(h + 1)} on {label}."
            for label, h, n, total in newly_low
        ]
        subject = f"[Court Alert] Low availability at {VENUE_NAME}"
        body = "\n".join(lines) + f"\n\nBook now: {BOOKING_URL}"
        send_email(subject, body)
    else:
        print("No newly-low slots - no alert email sent.")

    if newly_rainy:
        lines = [
            f"{RAIN_LABELS[g['rain_level']]} on {g['date_label']} around "
            f"{rain_slots_text(g)} ({rain_detail(g)}). {RAIN_ADVICE[g['rain_level']]}"
            for g in newly_rainy
        ]
        subject = f"[Rain Alert] {RAIN_LABELS[max(g['rain_level'] for g in newly_rainy)]} for badminton"
        body = ("\n\n".join(lines) + "\n\nCovers the hour before to the hour after each slot, "
                "so travel time is included.\nForecasts can be wrong, so check again before you leave.")
        send_email(subject, body)
    else:
        print("No new rain alerts - no rain email sent.")


def send_failure_alert(message):
    try:
        send_email("[ALERT] badminton-court-checker did not run", message, owner_only=True)
    except Exception as exc:
        print("Also failed to send the failure alert email:", exc)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_failure_alert(f"{type(exc).__name__}: {exc}")
        raise
