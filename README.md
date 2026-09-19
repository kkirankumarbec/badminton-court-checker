# Badminton Court Checker

Checks court availability at **Badmintonium Academy** (Doddathoguru,
Electronic City) and emails you the results, using Playo's public booking
API - no login or scraping needed.

## Schedule (all times IST)

| Time | Mode | Behaviour |
|---|---|---|
| 12:00 PM | Alert-only | Emails **only** if 2 or fewer of the 7 courts remain free |
| 1:00 PM | Report | Always emails the current availability |
| 5:00 PM | Report | Always emails the current availability |

**Which slots get checked depends on the day:**

- **Monday - Friday**: that same day's **7 PM, 8 PM, and 9 PM** slots.
- **Saturday & Sunday**: nothing runs on the weekend days themselves.
  Instead, **Friday's** run also looks ahead and includes **Saturday's and
  Sunday's 8 AM and 9 AM** slots in the same email.

So on a normal Monday-Thursday, you get 3 emails/no-emails about that
evening. On Friday, the same 3 checks also cover the upcoming weekend
mornings. Saturday and Sunday themselves are quiet.

## How it works

`check_availability.py` calls:

```
https://api.playo.io/booking-lab-public/availability/v1/<venueId>/SP5/<date>
```

for each relevant date, counts how many of the 7 courts are free per hour,
and either sends an alert (noon) or a full report (1 PM / 5 PM).

## Setup

This repo needs three GitHub Actions secrets (Settings -> Secrets and
variables -> Actions -> New repository secret) - the same ones used by the
`lichess-weekly-auto` bot:

| Secret | Value |
|---|---|
| `GMAIL_ADDRESS` | The Gmail address to send from |
| `GMAIL_APP_PASSWORD` | A Gmail App Password for that account |
| `NOTIFY_EMAIL` | Where alerts/reports are sent (defaults to `GMAIL_ADDRESS` if unset) |

Without these secrets the workflow still runs and logs availability, it
just skips sending email.

You can also trigger a run manually from the Actions tab ("Run workflow"),
choosing `alert` or `report` mode.

## Adjusting the alert

Edit the constants at the top of `check_availability.py`:

- `ALERT_THRESHOLD` - courts remaining that triggers an alert (default `2`)
- `WEEKDAY_HOURS` - weekday slots checked (default `19, 20, 21` = 7-10 PM)
- `WEEKEND_HOURS` - weekend slots checked (default `8, 9` = 8-10 AM)
