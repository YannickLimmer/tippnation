# TippNation

TippNation is a small Streamlit betting game for a closed World Cup group.

## Architecture

- `app.py` contains the Streamlit UI only.
- `tippnation/db.py` supports local SQLite and Turso/libSQL.
- `tippnation/admin.py` exposes Python admin functions for database initialization, result updates, and point computation.
- `tippnation/scoring.py` contains the point rules and stores computed results in the database.
- `data/events/world_cup_2026.json` is the checked-in World Cup 2026 event bundle. It contains rules, teams, and fixture templates, but no user data.

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
```

Environment variables `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are also supported. If no Turso URL is configured, the app uses `data/tippnation.sqlite3`.

## Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app initializes and syncs the configured event and secret-backed users on startup. Admin actions in the app can update match results and recompute point tables into SQLite/Turso.

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
