#!/usr/bin/env bash
# Interactive setup for the Oura dashboard and morning brief.
#
# Collects the four things only you can create (an Oura app, a Gmail app
# password, browser consent, a GitHub token), then does everything else:
# writes .env, uploads all six GitHub secrets, and verifies the whole path.
#
# Safe to re-run — it shows what is already set and lets you keep it.

set -uo pipefail

cd "$(dirname "$0")"

bold=$(tput bold 2>/dev/null || true)
dim=$(tput dim 2>/dev/null || true)
red=$(tput setaf 1 2>/dev/null || true)
green=$(tput setaf 2 2>/dev/null || true)
yellow=$(tput setaf 3 2>/dev/null || true)
reset=$(tput sgr0 2>/dev/null || true)

step() { printf '\n%s%s%s\n' "$bold" "$1" "$reset"; }
info() { printf '%s%s%s\n' "$dim" "$1" "$reset"; }
good() { printf '%s✓%s %s\n' "$green" "$reset" "$1"; }
warn() { printf '%s!%s %s\n' "$yellow" "$reset" "$1"; }
fail() { printf '%s✗%s %s\n' "$red" "$reset" "$1"; }

die() { fail "$1"; exit 1; }

# Read a value, keeping any existing one when the user just presses enter.
ask() {                     # ask VARNAME "Prompt" [secret]
  local name=$1 prompt=$2 secret=${3:-} current=${!1:-} reply=
  if [ -n "$current" ]; then
    local shown="$current"
    [ -n "$secret" ] && shown="(already set)"
    printf '%s\n  %s[keep: %s]%s ' "$prompt" "$dim" "$shown" "$reset"
  else
    printf '%s\n  ' "$prompt"
  fi
  if [ -n "$secret" ]; then
    read -rs reply; echo
  else
    read -r reply
  fi
  if [ -n "$reply" ]; then
    printf -v "$name" '%s' "$reply"
  fi
  export "$name"
}

confirm() {                 # confirm "Question" -> 0 for yes
  local reply
  printf '%s [y/N] ' "$1"
  read -r reply
  [[ "$reply" =~ ^[Yy] ]]
}

PY=${PYTHON:-python3}

# ---------------------------------------------------------------- prereqs
step "Checking prerequisites"

command -v "$PY" >/dev/null || die "python3 not found. Install Python 3.10 or newer."
PYV=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' \
  || die "Python $PYV is too old; 3.10 or newer is needed."
good "Python $PYV"

HAVE_GH=1
if ! command -v gh >/dev/null; then
  HAVE_GH=0
  warn "The GitHub CLI (gh) is not installed, so secrets cannot be uploaded for you."
  info "Install it from https://cli.github.com and re-run, or add the secrets by hand."
elif ! gh auth status >/dev/null 2>&1; then
  HAVE_GH=0
  warn "gh is installed but not signed in. Run: gh auth login"
else
  good "GitHub CLI ready ($(gh api user --jq .login 2>/dev/null || echo 'signed in'))"
fi

REPO=""
if [ "$HAVE_GH" = "1" ]; then
  REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)
  [ -n "$REPO" ] && good "Repository: $REPO"
fi

# Load whatever is already configured so a re-run is painless. This goes
# through Python and shlex.quote rather than `source`, so a pasted secret
# containing shell metacharacters can never be executed.
if [ -f .env ]; then
  good "Found an existing .env; current values are offered as defaults."
  eval "$("$PY" - <<'PYEOF'
import shlex
KEYS = {
    "OURA_CLIENT_ID", "OURA_CLIENT_SECRET", "OURA_REFRESH_TOKEN",
    "MAIL_TO", "MAIL_FROM", "GMAIL_APP_PASSWORD", "OURA_SLEEP_NEED_HOURS",
}
for raw in open(".env", encoding="utf-8"):
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, _, value = line.partition("=")
    key = key.strip()
    if key in KEYS:
        print(f"export {key}={shlex.quote(value.strip().strip(chr(34)).strip(chr(39)))}")
