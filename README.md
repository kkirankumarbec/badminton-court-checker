# Badminton Court Checker

Checks daily whether courts are getting booked out at **Badmintonium Academy**
(Doddathoguru, Electronic City) and emails an alert when only 2 or fewer of
the 7 courts remain free during the 7 PM - 9 PM window.

- Runs automatically every day at **12:00 PM IST** via GitHub Actions
  (`.github/workflows/check.yml`).
- Reads live availability straight from Playo's public booking API - no
  login or scraping needed.
- Can also be triggered manually from the Actions tab ("Run workflow").

## How it works

`check_availability.py` calls:

```
https://api.playo.io/booking-lab-public/availability/v1/<venueId>/SP5/<date>
```

for today's date, counts how many of the 7 courts are free for the
7:00 PM and 8:00 PM slots, and sends an email only if that count drops to
2 or fewer.

## Setup

This repo needs three GitHub Actions secrets (Settings -> Secrets and
variables -> Actions -> New repository secret) - the same ones used by the
`lichess-weekly-auto` bot:

| Secret | Value |
|---|---|
| `GMAIL_ADDRESS` | The Gmail address to send alerts from |
| `GMAIL_APP_PASSWORD` | A Gmail App Password for that account |
| `NOTIFY_EMAIL` | Where the alert should be sent (defaults to `GMAIL_ADDRESS` if left unset) |

Without these secrets the workflow still runs and logs availability, it
just skips sending the email.

## Adjusting the alert

Edit the constants at the top of `check_availability.py`:

- `ALERT_THRESHOLD` - courts remaining that triggers an email (default `2`)
- `ALERT_START_HOUR` / `ALERT_END_HOUR` - the time window checked (default
  7 PM - 9 PM)
