from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from .admin import compute_and_store_points, initialize_database, set_match_results
from .config import EventConfig, ROOT
from .db import Database, SqliteDatabase
from .odds import seed_synthetic_replay_odds


EURO_2024_CONFIG = ROOT / "data" / "events" / "euro_2024.json"
EURO_2024_SOURCE = ROOT / "agent" / "ec-2024.txt"
REPLAY_DB_DIR = ROOT / "data" / "replay"
REPLAY_ADMIN_PASSWORD = "admin"
REPLAY_USER_PASSWORD = "user"


@dataclass(frozen=True)
class ReplaySnapshot:
    key: str
    label: str
    now_utc: datetime
    description: str


@dataclass(frozen=True)
class ReplaySettings:
    event_key: str
    snapshot: ReplaySnapshot
    config_path: Path
    db_path: Path

    @property
    def cache_key(self) -> str:
        return f"{self.event_key}:{self.snapshot.key}"


EURO_2024_SNAPSHOTS: dict[str, ReplaySnapshot] = {
    "pre_tournament": ReplaySnapshot(
        key="pre_tournament",
        label="Before first match",
        now_utc=datetime(2024, 6, 14, 17, 0, tzinfo=timezone.utc),
        description="One hour before Germany vs Scotland.",
    ),
    "group_stage": ReplaySnapshot(
        key="group_stage",
        label="During group stage",
        now_utc=datetime(2024, 6, 20, 12, 0, tzinfo=timezone.utc),
        description="After the first 15 group matches, before the 20 June fixtures.",
    ),
    "playoffs": ReplaySnapshot(
        key="playoffs",
        label="During playoffs",
        now_utc=datetime(2024, 7, 6, 12, 0, tzinfo=timezone.utc),
        description="After two quarterfinals, before England vs Switzerland.",
    ),
    "post_final": ReplaySnapshot(
        key="post_final",
        label="After final",
        now_utc=datetime(2024, 7, 15, 10, 0, tzinfo=timezone.utc),
        description="The tournament is complete.",
    ),
}


TEAM_IDS = {
    "Albania": "ALB",
    "Austria": "AUT",
    "Belgium": "BEL",
    "Croatia": "CRO",
    "Czech Republic": "CZE",
    "Denmark": "DEN",
    "England": "ENG",
    "France": "FRA",
    "Georgia": "GEO",
    "Germany": "GER",
    "Hungary": "HUN",
    "Italy": "ITA",
    "Netherlands": "NED",
    "Poland": "POL",
    "Portugal": "POR",
    "Romania": "ROU",
    "Scotland": "SCO",
    "Serbia": "SRB",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "Spain": "ESP",
    "Switzerland": "SUI",
    "Turkey": "TUR",
    "Ukraine": "UKR",
}


FAVORITES = {
    "Claus": "GEO",
    "Gina": "GER",
    "Linus": "ESP",
    "Liv": "SCO",
    "Mama": "BEL",
    "Noel": "POR",
    "Oma": "ESP",
    "Opa": "GER",
    "Papa": "CRO",
    "Vroni": "ITA",
    "Yannick": "ENG",
}


def build_replay_settings(replay: str | None, snapshot_key: str | None) -> ReplaySettings | None:
    if not replay:
        return None
    normalized = replay.strip().lower().replace("-", "_")
    if normalized not in {"euro_2024", "euros_2024", "ec_2024"}:
        return None

    key = (snapshot_key or "group_stage").strip().lower().replace("-", "_")
    snapshot = EURO_2024_SNAPSHOTS.get(key, EURO_2024_SNAPSHOTS["group_stage"])
    db_path = REPLAY_DB_DIR / f"euro_2024_{snapshot.key}.sqlite3"
    return ReplaySettings(
        event_key="euro_2024",
        snapshot=snapshot,
        config_path=EURO_2024_CONFIG,
        db_path=db_path,
    )


def replay_settings_for_snapshot(snapshot_key: str) -> ReplaySettings:
    key = snapshot_key.strip().lower().replace("-", "_")
    if key not in EURO_2024_SNAPSHOTS:
        raise ValueError(f"Unknown Euro 2024 replay snapshot: {snapshot_key}")
    settings = build_replay_settings("euro_2024", key)
    if settings is None:
        raise ValueError(f"Could not build Euro 2024 replay snapshot: {snapshot_key}")
    return settings