PYEOF
)"
fi

# ------------------------------------------------------------- oura app
step "1/5 — Register an Oura application"
cat <<'TXT'
Oura has retired personal access tokens, so the dashboard signs in with OAuth.

  1. Open https://cloud.ouraring.com/oauth/applications
  2. Create a new application (any name, e.g. "My dashboard")
  3. In "Redirect URIs" paste exactly:

         http://localhost:8731/callback

  4. Save, then copy the Client ID and Client Secret below.
TXT
echo
ask OURA_CLIENT_ID     "Client ID:"
ask OURA_CLIENT_SECRET "Client secret:" secret
[ -n "${OURA_CLIENT_ID:-}" ]     || die "A client ID is required."
[ -n "${OURA_CLIENT_SECRET:-}" ] || die "A client secret is required."

# ----------------------------------------------------------------- email
step "2/5 — Gmail delivery"
cat <<'TXT'
Gmail blocks ordinary sign-in over SMTP, so the brief needs an App Password:
a 16-character code, not your normal password.

  1. Open https://myaccount.google.com/apppasswords
     (needs 2-Step Verification switched on)
  2. Create one called "Oura brief" and copy the code.
TXT
echo
ask MAIL_TO            "Send the brief to which address?"
ask MAIL_FROM          "Send it from which Gmail address?"
ask GMAIL_APP_PASSWORD "Gmail app password:" secret

