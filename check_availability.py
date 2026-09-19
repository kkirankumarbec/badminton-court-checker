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


def build_group(label, date_str, hours):
    """Fetch + format one date's availability. Returns (section_text, low_hours, total_courts)."""
    hourly, total = hourly_availability(date_str, hours)
    lines = [
        f"  {fmt_hour(h)} - {fmt_hour(h + 1)}: {hourly[h]} of {total} courts free"
        for h in hours
    ]
    section = f"{label}:\n" + "\n".join(lines)
    low = {h: n for h, n in hourly.items() if n <= ALERT_THRESHOLD}
    return section, low, total


def main():
    now = datetime.now(IST)
    weekday = now.weekday()  # Monday = 0 ... Sunday = 6

    if weekday >= 5:  # Saturday / Sunday - nothing runs on the weekend itself
        print(f"{now.strftime('%A')} - nothing scheduled "
              f"(weekend availability is checked and mailed on Friday).")
        return

    sections = []
    low_groups = []  # list of (date_label, low_hours_dict, total_courts)

    # Today's weekday evening slots (every weekday, Mon-Fri)
    today_str = now.strftime("%Y-%m-%d")
    today_label = f"Today ({now.strftime('%A, %d %b')})"
    section, low, total = build_group(today_label, today_str, WEEKDAY_HOURS)
    sections.append(section)
    if low:
        low_groups.append((now.strftime("%A, %d %b %Y"), low, total))

    # On Friday, also look ahead to the weekend mornings
    if weekday == 4:  # Friday
        for offset, day_name in ((1, "Saturday"), (2, "Sunday")):
            d = now + timedelta(days=offset)
            d_str = d.strftime("%Y-%m-%d")
            label = f"{day_name} ({d.strftime('%d %b')})"
            section, low, total = build_group(label, d_str, WEEKEND_HOURS)
            sections.append(section)
            if low:
                low_groups.append((d.strftime("%A, %d %b %Y"), low, total))

    report_body = (
        f"Court availability at {VENUE_NAME}:\n\n"
        + "\n\n".join(sections)
        + f"\n\nBook now: {BOOKING_URL}"
    )
    print(report_body)

    if MODE == "alert":
        if low_groups:
            alert_lines = [
                f"Only {n} of {total} courts left for {fmt_hour(h)}-{fmt_hour(h + 1)} on {date_label}."
                for date_label, low, total in low_groups
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