def reset_replay_database(settings: ReplaySettings, config: EventConfig) -> Database:
    if settings.db_path.exists():
        settings.db_path.unlink()
    db = SqliteDatabase(str(settings.db_path))
    _seed_euro_2024(db, config, settings.snapshot.now_utc)
    return db


def _seed_euro_2024(db: Database, config: EventConfig, replay_now: datetime) -> None:
    source_rows = _load_source_rows()
    usernames = sorted({row["Name"] for row in source_rows})
    initialize_database(db, config, usernames)
    _seed_favorites(db, config)
    _seed_results(db, config, source_rows, replay_now)
    _seed_bets(db, config, source_rows, replay_now)
    seed_synthetic_replay_odds(db, config, replay_now)
    compute_and_store_points(db, config)


def _load_source_rows() -> list[dict[str, str]]:
    with EURO_2024_SOURCE.open(encoding="utf-8", newline="") as source:
        return list(csv.DictReader(source))


def _seed_favorites(db: Database, config: EventConfig) -> None:
    rows = [
        (config.event_id, username, team_id, "2024-06-13T12:00:00+00:00")
        for username, team_id in FAVORITES.items()
        if team_id in config.teams
    ]
    db.executemany(
        """
        INSERT INTO favorites (event_id, username, team_id, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(event_id, username) DO UPDATE SET
            team_id = excluded.team_id,
            updated_at = excluded.updated_at
        """,
        rows,
    )


def _seed_results(db: Database, config: EventConfig, source_rows: list[dict[str, str]], replay_now: datetime) -> None:
    source_by_match = _source_by_match(source_rows)
    result_rows = []
    for match in config.matches:
        source = source_by_match[match.match_id]
        result = _result_for_source_row(source)
        is_completed = match.kickoff_utc <= replay_now and result is not None
        result_rows.append(
            {
                "match_id": match.match_id,
                "result_a": result[0] if is_completed else None,
                "result_b": result[1] if is_completed else None,
                "status": "completed" if is_completed else "scheduled",
            }
        )
    set_match_results(db, config.event_id, pd.DataFrame(result_rows))


def _seed_bets(db: Database, config: EventConfig, source_rows: list[dict[str, str]], replay_now: datetime) -> None:
    match_by_id = {match.match_id: match for match in config.matches}
    rows = []
    for row in source_rows:
        match_id = _source_match_id(row)
        match = match_by_id[match_id]
        submitted_at = _made_up_submitted_at(match.kickoff_utc, row["Name"])
        if submitted_at > replay_now or not row["ScoreA"] or not row["ScoreB"] or not row["Factor"]:
            continue
        rows.append(
            (
                config.event_id,
                match_id,
                row["Name"],
                int(row["ScoreA"]),
                int(row["ScoreB"]),
                int(row["Factor"]),
                int(row["Kanonenwilli"] or 0),
                submitted_at.isoformat(),
            )
        )
    if not rows:
        return
    db.executemany(
        """
        INSERT INTO bets (
            event_id, match_id, username, score_a, score_b,
            factor, kanonenwilli, submitted_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_id, match_id, username) DO UPDATE SET
            score_a = excluded.score_a,
            score_b = excluded.score_b,
            factor = excluded.factor,
            kanonenwilli = excluded.kanonenwilli,
            submitted_at = excluded.submitted_at
        """,
        rows,
    )


def _source_by_match(source_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in source_rows:
        rows.setdefault(_source_match_id(row), row)
    return rows


def _source_match_id(row: dict[str, str]) -> str:
    return f"M{int(row['Unnamed: 0']) + 1:02d}"


def _result_for_source_row(row: dict[str, str]) -> tuple[int, int] | None:
    if row["TeamA"] == "Spain" and row["TeamB"] == "England":
        return (2, 1)
    if not row["ResultA"] or not row["ResultB"]:
        return None
    return int(row["ResultA"]), int(row["ResultB"])


def _made_up_submitted_at(kickoff_utc: datetime, username: str) -> datetime:
    minute_offset = sum(ord(char) for char in username) % 180
    return kickoff_utc - timedelta(hours=6, minutes=minute_offset)
