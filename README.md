# Badminton Court Checker

Checks court availability at **Badmintonium Academy** (Doddathoguru,
Electronic City), emails you the results, and publishes a **shareable live
status page** - using Playo's public booking API, no login or scraping
needed.

## Schedule (all times IST)

| Time | Mode | Behaviour |
|---|---|---|
| 12:00 PM | Alert-only | Emails **only** if 2 or fewer of the 7 courts remain free |
| 1:00 PM | Report | Always emails the current availability |
| 5:00 PM | Report | Always emails the current availability |

**Which slots get checked depends on the day** - weekend courts fill up
much earlier, so each weekend day's status is checked **one day ahead**:

- **Monday - Friday**: that same day's **7 PM, 8 PM, and 9 PM** slots.
- **Friday** additionally looks one day ahead and includes **Saturday's**
  8 AM and 9 AM slots in the same email.
- **Saturday** looks one day ahead and includes **Sunday's** 8 AM and 9 AM
  slots (no check of Saturday itself - it isn't a play day).
- **Sunday** is quiet - Monday is a weekday and gets checked same-day as
  usual, so there's nothing to look ahead to.

So Monday-Thursday you get 3 emails/no-emails about that evening. Friday's
3 checks also cover Saturday morning, and Saturday's 3 checks cover Sunday
morning. Sunday itself sends nothing.

## Shareable link

Every run regenerates `docs/index.html` - a small mobile-friendly status
page - and the workflow commits it back to the repo. Once GitHub Pages is
turned on (one-time, see Setup below), that file is served at:

```
https://<your-github-username>.github.io/badminton-court-checker/
```

Anyone with that link (a friend included) sees the same live availability
you get emailed, refreshed 3x a day automatically. No login needed to view
it.

## How it works

`check_availability.py` calls:

```
https://api.playo.io/booking-lab-public/availability/v1/<venueId>/SP5/<date>
```

for each relevant date, counts how many of the 7 courts are free per hour,
writes `docs/index.html`, and either sends an alert (noon) or a full
report email (1 PM / 5 PM).

## Setup

1. **Email secrets** - add three GitHub Actions secrets (Settings ->
   Secrets and variables -> Actions -> New repository secret), the same
   ones used by the `lichess-weekly-auto` bot:

   | Secret | Value |
   |---|---|
   | `GMAIL_ADDRESS` | The Gmail address to send from |
   | `GMAIL_APP_PASSWORD` | A Gmail App Password for that account |
   | `NOTIFY_EMAIL` | Where alerts/reports are sent (defaults to `GMAIL_ADDRESS` if unset) |

   Without these secrets the workflow still runs, updates the page, and
   logs availability - it just skips sending email.

2. **GitHub Pages** (for the shareable link) - go to Settings -> Pages ->
   under "Build and deployment", set Source to "Deploy from a branch",
   Branch to `main` and folder to `/docs`, then Save. The link goes live
   within a minute or two, and every future run keeps it updated.

You can also trigger a run manually from the Actions tab ("Run workflow"),
choosing `alert` or `report` mode.

## Adjusting the alert

Edit the constants at the top of `check_availability.py`:

- `ALERT_THRESHOLD` - courts remaining that triggers an alert (default `2`)
- `WEEKDAY_HOURS` - weekday slots checked (default `19, 20, 21` = 7-10 PM)
- `WEEKEND_HOURS` - weekend slots checked (default `8, 9` = 8-10 AM)
