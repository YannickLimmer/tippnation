from __future__ import annotations

import argparse
import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pandas as pd

from .config import DEFAULT_EVENT_CONFIG, EventConfig, MatchConfig, ROOT, load_event_config
from .db import Database, ensure_schema
from .repository import (
    acquire_odds_refresh_lock,
    insert_auto_bets,
    load_locked_score_probabilities,
    lock_latest_pregame_odds,
    release_odds_refresh_lock,
    sync_event_config,
)


DEFAULT_STATE_PATH = ROOT / "data" / "autobet_state.json"
DEFAULT_LOOKBACK = timedelta(days=2)
LOCK_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class AutoBetResult:
    checked_db: bool
    candidate_matches: int
    processed_matches: int
    generated_bets: int
    skipped_matches: int
    skipped_reason: str | None = None


def fill_missing_bets(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    state_path: Path = DEFAULT_STATE_PATH,
    now: datetime | None = None,
    lookback: timedelta = DEFAULT_LOOKBACK,
    backfill: bool = False,
    dry_run: bool = False,
    verbose: bool = True,
) -> AutoBetResult:
    current_time = _to_utc(now or datetime.now(timezone.utc))
    config = load_event_config(config_path)
    state = _load_state(state_path)
    candidates = _local_candidates(config, state, current_time, None if backfill else lookback)
    _log(verbose, f"event_id={config.event_id}")
    _log(verbose, f"mode=autobet backfill={backfill} dry_run={dry_run} now={current_time.isoformat()}")
    _log(verbose, f"local_candidate_matches={len(candidates)}")
    if not candidates:
        return AutoBetResult(
            checked_db=False,
            candidate_matches=0,
            processed_matches=0,
            generated_bets=0,
            skipped_matches=0,
            skipped_reason="No newly-started unprocessed matches.",
        )

    _log(verbose, "stage=database_connect")
    from .db import connect
    from .secrets import get_database_settings

    db = connect(get_database_settings())
    owner = f"autobet-{uuid4()}"
    lock_key = f"{config.event_id}:auto-bets"
    try:
        ensure_schema(db)
        sync_event_config(db, config)
        if not acquire_odds_refresh_lock(db, lock_key, owner, current_time, current_time + LOCK_TTL):
            return AutoBetResult(
                checked_db=True,
                candidate_matches=len(candidates),
                processed_matches=0,
                generated_bets=0,
                skipped_matches=len(candidates),
                skipped_reason="Another auto-bet run is active.",
            )
        try:
            return _fill_candidates(
                db,
                config,
                state,
                state_path,
                candidates,
                current_time,
                dry_run=dry_run,
                verbose=verbose,
            )
        finally:
            release_odds_refresh_lock(db, lock_key, owner)
    finally:
        db.close()
        _log(verbose, "stage=database_close")


def _fill_candidates(
    db: Database,
    config: EventConfig,
    state: dict[str, Any],
    state_path: Path,
    candidates: list[MatchConfig],
    now: datetime,
    *,
    dry_run: bool,
    verbose: bool,
) -> AutoBetResult:
    if not dry_run:
        locked = lock_latest_pregame_odds(db, config.event_id, now)
        _log(verbose, f"pregame_odds_locked={locked}")

    processed, skipped, generated_by_match, generated_total = fill_missing_bets_for_matches(
        db,
        config,
        candidates,
        now=now,
        dry_run=dry_run,
        verbose=verbose,
    )
    if not dry_run:
        for match in candidates:
            if _match_has_locked_probabilities(db, config.event_id, match.match_id):
                generated = generated_by_match.get(match.match_id, 0)
                _mark_processed(state, config.event_id, match.match_id, now, generated)
        if processed:
            _save_state(state_path, state)
    return AutoBetResult(
        checked_db=True,
        candidate_matches=len(candidates),
        processed_matches=processed,
        generated_bets=generated_total,
        skipped_matches=skipped,
    )


