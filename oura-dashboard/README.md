# Oura dashboard + morning brief

Tracks every stat your Oura ring records, builds a self-contained HTML
dashboard, and emails you a short brief each morning with suggestions drawn
from your own trailing data.

Two moving parts:

- **A dashboard** (`out/index.html`) — one file, no server, no external
  requests. Hover any chart, switch the range, read the table view. Follows
  your system light/dark theme.
- **A morning brief** — an email that leads with the single thing most worth
  acting on today, then everything else worth knowing, each with the numbers
  behind it.

A scheduled GitHub Actions workflow runs the whole thing daily, so nothing
needs to stay running on your machine.

---

## Try it before connecting anything

No token needed — this builds the dashboard and brief from synthetic data:

```bash
cd oura-dashboard
python -m oura_dashboard demo          # writes out/index.html and out/brief.html
open out/index.html                    # or: xdg-open / start
```

Run from `src/` (or install the package) if `python -m oura_dashboard` cannot
find the module:

```bash
cd oura-dashboard/src && python -m oura_dashboard demo
```

## Setup

### 1. Get an Oura token

Create a **personal access token** at
<https://cloud.ouraring.com/personal-access-tokens>. It is tied to your own
account and needs no OAuth app.

### 2. Local configuration

```bash
cd oura-dashboard
cp .env.example .env
# then fill in OURA_TOKEN (and the mail settings if sending locally)
```

| Variable | Purpose |
|---|---|
| `OURA_TOKEN` | Your personal access token. Required. |
| `MAIL_TO` | Where the brief is sent. |
| `MAIL_FROM` | The Gmail address it is sent from. |
| `GMAIL_APP_PASSWORD` | A Gmail **App Password** (see below). |
| `OURA_SLEEP_NEED_HOURS` | Your nightly sleep target. Default `8.0`. |
| `OURA_TIMEZONE` | Informational; Oura returns local timestamps. |
| `OURA_SANDBOX` | `1` to hit Oura's sandbox (fake data, any token works). |

### 3. Gmail App Password

Gmail blocks normal sign-in over SMTP, so the brief needs an App Password —
a 16-character code, not your account password. Create one at
<https://myaccount.google.com/apppasswords> (requires 2-Step Verification).

### 4. First sync

```bash
python -m oura_dashboard sync --days 120   # pulls history into data/history.json
python -m oura_dashboard build             # writes out/index.html
python -m oura_dashboard brief             # prints the brief without sending
python -m oura_dashboard send --dry-run    # same, in send format
```

## Daily automation (GitHub Actions)

`.github/workflows/oura-daily.yml` runs every morning: it syncs, commits the
updated history, rebuilds the dashboard, publishes it to GitHub Pages, and
emails you the brief.

Add these under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Value |
|---|---|
| `OURA_TOKEN` | Your Oura personal access token |
| `MAIL_TO` | Where to send the brief |
| `MAIL_FROM` | Your Gmail address |
| `GMAIL_APP_PASSWORD` | The 16-character App Password |

Optionally add a **variable** `OURA_SLEEP_NEED_HOURS` if 8 hours is not your
target.

**Changing the time.** The cron is UTC:

```yaml
- cron: "0 11 * * *"   # 07:00 US Eastern in summer, 06:00 in winter
```

GitHub's scheduler can run a few minutes late under load, so pick a time
slightly before when you want to read it.

**The dashboard link.** The workflow publishes to GitHub Pages and links it in
the email. Enable it under **Settings → Pages → Source: GitHub Actions**. If
you would rather not publish it, the email also carries the dashboard as an
HTML attachment (`--attach-dashboard`), and the publish job is marked
`continue-on-error`, so leaving Pages off costs you the link but never the
brief.

Run it by hand any time from the **Actions** tab (`Run workflow`), optionally
with "Sync and build only" ticked to skip the email.

## What gets tracked

Every v2 endpoint the ring populates is fetched and stored raw, then joined
into one row per day:

| Group | Stats |
|---|---|
| Scores | sleep, readiness, activity, plus each of their contributor sub-scores |
| Sleep | time asleep, time in bed, deep/REM/light, awake, efficiency, latency, restlessness, bedtime and wake time, naps |
| Heart | average and lowest heart rate, average HRV, respiratory rate |
| Body | temperature deviation, blood oxygen, breathing disturbance index |
| Activity | steps, calories, high/medium/low activity minutes, sedentary time, inactivity alerts, walking equivalent, workouts |
| Stress | high-stress and restorative minutes, daily summary |
| Long horizon | resilience level, cardiovascular age, VO₂ max |

Raw documents are kept in `data/history.json` and upserted on each sync, so
your local record keeps growing and later corrections from Oura overwrite
earlier values.

## How the suggestions work

Every suggestion compares today against **your own** trailing baseline — the
last 7 days versus the 28 before them — rather than a population average. A
rule fires only with enough history behind it, and each one carries the numbers
that triggered it.

Roughly 23 rules cover recovery (low readiness, HRV drops, elevated resting
heart rate, temperature deviation, resilience slipping), sleep (debt, bedtime
drift and irregularity, efficiency, latency, short deep/REM, frequent naps),
training load (rising intensity against falling readiness, sedentary weeks,
good days to go hard), stress and breathing, and data gaps. Positive findings
are included deliberately: a brief that only nags gets ignored.

Ranked `critical` → `warn` → `info` → `win`; the top one leads the email and
the dashboard.

These are pattern observations from your own data, not medical advice.

## Commands

| Command | What it does |
|---|---|
| `sync [--days N]` | Fetch from the API and upsert into `data/history.json` |
| `build` | Regenerate `out/index.html` |
| `brief [--html] [--url URL]` | Print the brief without sending |
| `send [--dry-run] [--attach-dashboard] [--url URL]` | Email the brief |
| `morning [--skip-send] [--attach-dashboard]` | sync + build + send (the daily job) |
| `demo [--days N]` | Build everything from synthetic sample data |

Add `-v` for progress logging.

## Tests

```bash
cd oura-dashboard
python -m pytest -q
```

119 tests, no network access and no credentials required — the API is faked at
the client boundary and the rules are driven by constructed histories.

## Notes

- **No dependencies.** Standard library only, Python 3.10+. The charts are
  hand-built SVG, so the dashboard has nothing to load and nothing to break.
- **Rate limits.** Oura allows 5,000 requests per 5 minutes per token; one
  sync makes about 17. Transient 429s and 5xx responses are retried with
  exponential backoff.
- **`vO2_max`** really is spelled with a capital O in the API path —
  `vo2_max` returns 404.
- **Partial data is normal.** Today's documents appear as the ring syncs, and
  some endpoints stay empty depending on firmware and subscription. A failing
  endpoint is logged and skipped rather than sinking the run.
