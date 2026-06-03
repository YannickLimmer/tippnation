from __future__ import annotations

import argparse
import gzip
import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DEFAULT_EVENT_CONFIG, ROOT, load_event_config
from .db import Database, connect
from .secrets import get_database_settings


SKIPPED_TABLES = {"score_probabilities"}


@dataclass(frozen=True)
class SchemaItem:
    type: str
    name: str
    sql: str


@dataclass(frozen=True)
class TableBackup:
    name: str
    rows: int


@dataclass(frozen=True)
class BackupResult:
    path: Path
    tables: list[TableBackup]

    @property
    def total_rows(self) -> int:
        return sum(table.rows for table in self.tables)


def create_backup(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    output_root: Path = ROOT / "backup",
    event_folder: str | None = None,
    compress: bool = True,
) -> BackupResult:
    config = load_event_config(config_path)
    folder_name = _slug(event_folder or config.name)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = output_root / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    sqlite_path = output_dir / f"{folder_name}_{timestamp}.sqlite3"
    backup_path = sqlite_path.with_suffix(".sqlite3.gz") if compress else sqlite_path

    settings = get_database_settings()
    source = connect(settings)
    try:
        schema_items = _load_schema(source)
        table_items = [item for item in schema_items if item.type == "table" and item.name not in SKIPPED_TABLES]
        dependent_items = [
            item
            for item in schema_items
            if item.type != "table" and not _references_skipped_table(item.sql)
        ]

        with sqlite3.connect(sqlite_path) as target:
            target.execute("PRAGMA foreign_keys = OFF")
            for item in table_items:
                target.execute(item.sql)

            table_counts = [_copy_table(source, target, item.name) for item in table_items]

            for item in dependent_items:
                target.execute(item.sql)
            target.execute("PRAGMA foreign_keys = ON")
            target.execute("PRAGMA user_version = 1")
            target.commit()
            target.execute("VACUUM")
        if compress:
            _gzip_file(sqlite_path, backup_path)
            sqlite_path.unlink()
    except Exception:
        sqlite_path.unlink(missing_ok=True)
        backup_path.unlink(missing_ok=True)
        raise
    finally:
        source.close()

    return BackupResult(path=backup_path, tables=table_counts)


def _load_schema(db: Database) -> list[SchemaItem]:
    rows = db.query(
        """
        SELECT type, name, sql
        FROM sqlite_master
        WHERE sql IS NOT NULL
          AND name NOT LIKE 'sqlite_%'
          AND type IN ('table', 'index', 'trigger', 'view')
        ORDER BY
          CASE type
            WHEN 'table' THEN 0
            WHEN 'index' THEN 1
            WHEN 'trigger' THEN 2
            WHEN 'view' THEN 3
            ELSE 4
          END,
          name
        """
    )
    return [
        SchemaItem(type=str(row["type"]), name=str(row["name"]), sql=str(row["sql"]))
        for row in rows
        if row.get("sql")
    ]


def _copy_table(source: Database, target: sqlite3.Connection, table_name: str) -> TableBackup:
    quoted_table = _quote_identifier(table_name)
    rows = source.query(f"SELECT * FROM {quoted_table}")
    if not rows:
        return TableBackup(name=table_name, rows=0)

    columns = list(rows[0].keys())
    quoted_columns = ", ".join(_quote_identifier(column) for column in columns)
    placeholders = ", ".join("?" for _ in columns)
    target.executemany(
        f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})",
        [[_sqlite_value(row[column]) for column in columns] for row in rows],
    )
    return TableBackup(name=table_name, rows=len(rows))


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _sqlite_value(value: Any) -> Any:
    if isinstance(value, memoryview):
        return bytes(value)
    return value


def _gzip_file(source: Path, destination: Path) -> None:
    with source.open("rb") as source_file, gzip.open(destination, "wb", compresslevel=9) as destination_file:
        shutil.copyfileobj(source_file, destination_file)


def _references_skipped_table(sql: str) -> bool:
    lowered = sql.lower()
    return any(table.lower() in lowered for table in SKIPPED_TABLES)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug:
        raise ValueError("Event folder name cannot be empty.")
    return slug


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a timestamped local SQLite backup of the TippNation database.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_EVENT_CONFIG,
        help=f"Event config path. Defaults to {DEFAULT_EVENT_CONFIG}.",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT / "backup",
        help="Backup root directory. Defaults to ./backup.",
    )
    parser.add_argument(
        "--event-folder",
        help="Override the event folder name under the backup root. Defaults to the configured event name.",
    )
    parser.add_argument(
        "--uncompressed",
        action="store_true",
        help="Keep the backup as a plain .sqlite3 file instead of compressing it to .sqlite3.gz.",
    )
    args = parser.parse_args()

    result = create_backup(
        config_path=args.config,
        output_root=args.output_root,
        event_folder=args.event_folder,
        compress=not bool(args.uncompressed),
    )
    print(f"backup_path={result.path}")
    print(f"tables={len(result.tables)}")
    print(f"rows={result.total_rows}")
    for table in result.tables:
        print(f"table.{table.name}.rows={table.rows}")


if __name__ == "__main__":
    main()
