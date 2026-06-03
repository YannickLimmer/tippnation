from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from .config import DEFAULT_EVENT_CONFIG, EventConfig, load_event_config
from .db import Database, connect, ensure_schema
from .odds import (
    keep_betfair_session_alive,
    login_betfair_with_certificate,
    odds_refresh_decision,
    refresh_betfair_odds,
    refresh_market_odds_if_due,
)
from .repository import load_matches, lock_latest_pregame_odds, sync_event_config
from .secrets import get_betfair_settings, get_database_settings


@dataclass(frozen=True)
class LocalOddsUpdateResult:
    attempted: bool
    updated_matches: int
    locked_matches: int
    unmatched_matches: int
    skipped_reason: str | None = None
    error: str | None = None


def update_betting_odds(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    force: bool = False,
    all_upcoming: bool = False,
    now: datetime | None = None,
) -> LocalOddsUpdateResult:
    current_time = now or datetime.now(timezone.utc)
    config = load_event_config(config_path)
    db = connect(get_database_settings())
    try:
        ensure_schema(db)
        sync_event_config(db, config)

        locked_before = lock_latest_pregame_odds(db, config.event_id, current_time)
        settings = get_betfair_settings()
        if settings is None:
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                skipped_reason="Betfair credentials are not configured.",
            )

        try:
            settings = login_betfair_with_certificate(settings)
        except Exception as exc:
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                error=str(exc),
            )

        keep_alive = keep_betfair_session_alive(settings)
        if str(keep_alive.get("status", "")).upper() != "SUCCESS":
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                skipped_reason=f"Betfair keep-alive failed: {keep_alive.get('status', 'unknown')}",
            )

        matches = load_matches(db, config.event_id)
        if force:
            target_match_ids = _target_match_ids(matches, current_time, all_upcoming)
            updated, unmatched = refresh_betfair_odds(db, config, settings, matches, target_match_ids, current_time)
            locked_after = lock_latest_pregame_odds(db, config.event_id, current_time)
            return LocalOddsUpdateResult(
                attempted=True,
                updated_matches=updated,
                locked_matches=locked_before + locked_after,
                unmatched_matches=unmatched,
            )

        decision = odds_refresh_decision(db, config.event_id, matches, current_time)
        result = refresh_market_odds_if_due(db, config, settings, matches, current_time)
        return LocalOddsUpdateResult(
            attempted=result.attempted,
            updated_matches=result.updated_matches,
            locked_matches=locked_before + result.locked_matches,
            unmatched_matches=result.unmatched_matches,
            skipped_reason=result.skipped_reason or (None if decision.due else decision.reason),
            error=result.error,
        )
    finally:
        db.close()


def check_betfair_auth() -> LocalOddsUpdateResult:
    settings = get_betfair_settings()
    if settings is None:
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            skipped_reason="Betfair credentials are not configured.",
        )
    try:
        settings = login_betfair_with_certificate(settings)
    except Exception as exc:
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            error=str(exc),
        )
    keep_alive = keep_betfair_session_alive(settings)
    if str(keep_alive.get("status", "")).upper() != "SUCCESS":
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            skipped_reason=f"Betfair keep-alive failed: {keep_alive.get('status', 'unknown')}",
        )
    return LocalOddsUpdateResult(
        attempted=True,
        updated_matches=0,
        locked_matches=0,
        unmatched_matches=0,
    )


def _target_match_ids(matches: pd.DataFrame, now: datetime, all_upcoming: bool) -> list[str]:
    upcoming = matches[matches["kickoff_utc"] > pd.Timestamp(now)].sort_values("kickoff_utc")
    if upcoming.empty:
        return []
    if all_upcoming:
        return [str(match_id) for match_id in upcoming["match_id"].tolist()]
    next_round = str(upcoming.iloc[0]["round_name"])
    target = upcoming[upcoming["round_name"] == next_round]
    return [str(match_id) for match_id in target["match_id"].tolist()]


def _parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _strict_failure_reason(result: LocalOddsUpdateResult) -> str | None:
    if result.error:
        return result.error
    reason = result.skipped_reason or ""
    if "Betfair credentials" in reason or "Betfair keep-alive failed" in reason:
        return reason
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh TippNation Betfair odds from a local machine.")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_EVENT_CONFIG,
        help=f"Event config path. Defaults to {DEFAULT_EVENT_CONFIG}.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Fetch odds now even if the normal refresh cadence says the current snapshots are fresh.",
    )
    parser.add_argument(
        "--all-upcoming",
        action="store_true",
        help="With --force, update every upcoming match instead of only the next round/stage.",
    )
    parser.add_argument(
        "--now",
        help="Override current time for testing, e.g. 2026-06-05T22:30:00+00:00.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero for CI-relevant failures such as missing Betfair credentials, certificate login failure, keep-alive failure, or refresh errors.",
    )
    parser.add_argument(
        "--auth-check",
        action="store_true",
        help="Only test Betfair certificate/session login and keep-alive. Does not connect to the database.",
    )
    args = parser.parse_args()

    if args.auth_check:
        result = check_betfair_auth()
    else:
        result = update_betting_odds(
            config_path=args.config,
            force=bool(args.force),
            all_upcoming=bool(args.all_upcoming),
            now=_parse_now(args.now),
        )
    print(f"attempted={result.attempted}")
    print(f"updated_matches={result.updated_matches}")
    print(f"unmatched_matches={result.unmatched_matches}")
    print(f"locked_matches={result.locked_matches}")
    if result.skipped_reason:
        print(f"skipped_reason={result.skipped_reason}")
    if result.error:
        print(f"error={result.error}")
    if args.strict and (failure_reason := _strict_failure_reason(result)):
        raise SystemExit(failure_reason)


if __name__ == "__main__":
    main()
