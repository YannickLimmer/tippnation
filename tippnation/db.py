from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from .config import ROOT
from .secrets import DatabaseSettings


class Database(Protocol):
    def execute(self, sql: str, params: Sequence[Any] = ()) -> None: ...
    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]: ...
    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None: ...


class SqliteDatabase:
    def __init__(self, path: str) -> None:
        db_path = Path(path)
        if not db_path.is_absolute():
            db_path = ROOT / db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self.connection:
            self.connection.execute(sql, tuple(params))

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        cursor = self.connection.execute(sql, tuple(params))
        return [dict(row) for row in cursor.fetchall()]

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.connection:
            self.connection.executemany(sql, [tuple(row) for row in rows])


class LibsqlDatabase:
    def __init__(self, url: str, auth_token: str | None) -> None:
        try:
            import libsql_client
        except ImportError as exc:
            raise RuntimeError("Install libsql-client to use Turso/libSQL.") from exc
        self.client = libsql_client.create_client_sync(url=url, auth_token=auth_token)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self.client.execute(sql, list(params))

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        result = self.client.execute(sql, list(params))
        columns = list(getattr(result, "columns", []) or [])
        rows = []
        for row in getattr(result, "rows", []):
            if hasattr(row, "asdict"):
                rows.append(dict(row.asdict()))
            elif isinstance(row, Mapping):
                rows.append(dict(row))
            else:
                rows.append(dict(zip(columns, row)))
        return rows

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        for row in rows:
            self.execute(sql, row)


def connect(settings: DatabaseSettings) -> Database:
    if settings.url.startswith("libsql://") or settings.url.startswith("https://"):
        return LibsqlDatabase(settings.url, settings.auth_token)
    return SqliteDatabase(settings.url)


SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        timezone TEXT NOT NULL,
        config_json TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS players (
        username TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        active INTEGER NOT NULL DEFAULT 1,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS favorites (
        event_id TEXT NOT NULL,
        username TEXT NOT NULL,
        team_id TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (event_id, username)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS matches (
        event_id TEXT NOT NULL,
        match_id TEXT NOT NULL,
        sort_order INTEGER NOT NULL,
        kickoff_utc TEXT NOT NULL,
        stage TEXT NOT NULL,
        round_name TEXT NOT NULL,
        group_name TEXT,
        team_a_id TEXT NOT NULL,
        team_b_id TEXT NOT NULL,
        team_a_name TEXT NOT NULL,
        team_b_name TEXT NOT NULL,
        venue TEXT,
        result_a INTEGER,
        result_b INTEGER,
        status TEXT NOT NULL DEFAULT 'scheduled',
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (event_id, match_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bets (
        event_id TEXT NOT NULL,
        match_id TEXT NOT NULL,
        username TEXT NOT NULL,
        score_a INTEGER NOT NULL,
        score_b INTEGER NOT NULL,
        factor INTEGER NOT NULL,
        kanonenwilli INTEGER,
        submitted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (event_id, match_id, username)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS points (
        event_id TEXT NOT NULL,
        match_id TEXT NOT NULL,
        username TEXT NOT NULL,
        base INTEGER NOT NULL,
        fbase INTEGER NOT NULL,
        exotic INTEGER NOT NULL,
        favorite INTEGER NOT NULL,
        kanonenwilli INTEGER NOT NULL,
        final INTEGER NOT NULL,
        computed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (event_id, match_id, username)
    )
    """,
)


def ensure_schema(db: Database) -> None:
    for statement in SCHEMA:
        db.execute(statement)

