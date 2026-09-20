# Badminton Court Checker

Checks court availability at **Badmintonium Academy** (Doddathoguru,
Electronic City), emails you low-availability alerts, and publishes a
**shareable live status page** - using Playo's public booking API, no
login or scraping needed.

## Schedule

Runs **every 15 minutes, all day, every day** via GitHub Actions
(`*/15 * * * *`). There's no fixed check-in time anymore - the page and
alerts are continuously kept current.

**Each run shows the next 3 days** (today + the following 2), and picks
the relevant hours per day:

- A **weekday** shows that day's **7 PM, 8 PM, and 9 PM** slots.
- A **weekend day** (Sat/Sun) shows its **8 AM and 9 AM** slots.

So depending on what day it is, the 3-day window naturally mixes evening
and morning slots - e.g. checking on a Thursday shows Thu/Fri evenings
plus Saturday morning, automatically.

## Alerts

An email fires the moment any shown slot's availability drops to **2 or
fewer courts**. Because checks run every 15 minutes, a slot that *stays*
low doesn't re-alert every cycle - you're emailed once when it first
crosses the threshold, and only alerted again if it recovers (books back
up above 2) and later drops low again. This state is tracked in
`alert_state.json`, which the workflow commits alongside the page.

## Shareable link

Every run regenerates `docs/index.html` - a small mobile-friendly status
page - and the workflow commits it back to the repo. Once GitHub Pages is
turned on (one-time, see Setup below), that file is served at:

```
https://<your-github-username>.github.io/badminton-court-checker/
```

Anyone with that link (a friend included) sees the same live availability,
refreshed every 15 minutes. No login needed to view it.

## How it works

`check_availability.py` calls:

```
https://api.playo.io/booking-lab-public/availability/v1/<venueId>/SP5/<date>
```

for each of the next 3 dates, counts how many of the 7 courts are free per
hour, writes `docs/index.html`, and emails an alert for any slot that just
became low.

## Setup

1. **Email secrets** - add three GitHub Actions secrets (Settings ->
   Secrets and variables -> Actions -> New repository secret), the same
   ones used by the `lichess-weekly-auto` bot:

   | Secret | Value |
   |---|---|
   | `GMAIL_ADDRESS` | The Gmail address to send from |
   | `GMAIL_APP_PASSWORD` | A Gmail App Password for that account |
   | `NOTIFY_EMAIL` | Where alerts are sent (defaults to `GMAIL_ADDRESS` if unset) |

   Without these secrets the workflow still runs, updates the page, and
   logs availability - it just skips sending email.

2. **GitHub Pages** (for the shareable link) - go to Settings -> Pages ->
   under "Build and deployment", set Source to "Deploy from a branch",
   Branch to `main` and folder to `/docs`, then Save. The link goes live
   within a minute or two, and every future run keeps it updated.

You can also trigger a run manually from the Actions tab ("Run workflow").

Note: since the page's "last updated" timestamp changes on every run, the
workflow commits to the repo roughly every 15 minutes (~96 commits/day).
That's expected and harmless (GitHub Actions minutes are unlimited for
public repos) - just don't be surprised by a busy commit history.

## Adjusting the alert

Edit the constants at the top of `check_availability.py`:

- `ALERT_THRESHOLD` - courts remaining that triggers an alert (default `2`)
- `DAYS_AHEAD` - how many days ahead to show (default `3`)
- `WEEKDAY_HOURS` - weekday slots checked (default `19, 20, 21` = 7-10 PM)
- `WEEKEND_HOURS` - weekend slots checked (default `8, 9` = 8-10 AM)
