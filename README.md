# Badminton Court Checker

Checks court availability at **Badmintonium Academy** (Doddathoguru,
Electronic City), emails you low-availability alerts, and publishes a
**shareable live status page** - using Playo's public booking API, no
login or scraping needed.

## Schedule

Runs **hourly** (a few minutes past the hour), every day, via GitHub
Actions (`7 * * * *`).

This used to be set to every 15 minutes, but GitHub's native `schedule`
trigger doesn't reliably honor sub-hourly cron intervals - it silently
delayed runs to every 2-6 hours in practice, regardless of the requested
interval. Hourly (off the exact hour, to dodge top-of-hour queueing
across GitHub) is the most reliable cadence achievable without an
external trigger.

**For true 15-minute freshness**, add an external scheduler (e.g.
[cron-job.org](https://cron-job.org), free) that calls GitHub's API to
run the workflow on demand:

- URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/check.yml/dispatches`
- Method: `POST`, every 15 minutes
- Headers: `Authorization: Bearer <a GitHub token scoped to Actions: Read and write on just this repo>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
- Body: `{"ref":"main"}`

The native hourly schedule stays as a harmless fallback either way.

**Each run shows the next 3 days** (today + the following 2), and picks
the relevant hours per day:

- A **weekday** shows that day's **7 PM, 8 PM, and 9 PM** slots.
- A **weekend day** (Sat/Sun) shows its **8 AM and 9 AM** slots.

So depending on what day it is, the 3-day window naturally mixes evening
and morning slots - e.g. checking on a Thursday shows Thu/Fri evenings
plus Saturday morning, automatically.

## Alerts

An email fires the moment any shown slot's availability drops to **2 or
fewer courts**. Because checks run repeatedly, a slot that *stays*
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
refreshed roughly hourly (or every 15 min if you've added the external
trigger above). No login needed to view it.

## Splitting the court cost

The page links to `docs/split.html` ("Split court cost") - a small
calculator for whoever paid to work out and send everyone's share:

1. Enter the total amount, the payee's UPI ID (whoever booked/paid that
   session), and pick who's playing from the group roster.
2. It splits the amount evenly (any odd paisa goes to the last person, so
   the total always adds up exactly) and generates, per person, a
   **WhatsApp click-to-send link** pre-filled with their share and a UPI
   payment link that opens their UPI app when they tap it.
3. There's also a **"Copy summary"** button with one combined message for
   pasting straight into the group chat - WhatsApp has no way to link
   directly into a group, so this is the fastest manual alternative.

Nothing is sent automatically - you still tap "Send on WhatsApp" (or paste
the summary) yourself for each session; there's no API for auto-nudging
someone's UPI app, and this keeps money-related messages under your
control.

**The group roster** lives in `docs/players.json` - a simple list of
`{"name": ..., "phone": "91..."}` entries (country code, no `+` or spaces).
Edit that file directly in the repo to add or remove people; it isn't
touched by the automated workflow, so your edits stick.

## Tracking who owes what (running ledger)

The page also links to a **Google Sheet** ("Who owes what") that tracks
outstanding balances across sessions - unlike the split calculator above,
this one remembers, so an unpaid amount carries forward until it's settled,
however many days that takes. Three of you book on rotation, so this is a
shared Sheet, not another static page.

It has four sections in one tab:

- **ROSTER** - player names (grows independently of `players.json`).
- **BOOKINGS** - one row per day you book: Date, Total, Paid By. The
  Num Players and Share columns fill in automatically.
- **PARTICIPANTS** - one row per person per booking (add rows for
  everyone who played that date). Their share is auto-filled - 0 for
  whoever is listed as "Paid By" that day, since paying the venue already
  covers their own share.
- **PAYMENTS** - one row per payment someone makes to settle up.
- **BALANCES** - fully automatic, don't type into it: Total Owed minus
  Total Paid per person, running forever until you log a payment against
  them.

To use it day to day: after a booking, add one Bookings row and one
Participants row per player who showed up. When someone pays, add one
Payments row. That's it - Balances updates itself. Running low on
pre-filled rows (it ships with ~6 weeks of headroom) just means selecting
the last formula row in a section and copy-pasting it down as many rows as
you need - Sheets adjusts the relative references automatically.

**Sharing it**: the Sheet is private to whoever created it by default.
Share it (Sheets' own Share button, "Editor" access) with the other two
people who book, so all three can log bookings and payments without
routing through you.

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
workflow commits to the repo roughly once an hour (~24 commits/day, more
if you've added the external 15-min trigger). That's expected and
harmless (GitHub Actions minutes are unlimited for
public repos) - just don't be surprised by a busy commit history.

## Adjusting the alert

Edit the constants at the top of `check_availability.py`:

- `ALERT_THRESHOLD` - courts remaining that triggers an alert (default `2`)
- `DAYS_AHEAD` - how many days ahead to show (default `3`)
- `WEEKDAY_HOURS` - weekday slots checked (default `19, 20, 21` = 7-10 PM)
- `WEEKEND_HOURS` - weekend slots checked (default `8, 9` = 8-10 AM)
