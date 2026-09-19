import os
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, timedelta, timezone

import requests

VENUE_ID = "2b413335-e49f-4241-9ebd-c2d95606b286"
VENUE_NAME = "Badmintonium Academy, Doddathoguru, Electronic City"
SPORT_ID = "SP5"  # Badminton
BOOKING_URL = f"https://playo.co/booking?venueId={VENUE_ID}"

ALERT_START_HOUR = 19  # 7 PM
ALERT_END_HOUR = 21    # 9 PM (slots starting 19:00 and 20:00 are checked)
ALERT_THRESHOLD = 2    # send an email when available courts drop to this or fewer

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "").strip()
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "").strip() or GMAIL_ADDRESS

IST = timezone(timedelta(hours=5, minutes=30))


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
    print("Alert email sent to", NOTIFY_EMAIL)


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
    return datetime(2000, 1, 1, hour).strftime("%I:%M %p").lstrip("0")


def hourly_availability(courts):
    hourly = {}
    for court in courts:
        for slot in court["slotInfo"]:
            hour = int(slot["time"].split(":")[0])
            if ALERT_START_HOUR <= hour < ALERT_END_HOUR:
                hourly.setdefault(hour, 0)
                if slot["status"] == 1:
                    hourly[hour] += 1
    return dict(sorted(hourly.items()))


def send_alert(message):
    try:
        send_email("[ALERT] badminton-court-checker did not run", message)
    except Exception as exc:
        print("Also failed to send the alert email:", exc)


def main():
    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%Y-%m-%d")

    courts = fetch_availability(date_str)
    total_courts = len(courts)
    hourly = hourly_availability(courts)

    print(f"Checked {VENUE_NAME} for {date_str} ({total_courts} courts total)")
    for hour, available in hourly.items():
        print(f"  {fmt_hour(hour)}-{fmt_hour(hour + 1)}: {available}/{total_courts} courts free")

    low_hours = {h: n for h, n in hourly.items() if n <= ALERT_THRESHOLD}

    if low_hours:
        lines = [
            f"Only {n} court(s) left at {VENUE_NAME} for "
            f"{fmt_hour(h)}-{fmt_hour(h + 1)} today ({now_ist.strftime('%A, %d %b %Y')})."
            for h, n in low_hours.items()
        ]
        body = "\n".join(lines) + f"\n\nBook now: {BOOKING_URL}"
        subject = f"[Court Alert] Only {min(low_hours.values())} court(s) left 7-9 PM today"
        send_email(subject, body)
    else:
        print("Availability above alert threshold - no email sent.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        send_alert(f"{type(exc).__name__}: {exc}")
        raise
