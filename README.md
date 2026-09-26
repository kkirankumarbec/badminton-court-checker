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
   **WhatsApp click-to-send link** pre-filled with their share and a
   tappable pay link (`docs/pay.html`, see below) that opens their UPI app.
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

## Clearing dues (`docs/dues.html`)

The group tracks its running split inside **GPay** (that's where the
balances accumulate, and settling up there clears them automatically), so
this repo deliberately does not keep a second ledger. The "Clear dues"
page only handles the part GPay doesn't: getting people to actually pay.

1. Enter the **payee UPI ID** (whoever is owed - it's remembered on your
   device after the first time) and an optional note.
2. Type the **amount GPay shows** next to each person who still owes.
   Leave everyone else blank. Someone missing from the roster can be added
   on the page ("Add someone not listed"); that's saved on your device only.
   To add someone for everyone, put them in `docs/players.json`.
3. **Generate reminders** gives a **Remind on WhatsApp** button per person
   (a 1:1 chat with the message and amount ready to send) plus a combined
   summary to paste into the group chat.

I can't read GPay balances (there's no API), so the amounts are typed in by
whoever sends the reminders. Nothing is sent automatically.

**`docs/pay.html`** is the pay link inside those messages. It's a normal
https link, so it's tappable in WhatsApp; opening it on a phone shows the
amount and payee and a button that opens the UPI app pre-filled. It
validates its inputs, but anyone can craft a link to it, so it always shows
the payee UPI ID prominently for the payer to check.

The earlier Google Sheet ledger ("Badminton Court Ledger" in Drive) is no
longer linked from the site; the file is untouched if you want it back.

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
   | `NOTIFY_EMAIL` | Who gets the alerts: one address, or several separated by commas (defaults to `GMAIL_ADDRESS` if unset) |

   To alert more than one person, put all their addresses in
   `NOTIFY_EMAIL`, e.g. `you@gmail.com,friend@gmail.com`. The first address
   is the owner and is the only one that also gets the "did not run"
   failure emails. Keep the addresses in the secret rather than in the code:
   this repo is public, and the run logs never print them.

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
