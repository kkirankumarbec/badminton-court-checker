import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import requests

VENUE_ID = "2b413335-e49f-4241-9ebd-c2d95606b286"
VENUE_NAME = "Badmintonium Academy, Doddathoguru, Electronic City"
SPORT_ID = "SP5"  # Badminton
BOOKING_URL = f"https://playo.co/booking?venueId={VENUE_ID}"

WEEKDAY_HOURS = [19, 20, 21]  # 7 PM, 8 PM, 9 PM slots - checked same day, Mon-Fri
WEEKEND_HOURS = [8, 9]        # 8 AM, 9 AM slots - checked ahead of time, only on Friday
ALERT_THRESHOLD = 2           # courts remaining that triggers an alert

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "").strip() or GMAIL_ADDRESS
MODE = os.getenv("MODE", "report").strip().lower()  # "alert" (noon) or "report" (1pm/5pm)

IST = timezone(timedelta(hours=5, minutes=30))
PAGE_PATH = os.path.join(os.path.dirname(__file__), "docs", "index.html")


def send_email(subject, body):
    if not (GMAIL_ADDRESS and GMAIL_APP_PASSWORD and NOTIFY_EMAIL):
        print("Email not configured (GMAIL_ADDRESS / GMAIL_APP_PASSWORD / "
              "NOTIFY_EMAIL missing) - skipping email:", subject)
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = NOTIFY_EMAIL
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [NOTIFY_EMAIL], msg.as_string())
    print("Email sent to", NOTIFY_EMAIL)


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


def collect_groups(now):
    """Build the list of availability groups to check for the given IST 'now'.

    Weekdays (Mon-Fri) check that same day's evening slots. Weekend mornings
    are checked one day ahead - since weekend courts fill up much earlier -
    so Friday covers Saturday, and Saturday covers Sunday. Sunday itself is
    quiet: Monday is a weekday and gets checked same-day as usual.
    """
    weekday = now.weekday()  # Monday = 0 ... Sunday = 6
    groups = []

    if weekday <= 4:  # Monday-Friday: today's own evening slots
        today_label = f"Today ({now.strftime('%A, %d %b')})"
        groups.append(build_group(
            today_label, now.strftime("%A, %d %b %Y"), now.strftime("%Y-%m-%d"), WEEKDAY_HOURS
        ))

    if weekday in (4, 5):  # Friday & Saturday: one day ahead to the next weekend morning
        d = now + timedelta(days=1)
        label = f"{d.strftime('%A')} ({d.strftime('%d %b')})"
        groups.append(build_group(
            label, d.strftime("%A, %d %b %Y"), d.strftime("%Y-%m-%d"), WEEKEND_HOURS
        ))

    return groups


def render_html(groups, now, mode):
    def status_class(n, total):
        if n <= ALERT_THRESHOLD:
            return "low"
        if n <= total // 2:
            return "mid"
        return "ok"

    if groups:
        cards = []
        for g in groups:
            rows = "".join(
                f'<tr class="{status_class(n, g["total"])}">'
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
    else:
        body_html = (
            '<section class="card"><p class="quiet">No check runs on Sunday - '
            "Sunday morning's availability was already shown here from Saturday's "
            "check. Next update: Monday evening.</p></section>"
        )

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
  .quiet {{ color: #666; font-size: 0.9rem; margin: 0; }}
  .book {{
    display: block; text-align: center; background: #1a7f37; color: #fff;
    text-decoration: none; padding: 12px; border-radius: 10px;
    font-weight: 600; margin: 20px 0;
  }}
  footer {{ color: #999; font-size: 0.8rem; text-align: center; }}
  @media (prefers-color-scheme: dark) {{
    body {{ background: #17181a; color: #eee; }}
    .card {{ background: #232427; box-shadow: none; }}
    td {{ border-top-color: #333; }}
    .subtitle, footer, .quiet {{ color: #999; }}
  }}
</style>
</head>
<body>
  <h1>Badmintonium Academy</h1>
  <div class="subtitle">Doddathoguru, Electronic City - court availability</div>
  {body_html}
  <a class="book" href="{BOOKING_URL}">Book on Playo</a>
  <footer>
    Last updated {updated} ({mode} check)<br>
    Auto-refreshed 3x daily via GitHub Actions
  </footer>
</body>
</html>
"""


def write_page(groups, now, mode):
    os.makedirs(os.path.dirname(PAGE_PATH), exist_ok=True)
    with open(PAGE_PATH, "w", encoding="utf-8") as f:
        f.write(render_html(groups, now, mode))
    print("Wrote", PAGE_PATH)


def main():
    now = datetime.now(IST)
    groups = collect_groups(now)

    if not groups:
        print(f"{now.strftime('%A')} - nothing scheduled "
              f"(Sunday's availability was already checked and mailed on Saturday). "
              f"Leaving the page as Saturday left it.")
        return

    write_page(groups, now, MODE)

    report_body = (
        f"Court availability at {VENUE_NAME}:\n\n"
        + "\n\n".join(group_text(g) for g in groups)
        + f"\n\nBook now: {BOOKING_URL}"
    )
    print(report_body)

    low_groups = [
        (g["date_label"], g["low"], g["total"]) for g in groups if g["low"]
    ]

    if MODE == "alert":
        if low_groups:
            alert_lines = [
                f"Only {n} of {total} courts left for {fmt_hour(h)}-{fmt_hour(h + 1)} on {label}."
                for label, low, total in low_groups
                for h, n in low.items()
            ]
            subject = f"[Court Alert] Low availability at {VENUE_NAME}"
            body = "\n".join(alert_lines) + f"\n\nBook now: {BOOKING_URL}"
            send_email(subject, body)
        else:
            print("Availability above alert threshold - no alert email sent.")
    else:
        subject = f"Badmintonium Court Availability - {now.strftime('%a, %d %b %Y')}"
        send_email(subject, report_body)


def send_failure_alert(message):
    try:
        send_email("[ALERT] badminton-court-checker did not run", message)
    except Exception as exc:
        print("Also failed to send the failure alert email:", exc)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_failure_alert(f"{type(exc).__name__}: {exc}")
        raise