def fill_missing_bets_for_matches(
    db: Database,
    config: EventConfig,
    matches: list[MatchConfig],
    *,
    now: datetime,
    dry_run: bool = False,
    verbose: bool = False,
) -> tuple[int, int, dict[str, int], int]:
    """Create deterministic fallback bets for active players missing each match."""
    probabilities = load_locked_score_probabilities(db, config.event_id)
    players = _active_players(db)
    generated_rows: list[dict[str, Any]] = []
    processed = 0
    skipped = 0
    generated_by_match: dict[str, int] = {}

    for match in matches:
        match_probabilities = _match_probabilities(probabilities, match.match_id)
        if match_probabilities.empty:
            skipped += 1
            _log(verbose, f"match_id={match.match_id} skipped=no_locked_market_probabilities")
            continue
        missing_users = _missing_users(db, config.event_id, match.match_id, players)
        if not missing_users:
            processed += 1
            generated_by_match[match.match_id] = 0
            _log(verbose, f"match_id={match.match_id} generated=0")
            continue

        factor = _auto_factor(config, match)
        for username in missing_users:
            score_a, score_b = _sample_score(config.event_id, match.match_id, username, match_probabilities)
            generated_rows.append(
                {
                    "match_id": match.match_id,
                    "username": username,
                    "score_a": score_a,
                    "score_b": score_b,
                    "factor": factor,
                    "submitted_at": now.isoformat(),
                }
            )
        processed += 1
        generated_by_match[match.match_id] = len(missing_users)
        _log(verbose, f"match_id={match.match_id} generated={len(missing_users)}")

    inserted = 0 if dry_run else insert_auto_bets(db, config.event_id, generated_rows)
    if dry_run:
        return processed, skipped, generated_by_match, len(generated_rows)
    if inserted != len(generated_rows):
        generated_by_match = _inserted_auto_bets_by_match(db, config.event_id, generated_rows)
    return processed, skipped, generated_by_match, inserted


def _match_has_locked_probabilities(db: Database, event_id: str, match_id: str) -> bool:
    rows = db.query(
        """
        SELECT 1
        FROM pregame_odds_locks l
        JOIN score_probabilities p
          ON p.snapshot_id = l.snapshot_id
         AND p.event_id = l.event_id
         AND p.match_id = l.match_id
        WHERE l.event_id = ? AND l.match_id = ?
        LIMIT 1
        """,
        (event_id, match_id),
    )
    return bool(rows)


def _inserted_auto_bets_by_match(db: Database, event_id: str, rows: list[dict[str, Any]]) -> dict[str, int]:
    if not rows:
        return {}
    match_ids = sorted({str(row["match_id"]) for row in rows})
    placeholders = ",".join("?" for _ in match_ids)
    db_rows = db.query(
        f"""
        SELECT match_id, COUNT(*) AS generated
        FROM bets
        WHERE event_id = ?
          AND auto_generated = 1
          AND match_id IN ({placeholders})
        GROUP BY match_id
        """,
        (event_id, *match_ids),
    )
    return {str(row["match_id"]): int(row["generated"]) for row in db_rows}


def _active_players(db: Database) -> list[str]:
    rows = db.query("SELECT username FROM players WHERE active = 1 ORDER BY username")
    return [str(row["username"]) for row in rows]


def _missing_users(db: Database, event_id: str, match_id: str, players: list[str]) -> list[str]:
    rows = db.query(
        """
        SELECT username
        FROM bets
        WHERE event_id = ? AND match_id = ?
        """,
        (event_id, match_id),
    )
    submitted = {str(row["username"]) for row in rows}
    return [username for username in players if username not in submitted]


def _auto_factor(config: EventConfig, match: MatchConfig) -> int:
    rule = config.rules.get(match.round_name) or config.rules.get("knockout") or config.rules["group"]
    return max(1, int(round(2 / 3 * rule.max_factor)))