# Google displays app passwords in groups of four; the spaces are cosmetic.
GMAIL_APP_PASSWORD=${GMAIL_APP_PASSWORD// /}
export GMAIL_APP_PASSWORD

ask OURA_SLEEP_NEED_HOURS "Your nightly sleep target in hours (press enter for 8):"
: "${OURA_SLEEP_NEED_HOURS:=8.0}"
export OURA_SLEEP_NEED_HOURS

# ------------------------------------------------------------ write .env
step "3/5 — Saving local settings"
# Written by Python from the environment, so no value passes through a shell
# parser or lands in the process list.
"$PY" - <<'PYEOF'
import os, pathlib, stat

KEYS = [
    "OURA_CLIENT_ID", "OURA_CLIENT_SECRET",
    "MAIL_TO", "MAIL_FROM", "GMAIL_APP_PASSWORD",
    "OURA_SLEEP_NEED_HOURS",
]
path = pathlib.Path(".env")
lines = ["# Written by setup.sh. Holds live credentials; gitignored."]
for key in KEYS:
    value = os.environ.get(key, "")
    lines.append(f'{key}="{value}"')
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
print("wrote", path)
PYEOF
good "Wrote .env (owner-only permissions)"

# --------------------------------------------------------------- consent
step "4/5 — Granting access to your Oura data"
info "A browser window will open for you to approve the connection."
echo
if ! (cd src && "$PY" -m oura_dashboard authorize); then
  die "Authorization did not complete. Re-run ./setup.sh to try again."
fi

REFRESH_TOKEN=$("$PY" - <<'PYEOF'
import json, pathlib
path = pathlib.Path("data/.oauth.json")
try:
    print(json.loads(path.read_text()).get("refresh_token") or "")
except Exception:
    print("")
PYEOF
)
[ -n "$REFRESH_TOKEN" ] || die "Could not read the refresh token from data/.oauth.json"
good "Got a refresh token"

# ------------------------------------------------------- github secrets
step "5/5 — Setting up the daily job"

if [ "$HAVE_GH" = "0" ] || [ -z "$REPO" ]; then
  warn "Skipping the GitHub setup because gh is unavailable."
  cat <<TXT

Add these six secrets by hand at
  Settings -> Secrets and variables -> Actions

  OURA_CLIENT_ID        $OURA_CLIENT_ID
  OURA_CLIENT_SECRET    (the client secret)
  OURA_REFRESH_TOKEN    $REFRESH_TOKEN
  MAIL_TO               $MAIL_TO
  MAIL_FROM             $MAIL_FROM
  GMAIL_APP_PASSWORD    (the app password)
  OURA_SECRETS_PAT      (see below)
TXT
else
  cat <<'TXT'
One more token. Oura refresh tokens are single-use: every exchange
invalidates the old one, so the daily job has to write the replacement back
into its own secret. That needs a GitHub token, because the token Actions
provides cannot update secrets.

  1. Open https://github.com/settings/personal-access-tokens/new
  2. Repository access: "Only select repositories" -> pick this repo
  3. Permissions -> Repository permissions -> Secrets: Read and write
  4. Generate, then paste it below.

Press enter to skip; the brief will still arrive, but it will tell you the
token could not be rotated and the next run will need attention.
TXT
  echo
  ask OURA_SECRETS_PAT "Fine-grained GitHub token:" secret

  echo
  info "Uploading secrets to $REPO ..."
  put_secret() {           # put_secret NAME VALUE
    if [ -z "$2" ]; then
      warn "skipped $1 (no value)"
      return
    fi
    if printf '%s' "$2" | gh secret set "$1" --repo "$REPO" --body-file - 2>/dev/null; then
      good "$1"
    else
      fail "could not set $1"
    fi
  }
  put_secret OURA_CLIENT_ID     "$OURA_CLIENT_ID"
  put_secret OURA_CLIENT_SECRET "$OURA_CLIENT_SECRET"
  put_secret OURA_REFRESH_TOKEN "$REFRESH_TOKEN"
  put_secret MAIL_TO            "$MAIL_TO"
  put_secret MAIL_FROM          "$MAIL_FROM"
  put_secret GMAIL_APP_PASSWORD "$GMAIL_APP_PASSWORD"
  put_secret OURA_SECRETS_PAT   "${OURA_SECRETS_PAT:-}"

  if [ "${OURA_SLEEP_NEED_HOURS}" != "8.0" ]; then
    gh variable set OURA_SLEEP_NEED_HOURS --repo "$REPO" \
      --body "$OURA_SLEEP_NEED_HOURS" >/dev/null 2>&1 \
      && good "OURA_SLEEP_NEED_HOURS variable"
  fi

  if confirm "Turn on GitHub Pages so the dashboard gets a link?"; then
    if gh api -X POST "repos/$REPO/pages" -f "build_type=workflow" >/dev/null 2>&1; then
      good "GitHub Pages enabled"
    else
      info "Pages may already be on, or needs enabling by hand at Settings -> Pages (Source: GitHub Actions)."
    fi
  fi
fi

# -------------------------------------------------------------- verify
step "Verifying"
echo
if (cd src && "$PY" -m oura_dashboard check); then
  VERIFIED=1
else
  VERIFIED=0
fi

step "Pulling your history and building the dashboard"
echo
(cd src && "$PY" -m oura_dashboard --verbose sync --days 120) || \
  warn "The first sync had trouble; run it again with: cd src && $PY -m oura_dashboard -v sync"
(cd src && "$PY" -m oura_dashboard build) || true

step "Done"
if [ "$VERIFIED" = "1" ]; then
  good "Everything is configured."
else
  warn "Some checks did not pass — see the list above."
fi
cat <<TXT

  Your dashboard   $(pwd)/out/index.html
  See the brief    cd src && $PY -m oura_dashboard brief
  Send it now      cd src && $PY -m oura_dashboard send
TXT
if [ -n "$REPO" ]; then
  cat <<TXT
  Run the daily job now, without waiting for the morning:
                   gh workflow run "Oura morning brief" --repo $REPO
TXT
fi
echo
info "The scheduled run is 11:00 UTC daily; change the cron in"
info ".github/workflows/oura-daily.yml to suit your timezone."
