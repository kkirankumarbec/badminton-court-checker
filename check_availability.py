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


def render_html(groups, now):
    def status_class(n, total):
        if n <= ALERT_THRESHOLD:
            return "low"
        if n <= total // 2:
            return "mid"
        return "ok"

    cards = []
    for g in groups:
        rows = "".join(
            f'<tr class="{status_class(n, g["total"])}" '
            f'data-start="{g["date_str"]}T{h:02d}:00:00+05:30">'
            f'<td>{fmt_hour(h)} - {fmt_hour(h + 1)}</td>'
            f'<td>{n} of {g["total"]} free</td>'
            f"</tr>"
            for h, n in g["hourly"].items()
        )
        cards.append(
            f'<section class="card"><h2>{g["label"]}</h2>'
            f"<table>{rows}</table></section>"
        )
    body_html = "\n".join(cards)

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
  .dues {{
    display: block; text-align: center; background: #fff; color: #555;
    text-decoration: none; padding: 12px; border-radius: 10px;
    font-weight: 600; margin: 0 0 20px; border: 1px solid #ccc;
  }}
  footer {{ color: #999; font-size: 0.8rem; text-align: center; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #17181a; color: #eee; }}
    .card {{ background: #232427; box-shadow: none; }}
    td {{ border-top-color: #333; }}
    .subtitle, footer {{ color: #999; }}
    .split, .dues {{ background: #232427; }}
    .dues {{ color: #ccc; border-color: #444; }}
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
  <footer>
    Last updated {updated}<br>
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


def write_page(groups, now):
    os.makedirs(os.path.dirname(PAGE_PATH), exist_ok=True)
    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(render_html(groups, now))
    print("Wrote", PAGE_PATH)


def main():
    now = datetime.now(IST)
    groups = collect_groups(now)

    write_page(groups, now)

    report_body = (
        f"Court availability at {VENUE_NAME}:\n\n"
        + "\n\n".join(group_text(g) for g in groups)
        + f"\n\nBook now: {BOOKING_URL}"
    )
    print(report_body)

    state = load_state()
    newly_low, state = newly_low_slots(groups, state, now.strftime("%Y-%m-%d"))
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
