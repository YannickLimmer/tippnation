from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from .config import DEFAULT_EVENT_CONFIG, load_event_config
from .results import (
    DEFAULT_API_FOOTBALL_DAILY_BUDGET,
    DEFAULT_MAX_API_REQUESTS,
    DEFAULT_STATE_PATH,
    DEFAULT_THESPORTSDB_KEY,
    ResultPollResult,
    local_due_match_count,
    poll_match_results,
)


def update_results_from_provider(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    state_path: Path = DEFAULT_STATE_PATH,
    api_key: str = DEFAULT_THESPORTSDB_KEY,
    provider: str = "auto",
    now: datetime | None = None,
    force: bool = False,
    backfill: bool = False,
    dry_run: bool = False,
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
    api_football_daily_budget: int = DEFAULT_API_FOOTBALL_DAILY_BUDGET,
    verbose: bool = True,
):
    current_time = now or datetime.now(timezone.utc)
    _log(verbose, "stage=config_load")
    _log(verbose, f"config_path={config_path}")
    config = load_event_config(config_path)
    _log(verbose, f"event_id={config.event_id}")
    _log(verbose, f"mode=result_poll force={force} backfill={backfill} dry_run={dry_run} now={current_time.isoformat()}")
    due_count = local_due_match_count(config, state_path=state_path, now=current_time, force=force, backfill=backfill)
    _log(verbose, f"local_due_matches={due_count}")
    if due_count == 0:
        return ResultPollResult(
            attempted_api=False,
            checked_db=False,
            candidates=0,
            already_completed=0,
            updated_matches=0,
            unmatched_matches=0,
            api_requests=0,
            recomputed_points=False,
            skipped_reason="No locally due matches.",
        )

    _log(verbose, "stage=database_connect")
    from .db import connect, ensure_schema
    from .secrets import get_api_football_key, get_database_settings

    db = connect(get_database_settings())
    try:
        _log(verbose, "stage=database_schema")
        ensure_schema(db)
        if not dry_run:
            from .repository import sync_event_config

            sync_event_config(db, config)
        _log(verbose, "stage=result_poll")
        return poll_match_results(
            db,
            config,
            state_path=state_path,
            api_key=api_key,
            api_football_key=get_api_football_key(),
            provider=provider,
            now=current_time,
            force=force,
            backfill=backfill,
            dry_run=dry_run,
            max_api_requests=max_api_requests,
            api_football_daily_budget=api_football_daily_budget,
        )
    finally:
        db.close()
        _log(verbose, "stage=database_close")


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _print_result(result) -> None:
    print("stage=result")
    print(f"attempted_api={result.attempted_api}")
    print(f"checked_db={result.checked_db}")
    print(f"candidates={result.candidates}")
    print(f"already_completed={result.already_completed}")
    print(f"updated_matches={result.updated_matches}")
    print(f"unmatched_matches={result.unmatched_matches}")
    print(f"api_requests={result.api_requests}")
    print(f"recomputed_points={result.recomputed_points}")
    if result.skipped_reason:
        print(f"skipped_reason={result.skipped_reason}")
    if result.error:
        print(f"error={result.error}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll live/final match results and persist TippNation points.")
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
        help=f"Local poll state path. Defaults to {DEFAULT_STATE_PATH}.",
    )
    parser.add_argument("--api-key", default=DEFAULT_THESPORTSDB_KEY, help="TheSportsDB v1 API key. Defaults to the public free key.")
    parser.add_argument(
        "--provider",
        choices=["auto", "api-football", "thesportsdb"],
        default="auto",
        help="Result provider. auto prefers API-FOOTBALL when configured for the event.",
    )
    parser.add_argument("--now", help="Override current time for testing, e.g. 2026-06-05T03:00:00+00:00.")
    parser.add_argument("--force", action="store_true", help="Ignore local due/backoff state and check all unresolved matches in the lookback window.")
    parser.add_argument("--backfill", action="store_true", help="Query all past matches in the event that do not have stored scores.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and match results without writing the database, points, or local state.")
    parser.add_argument("--max-api-requests", type=int, default=DEFAULT_MAX_API_REQUESTS, help="Maximum provider API requests per run.")
    parser.add_argument(
        "--api-football-daily-budget",
        type=int,
        default=DEFAULT_API_FOOTBALL_DAILY_BUDGET,
        help="Local daily API-FOOTBALL request budget.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when an API or update error occurs.")
    args = parser.parse_args()

    result = update_results_from_provider(
        config_path=args.config,
        state_path=args.state,
        api_key=str(args.api_key),
        provider=str(args.provider),
        now=_parse_now(args.now),
        force=bool(args.force),
        backfill=bool(args.backfill),
        dry_run=bool(args.dry_run),
        max_api_requests=int(args.max_api_requests),
        api_football_daily_budget=int(args.api_football_daily_budget),
    )
    _print_result(result)
    if args.strict and result.error:
        raise SystemExit(result.error)


if __name__ == "__main__":
    main()