def _match_probabilities(probabilities: pd.DataFrame, match_id: str) -> pd.DataFrame:
    if probabilities.empty:
        return probabilities
    match_rows = probabilities[probabilities["match_id"].astype(str) == str(match_id)].copy()
    if match_rows.empty:
        return match_rows
    match_rows = match_rows.dropna(subset=["score_a", "score_b", "probability"])
    total = float(match_rows["probability"].sum())
    if total <= 0:
        return pd.DataFrame()
    match_rows["probability"] = match_rows["probability"].astype(float) / total
    return match_rows.sort_values(["score_a", "score_b"])


def _sample_score(event_id: str, match_id: str, username: str, probabilities: pd.DataFrame) -> tuple[int, int]:
    seed = hashlib.sha256(f"{event_id}:{match_id}:{username}:auto-bet".encode("utf-8")).hexdigest()
    rng = random.Random(int(seed[:16], 16))
    draw = rng.random()
    cumulative = 0.0
    last_score = (0, 0)
    for row in probabilities.itertuples(index=False):
        last_score = (int(row.score_a), int(row.score_b))
        cumulative += float(row.probability)
        if draw <= cumulative:
            return last_score
    return last_score


def _local_candidates(
    config: EventConfig,
    state: dict[str, Any],
    now: datetime,
    lookback: timedelta | None,
) -> list[MatchConfig]:
    due_after = now - lookback if lookback is not None else None
    candidates: list[MatchConfig] = []
    for match in config.matches:
        kickoff = _to_utc(match.kickoff_utc)
        if kickoff > now:
            continue
        if due_after is not None and kickoff < due_after:
            continue
        if _processed_match(state, config.event_id, match.match_id):
            continue
        candidates.append(match)
    return candidates


def _processed_match(state: dict[str, Any], event_id: str, match_id: str) -> bool:
    return bool(
        state.get("events", {})
        .get(event_id, {})
        .get("matches", {})
        .get(match_id, {})
        .get("processed_at")
    )


def _mark_processed(state: dict[str, Any], event_id: str, match_id: str, now: datetime, generated: int) -> None:
    events = state.setdefault("events", {})
    event = events.setdefault(event_id, {})
    matches = event.setdefault("matches", {})
    matches[str(match_id)] = {
        "processed_at": now.isoformat(),
        "generated_bets": int(generated),
    }


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"events": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"events": {}}
    return data if isinstance(data, dict) else {"events": {}}


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _to_utc(parsed)


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _print_result(result: AutoBetResult) -> None:
    print("stage=result")
    print(f"checked_db={result.checked_db}")
    print(f"candidate_matches={result.candidate_matches}")
    print(f"processed_matches={result.processed_matches}")
    print(f"generated_bets={result.generated_bets}")
    print(f"skipped_matches={result.skipped_matches}")
    if result.skipped_reason:
        print(f"skipped_reason={result.skipped_reason}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate market-sampled fallback bets for missed newly-started matches.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_EVENT_CONFIG,
        help=f"Event config path. Defaults to {DEFAULT_EVENT_CONFIG}.",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help=f"Local state path. Defaults to {DEFAULT_STATE_PATH}.",
    )
    parser.add_argument("--now", help="Override current time for testing, e.g. 2026-06-11T19:05:00+00:00.")
    parser.add_argument(
        "--lookback-minutes",
        type=int,
        default=int(DEFAULT_LOOKBACK.total_seconds() // 60),
        help="Only process matches that started within this window.",
    )
    parser.add_argument("--backfill", action="store_true", help="Process all past unprocessed matches, ignoring the lookback window.")
    parser.add_argument("--dry-run", action="store_true", help="Report generated bets without writing bets or local state.")
    args = parser.parse_args()

    result = fill_missing_bets(
        config_path=args.config,
        state_path=args.state,
        now=_parse_now(args.now),
        lookback=timedelta(minutes=int(args.lookback_minutes)),
        backfill=bool(args.backfill),
        dry_run=bool(args.dry_run),
    )
    _print_result(result)


if __name__ == "__main__":
    main()
