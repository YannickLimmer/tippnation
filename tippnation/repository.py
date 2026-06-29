from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import EventConfig, config_as_json
from .db import Database


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _iso(value: datetime | pd.Timestamp | str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime().isoformat()
    return value.isoformat()


def sync_event_config(db: Database, config: EventConfig) -> None:
    db.execute(
        """
        INSERT INTO events (event_id, name, timezone, config_json, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            name = excluded.name,
            timezone = excluded.timezone,
            config_json = excluded.config_json,
            updated_at = excluded.updated_at
        """,
        (config.event_id, config.name, config.timezone, config_as_json(config), iso_now()),
    )
    db.executemany(
        """
        INSERT INTO matches (
            event_id, match_id, sort_order, kickoff_utc, stage, round_name,
            group_name, team_a_id, team_b_id, team_a_name, team_b_name, venue
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id, match_id) DO UPDATE SET
            sort_order = excluded.sort_order,
            kickoff_utc = excluded.kickoff_utc,
            stage = excluded.stage,
            round_name = excluded.round_name,
            group_name = excluded.group_name,
            team_a_id = excluded.team_a_id,
            team_b_id = excluded.team_b_id,
            team_a_name = excluded.team_a_name,
            team_b_name = excluded.team_b_name,
            venue = excluded.venue,
            updated_at = CURRENT_TIMESTAMP
        """,
        [
            (
                config.event_id,
                match.match_id,
                match.sort_order,
                match.kickoff_utc.isoformat(),
                match.stage,
                match.round_name,
                match.group_name,
                match.team_a_id,
                match.team_b_id,
                match.team_a_name,
                match.team_b_name,
                match.venue,
            )
            for match in config.matches
        ],
    )
    from .knockout import sync_knockout_advancement

    sync_knockout_advancement(db, config)


def event_config_is_current(db: Database, config: EventConfig) -> bool:
    rows = db.query("SELECT config_json FROM events WHERE event_id = ?", (config.event_id,))
    if not rows or str(rows[0].get("config_json") or "") != config_as_json(config):
        return False

    static_matches = [match for match in config.matches if _is_static_config_match(match)]
    if not static_matches:
        return True

    db_rows = db.query(
        """
        SELECT match_id, kickoff_utc, stage, round_name, group_name,
               team_a_id, team_b_id, team_a_name, team_b_name, venue
        FROM matches
        WHERE event_id = ?
        """,
        (config.event_id,),
    )
    by_match_id = {str(row["match_id"]): row for row in db_rows}
    for match in static_matches:
        row = by_match_id.get(match.match_id)
        if row is None:
            return False
        expected = {
            "kickoff_utc": match.kickoff_utc.isoformat(),
            "stage": match.stage,
            "round_name": match.round_name,
            "group_name": match.group_name,
            "team_a_id": match.team_a_id,
            "team_b_id": match.team_b_id,
            "team_a_name": match.team_a_name,
            "team_b_name": match.team_b_name,
            "venue": match.venue,
        }
        for key, expected_value in expected.items():
            if _normalized_db_value(row.get(key)) != _normalized_db_value(expected_value):
                return False
    return True


def _is_static_config_match(match: Any) -> bool:
    return not (_is_dynamic_fixture_label(match.team_a_name) or _is_dynamic_fixture_label(match.team_b_name))


def _is_dynamic_fixture_label(value: str | None) -> bool:
    label = str(value or "").casefold()
    return label.startswith(("winner match ", "loser match ", "round of 32 "))


def _normalized_db_value(value: Any) -> str:
    return "" if value is None else str(value)


def sync_players(db: Database, usernames: Iterable[str]) -> None:
    db.executemany(
        """
        INSERT INTO players (username, display_name, active, updated_at)
        VALUES (?, ?, 1, ?)
        ON CONFLICT(username) DO UPDATE SET
            display_name = excluded.display_name,
            active = 1,
            updated_at = excluded.updated_at
        """,
        [(username, username, iso_now()) for username in sorted(set(usernames))],
    )


def list_players(db: Database) -> list[str]:
    rows = db.query("SELECT username FROM players WHERE active = 1 ORDER BY username")
    return [str(row["username"]) for row in rows]


def load_matches(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT * FROM matches
        WHERE event_id = ?
        ORDER BY sort_order
        """,
        (event_id,),
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    return df


def load_bets(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query("SELECT * FROM bets WHERE event_id = ?", (event_id,))
    return pd.DataFrame(rows)


def load_user_bets(db: Database, event_id: str, username: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT *
        FROM bets
        WHERE event_id = ? AND username = ?
        """,
        (event_id, username),
    )
    return pd.DataFrame(rows)


def load_match_bet_usernames(db: Database, event_id: str, match_id: str) -> list[str]:
    rows = db.query(
        """
        SELECT username
        FROM bets
        WHERE event_id = ? AND match_id = ?
        """,
        (event_id, match_id),
    )
    return [str(row["username"]) for row in rows]


def load_points(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT p.*, m.sort_order, m.kickoff_utc, m.stage, m.round_name, m.group_name,
               m.team_a_name, m.team_b_name, m.result_a, m.result_b
        FROM points p
        JOIN matches m ON m.event_id = p.event_id AND m.match_id = p.match_id
        WHERE p.event_id = ?
        ORDER BY m.sort_order, p.username
        """,
        (event_id,),
    )
    df = pd.DataFrame(rows)
    if not df.empty:
        df["kickoff_utc"] = pd.to_datetime(df["kickoff_utc"], utc=True)
    return df


def load_favorites(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT f.username, f.team_id
        FROM favorites f
        JOIN players p ON p.username = f.username
        WHERE f.event_id = ? AND p.active = 1
        ORDER BY f.username
        """,
        (event_id,),
    )
    return pd.DataFrame(rows)


def set_favorite(db: Database, event_id: str, username: str, team_id: str) -> None:
    db.execute(
        """
        INSERT INTO favorites (event_id, username, team_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(event_id, username) DO UPDATE SET
            team_id = excluded.team_id,
            updated_at = excluded.updated_at
        """,
        (event_id, username, team_id, iso_now()),
    )


def upsert_bets(db: Database, event_id: str, username: str, rows: list[dict[str, Any]]) -> None:
    db.executemany(
        """
        INSERT INTO bets (event_id, match_id, username, score_a, score_b, factor, auto_generated, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(event_id, match_id, username) DO UPDATE SET
            score_a = excluded.score_a,
            score_b = excluded.score_b,
            factor = excluded.factor,
            auto_generated = 0,
            submitted_at = excluded.submitted_at
        """,
        [
            (
                event_id,
                row["match_id"],
                username,
                int(row["score_a"]),
                int(row["score_b"]),
                int(row["factor"]),
                iso_now(),
            )
            for row in rows
        ],
    )


def insert_auto_bets(db: Database, event_id: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    before = _existing_bet_keys(db, event_id, rows)
    db.executemany(
        """
        INSERT OR IGNORE INTO bets (
            event_id, match_id, username, score_a, score_b, factor,
            kanonenwilli, auto_generated, submitted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, NULL, 1, ?)
        """,
        [
            (
                event_id,
                row["match_id"],
                row["username"],
                int(row["score_a"]),
                int(row["score_b"]),
                int(row["factor"]),
                str(row["submitted_at"]),
            )
            for row in rows
        ],
    )
    after = _existing_bet_keys(db, event_id, rows)
    return len(after - before)


def _existing_bet_keys(db: Database, event_id: str, rows: list[dict[str, Any]]) -> set[tuple[str, str]]:
    keys = {(str(row["match_id"]), str(row["username"])) for row in rows}
    if not keys:
        return set()
    values = []
    for match_id, username in keys:
        values.extend([match_id, username])
    predicate = " OR ".join("(match_id = ? AND username = ?)" for _ in keys)
    existing = db.query(
        f"""
        SELECT match_id, username
        FROM bets
        WHERE event_id = ? AND ({predicate})
        """,
        (event_id, *values),
    )
    return {(str(row["match_id"]), str(row["username"])) for row in existing}


def update_results(db: Database, event_id: str, rows: list[dict[str, Any]]) -> None:
    db.executemany(
        """
        UPDATE matches
        SET result_a = ?, result_b = ?, status = ?, updated_at = ?
        WHERE event_id = ? AND match_id = ?
        """,
        [
            (
                None if row.get("result_a") is None or pd.isna(row.get("result_a")) else int(row["result_a"]),
                None if row.get("result_b") is None or pd.isna(row.get("result_b")) else int(row["result_b"]),
                str(row.get("status") or "scheduled"),
                iso_now(),
                event_id,
                row["match_id"],
            )
            for row in rows
        ],
    )


def replace_points(db: Database, event_id: str, points: pd.DataFrame) -> None:
    db.execute("DELETE FROM points WHERE event_id = ?", (event_id,))
    if points.empty:
        return
    db.executemany(
        """
        INSERT INTO points (
            event_id, match_id, username, base, fbase, exotic,
            favorite, kanonenwilli, final, computed_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                event_id,
                row.match_id,
                row.username,
                int(row.base),
                int(row.fbase),
                int(row.exotic),
                int(row.favorite),
                int(row.kanonenwilli_points),
                int(row.final),
                iso_now(),
            )
            for row in points.itertuples(index=False)
        ],
    )


def update_kanonenwilli(db: Database, event_id: str, values: pd.DataFrame) -> None:
    if values.empty:
        return
    db.executemany(
        """
        UPDATE bets
        SET kanonenwilli = ?
        WHERE event_id = ? AND match_id = ? AND username = ?
        """,
        [
            (int(row.kanonenwilli), event_id, row.match_id, row.username)
            for row in values.itertuples(index=False)
        ],
    )


def acquire_odds_refresh_lock(
    db: Database,
    lock_key: str,
    owner: str,
    acquired_at: datetime,
    expires_at: datetime,
) -> bool:
    now_value = acquired_at.isoformat()
    db.execute("DELETE FROM odds_refresh_locks WHERE lock_key = ? AND expires_at <= ?", (lock_key, now_value))
    db.execute(
        """
        INSERT OR IGNORE INTO odds_refresh_locks (lock_key, acquired_at, expires_at, owner)
        VALUES (?, ?, ?, ?)
        """,
        (lock_key, acquired_at.isoformat(), expires_at.isoformat(), owner),
    )
    rows = db.query("SELECT owner FROM odds_refresh_locks WHERE lock_key = ?", (lock_key,))
    return bool(rows and rows[0]["owner"] == owner)


def release_odds_refresh_lock(db: Database, lock_key: str, owner: str) -> None:
    db.execute("DELETE FROM odds_refresh_locks WHERE lock_key = ? AND owner = ?", (lock_key, owner))


def insert_odds_snapshot(
    db: Database,
    *,
    event_id: str,
    match_id: str,
    snapshot_id: str,
    provider: str,
    provider_event_id: str | None,
    captured_at: datetime,
    kickoff_utc: datetime,
    market_count: int,
    score_max: int,
    diagnostics: dict[str, Any],
    markets: list[dict[str, Any]],
    probabilities: pd.DataFrame,
) -> None:
    db.execute(
        """
        INSERT INTO odds_snapshots (
            snapshot_id, event_id, match_id, provider, provider_event_id,
            captured_at, kickoff_utc, market_count, score_max,
            diagnostics_json, markets_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(snapshot_id) DO UPDATE SET
            diagnostics_json = excluded.diagnostics_json,
            markets_json = excluded.markets_json,
            created_at = excluded.created_at
        """,
        (
            snapshot_id,
            event_id,
            match_id,
            provider,
            provider_event_id,
            captured_at.isoformat(),
            kickoff_utc.isoformat(),
            int(market_count),
            int(score_max),
            json.dumps(diagnostics, sort_keys=True),
            json.dumps(markets, sort_keys=True),
            iso_now(),
        ),
    )
    db.execute("DELETE FROM score_probabilities WHERE snapshot_id = ?", (snapshot_id,))
    if probabilities.empty:
        return
    db.executemany(
        """
        INSERT INTO score_probabilities (
            snapshot_id, event_id, match_id, score_a, score_b, probability
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                snapshot_id,
                event_id,
                match_id,
                int(row.score_a),
                int(row.score_b),
                float(row.probability),
            )
            for row in probabilities.itertuples(index=False)
        ],
    )


def lock_latest_pregame_odds(db: Database, event_id: str, now: datetime) -> int:
    matches = db.query(
        """
        SELECT match_id, kickoff_utc
        FROM matches
        WHERE event_id = ? AND kickoff_utc <= ?
        """,
        (event_id, now.isoformat()),
    )
    locked = 0
    for match in matches:
        existing = db.query(
            "SELECT snapshot_id FROM pregame_odds_locks WHERE event_id = ? AND match_id = ?",
            (event_id, match["match_id"]),
        )
        if existing:
            continue
        snapshots = db.query(
            """
            SELECT snapshot_id, captured_at
            FROM odds_snapshots
            WHERE event_id = ? AND match_id = ? AND captured_at < ?
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            (event_id, match["match_id"], match["kickoff_utc"]),
        )
        if not snapshots:
            continue
        snapshot = snapshots[0]
        db.execute(
            """
            INSERT INTO pregame_odds_locks (
                event_id, match_id, snapshot_id, captured_at, locked_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(event_id, match_id) DO NOTHING
            """,
            (event_id, match["match_id"], snapshot["snapshot_id"], snapshot["captured_at"], now.isoformat()),
        )
        locked += 1
    return locked


def latest_odds_captured_at(db: Database, event_id: str, match_ids: list[str] | None = None) -> datetime | None:
    params: list[Any] = [event_id]
    clause = ""
    if match_ids:
        clause = f" AND match_id IN ({','.join('?' for _ in match_ids)})"
        params.extend(match_ids)
    rows = db.query(
        f"""
        SELECT MAX(captured_at) AS captured_at
        FROM odds_snapshots
        WHERE event_id = ?{clause}
        """,
        tuple(params),
    )
    value = rows[0].get("captured_at") if rows else None
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def latest_odds_captured_at_for_match(db: Database, event_id: str, match_id: str) -> datetime | None:
    rows = db.query(
        """
        SELECT MAX(captured_at) AS captured_at
        FROM odds_snapshots
        WHERE event_id = ? AND match_id = ?
        """,
        (event_id, match_id),
    )
    value = rows[0].get("captured_at") if rows else None
    return datetime.fromisoformat(str(value)) if value else None


def load_locked_score_probabilities(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT
            sp.event_id, sp.match_id, sp.score_a, sp.score_b, sp.probability,
            l.snapshot_id, l.captured_at
        FROM pregame_odds_locks l
        JOIN score_probabilities sp ON sp.snapshot_id = l.snapshot_id
        WHERE l.event_id = ?
        """,
        (event_id,),
    )
    return pd.DataFrame(rows)


def load_display_score_probabilities(
    db: Database,
    event_id: str,
    match_id: str,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, dict[str, Any] | None]:
    locked = db.query(
        """
        SELECT s.*
        FROM pregame_odds_locks l
        JOIN odds_snapshots s ON s.snapshot_id = l.snapshot_id
        WHERE l.event_id = ? AND l.match_id = ?
        LIMIT 1
        """,
        (event_id, match_id),
    )
    if locked:
        snapshot = locked[0]
    else:
        params: list[Any] = [event_id, match_id]
        now_clause = ""
        if now is not None:
            now_clause = " AND captured_at <= ?"
            params.append(now.isoformat())
        rows = db.query(
            f"""
            SELECT *
            FROM odds_snapshots
            WHERE event_id = ? AND match_id = ?{now_clause}
            ORDER BY captured_at DESC
            LIMIT 1
            """,
            tuple(params),
        )
        snapshot = rows[0] if rows else None
    if snapshot is None:
        return pd.DataFrame(columns=["score_a", "score_b", "probability"]), None

    probability_rows = db.query(
        """
        SELECT score_a, score_b, probability
        FROM score_probabilities
        WHERE snapshot_id = ?
        ORDER BY score_a, score_b
        """,
        (snapshot["snapshot_id"],),
    )
    metadata = dict(snapshot)
    for key in ("diagnostics_json", "markets_json"):
        try:
            metadata[key.removesuffix("_json")] = json.loads(str(metadata[key]))
        except (KeyError, json.JSONDecodeError, TypeError):
            metadata[key.removesuffix("_json")] = None
    return pd.DataFrame(probability_rows), metadata
