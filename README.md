# TippNation

TippNation is a small Streamlit betting game for a closed World Cup group.

## Architecture

- `app.py` contains the Streamlit UI only.
- `tippnation/db.py` supports local SQLite and Turso/libSQL.
- `tippnation/admin.py` exposes Python admin functions for database initialization, result updates, and point computation.
- `tippnation/odds_cli.py` refreshes Betfair odds from a local machine and writes snapshots to the configured database.
- `tippnation/scoring.py` contains the point rules and stores computed results in the database.
- `data/events/world_cup_2026.json` is the default World Cup 2026 event bundle.
- `data/events/international_friendlies_trial_2026.json` is the completed temporary trial event.
- `docs/` contains user-facing manuals loaded by the app help tab.
- `legacy/` contains the old CSV/Sheets implementation.

## Secrets

Users are still managed through Streamlit secrets. Supported formats:

```toml
[Admin]
Password = "admin-password"

[Yannick]
Password = "user-password"

[turso]
url = "libsql://tippster-yannicklimmer.aws-eu-west-1.turso.io"
auth_token = "..."

[betfair]
app_key = "..."
username = "..."
password = "..."
cert_base64 = "..."
key_base64 = "..."
# Optional fallback when certificate login is not configured:
session_token = "..."
```

Environment variables `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are also supported. For CI, `TIPPNATION_SECRETS_TOML` or `TIPPNATION_SECRETS` may contain the full TOML secrets document. If no Turso URL is configured, the app uses `data/tippnation.sqlite3`.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app initializes and syncs the configured event and secret-backed users on startup. Admin actions in the app can update match results and recompute point tables into SQLite/Turso.

## Local Odds Refresh

Streamlit Cloud cannot reach Betfair reliably, so market odds are refreshed locally
and persisted to Turso. The deployed app only reads the latest stored odds and locks
the most recent pre-kickoff snapshot after each match starts.

Refresh odds for the current default event using the normal cadence:

```bash
python -m tippnation.odds_cli
```

Force a refresh for the next stage/round:

```bash
python -m tippnation.odds_cli --force
```

Force every upcoming match in the event:

```bash
python -m tippnation.odds_cli --force --all-upcoming
```

## Local Result Polling

Live and final scores can be filled from API-FOOTBALL or TheSportsDB by running a
lightweight local poller. It first checks the event config and
`data/result_poll_state.json`; if no match is locally due, it does not connect to
the database or call an external API. When a match is due, it checks only those
match rows in the database so manually entered results are respected. Only
due matches in the live/final-settle window trigger provider API calls. API-FOOTBALL
matches are checked from kickoff until four hours after kickoff; whenever the
stored score changes, points are recomputed. After the four-hour window, use
`--force` or manual admin entry for any stragglers.

Run once:

```bash
python -m tippnation.results_cli
```

Run every 5 minutes from cron:

```cron
*/5 * * * * cd /path/to/tippnation && /usr/bin/python3 -m tippnation.results_cli --strict --provider auto --max-api-requests 2 --api-football-daily-budget 500 >> /path/to/tippnation/backup/result-poller.log 2>&1
```

Use `--dry-run` to test matching without writing results, points, or local state.
Use `--backfill` to query every past fixture in the event config that still has
no stored score, regardless of the normal live/final-settle window.
`--provider auto` prefers API-FOOTBALL when `API_FOOTBALL_KEY` is configured and
the event has `api_football` metadata; otherwise it falls back to TheSportsDB.
API-FOOTBALL event configs can include `api_football.league_id`, `season`, and
per-match `api_football_fixture_id` values. The World Cup event uses
`league_id = 1` and `season = 2026`; add per-match fixture IDs once verified.
The friendlies trial has a complete
API-FOOTBALL map: `league_id = 10`, `season = 2026`, and all 28 fixture IDs.
With fixture IDs, up to 20 matches are refreshed in one API request. TheSportsDB's
public v1 free key defaults to `123`; pass `--api-key` if you use a personal key.

API-FOOTBALL currently has 7500 requests/day available, but production cron should
still stay conservative. The poller stores local API-FOOTBALL request usage in
`data/result_poll_state.json` and refuses calls after
`--api-football-daily-budget`.

Penalty shootouts use TippNation's convention: the result is the score after 120
minutes plus one goal for the shootout winner.

## GitHub Actions Odds Refresh

`.github/workflows/betfair-odds.yml` runs `python -m tippnation.odds_cli --strict` every hour at minute 45 UTC. Each run logs in to Betfair with certificate authentication when `BETFAIR_USERNAME`, `BETFAIR_PASSWORD`, and cert material are configured, then requests a session keep-alive before it decides whether odds are due. In strict mode, missing credentials, certificate login failures, keep-alive failures, and refresh errors fail the Actions run instead of only printing a warning.

Create one repository secret named `TIPPNATION_SECRETS` whose value is the complete local `.secrets` TOML content, including Turso and Betfair sections. The workflow exposes that value only as `TIPPNATION_SECRETS_TOML` for the Python process; it is not written to the repository checkout. Alternatively, individual repository secrets named `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `BETFAIR_APP_KEY`, `BETFAIR_USERNAME`, `BETFAIR_PASSWORD`, `BETFAIR_CERT_BASE64`, and `BETFAIR_KEY_BASE64` are supported, along with fallback `BETFAIR_SESSION` and older `TURSO_TOKEN`, `BF_TOKEN`, and `BF_SESSION` names.

When individual cert secrets are present, the workflow restores them to `certs/betfair.crt` and `certs/betfair.key` for the run only. The `certs/` directory is ignored by git. When the cert base64 values are supplied inside `TIPPNATION_SECRETS`, the Python CLI decodes them into a temporary directory instead.

Test Betfair certificate login and keep-alive without touching Turso:

```bash
python -m tippnation.odds_cli --auth-check --strict
```

The workflow can also be started manually from the GitHub Actions tab:

- Set `auth_check` to test only Betfair certificate login and keep-alive without touching Turso.
- Leave `force` off to use the normal one-hour/five-hour/final-hour cadence.
- Set `force` to refresh the next upcoming stage immediately.
- Set both `force` and `all_upcoming` to refresh every upcoming match in the configured event.

## Local Euro 2024 Replay

Euro 2024 replay mode is a local development aid for testing rule changes against a historical tournament state. It never uses Turso. Each local replay launch creates a scratch SQLite database under `data/replay/` and seeds it from `agent/ec-2024.txt` plus `data/events/euro_2024.json`.

```bash
TIPPNATION_REPLAY=euro_2024 TIPPNATION_REPLAY_SNAPSHOT=group_stage streamlit run app.py
```

Supported snapshots:

- `pre_tournament`: 2024-06-14 17:00 UTC, before Germany vs Scotland.
- `group_stage`: 2024-06-20 12:00 UTC, during the group stage.
- `playoffs`: 2024-07-06 12:00 UTC, during the quarterfinals.
- `post_final`: 2024-07-15 10:00 UTC, after the final.

You can also use query parameters, for example `?replay=euro_2024&snapshot=playoffs`. In replay mode, every local user can log in with password `user`, and the admin tab uses password `admin`.
