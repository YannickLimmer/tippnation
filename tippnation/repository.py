from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import EventConfig, config_as_json
from .db import Database


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def load_points(db: Database, event_id: str) -> pd.DataFrame:
    rows = db.query(
        """
        SELECT p.*, m.kickoff_utc, m.stage, m.round_name, m.group_name,
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
        INSERT INTO bets (event_id, match_id, username, score_a, score_b, factor, submitted_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id, match_id, username) DO UPDATE SET
            score_a = excluded.score_a,
            score_b = excluded.score_b,
            factor = excluded.factor,
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

