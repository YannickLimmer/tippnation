from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import DEFAULT_EVENT_CONFIG, EventConfig, load_event_config
from .db import Database, connect, ensure_schema
from .odds import (
    keep_betfair_session_alive,
    login_betfair_with_certificate,
    odds_refresh_decision,
    refresh_betfair_odds,
    refresh_market_odds_if_due,
    seed_synthetic_equal_odds_backfill,
)
from .repository import load_matches, lock_latest_pregame_odds, sync_event_config
from .secrets import get_betfair_settings, get_database_settings


@dataclass(frozen=True)
class LocalOddsUpdateResult:
    attempted: bool
    updated_matches: int
    locked_matches: int
    unmatched_matches: int
    stage: str = "unknown"
    skipped_reason: str | None = None
    error: str | None = None
    seeded_matches: int = 0
    skipped_matches: int = 0


def update_betting_odds(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    force: bool = False,
    all_upcoming: bool = False,
    now: datetime | None = None,
    verbose: bool = True,
) -> LocalOddsUpdateResult:
    current_time = now or datetime.now(timezone.utc)
    _log(verbose, "stage=config_load")
    _log(verbose, f"config_path={config_path}")
    config = load_event_config(config_path)
    _log(verbose, f"event_id={config.event_id}")
    _log(verbose, f"mode=odds_refresh force={force} all_upcoming={all_upcoming} now={current_time.isoformat()}")
    _log(verbose, "stage=database_connect")
    db = connect(get_database_settings())
    try:
        _log(verbose, "stage=database_schema")
        ensure_schema(db)
        sync_event_config(db, config)

        _log(verbose, "stage=pregame_lock")
        locked_before = lock_latest_pregame_odds(db, config.event_id, current_time)
        _log(verbose, f"locked_before_refresh={locked_before}")

        _log(verbose, "stage=betfair_settings")
        settings = get_betfair_settings()
        if settings is None:
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                stage="betfair_settings",
                skipped_reason="Betfair credentials are not configured.",
            )
        _log_betfair_settings(verbose, settings)

        try:
            _log(verbose, "stage=betfair_cert_login")
            settings = login_betfair_with_certificate(settings)
        except Exception as exc:
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                stage="betfair_cert_login",
                error=str(exc),
            )
        _log(verbose, f"betfair_session_token_acquired={bool(settings.session_token)}")

        _log(verbose, "stage=betfair_keep_alive")
        keep_alive = keep_betfair_session_alive(settings)
        _log_keep_alive(verbose, keep_alive)
        if str(keep_alive.get("status", "")).upper() != "SUCCESS":
            return LocalOddsUpdateResult(
                attempted=False,
                updated_matches=0,
                locked_matches=locked_before,
                unmatched_matches=0,
                stage="betfair_keep_alive",
                skipped_reason=f"Betfair keep-alive failed: {keep_alive.get('status', 'unknown')}",
            )

        _log(verbose, "stage=matches_load")
        matches = load_matches(db, config.event_id)
        _log(verbose, f"matches_loaded={len(matches)}")
        if force:
            target_match_ids = _target_match_ids(matches, current_time, all_upcoming)
            _log(verbose, f"stage=betfair_refresh target_matches={len(target_match_ids)}")
            try:
                updated, unmatched = refresh_betfair_odds(db, config, settings, matches, target_match_ids, current_time)
            except Exception as exc:
                return LocalOddsUpdateResult(
                    attempted=True,
                    updated_matches=0,
                    locked_matches=locked_before,
                    unmatched_matches=len(target_match_ids),
                    stage="betfair_refresh",
                    error=str(exc),
                )
            locked_after = lock_latest_pregame_odds(db, config.event_id, current_time)
            return LocalOddsUpdateResult(
                attempted=True,
                updated_matches=updated,
                locked_matches=locked_before + locked_after,
                unmatched_matches=unmatched,
                stage="betfair_refresh",
            )

        _log(verbose, "stage=refresh_decision")
        decision = odds_refresh_decision(db, config.event_id, matches, current_time)
        _log(verbose, f"refresh_due={decision.due}")
        _log(verbose, f"refresh_reason={decision.reason}")
        _log(verbose, f"refresh_target_matches={len(decision.target_match_ids)}")
        _log(verbose, "stage=betfair_refresh_if_due")
        result = refresh_market_odds_if_due(db, config, settings, matches, current_time)
        return LocalOddsUpdateResult(
            attempted=result.attempted,
            updated_matches=result.updated_matches,
            locked_matches=locked_before + result.locked_matches,
            unmatched_matches=result.unmatched_matches,
            stage="betfair_refresh_if_due",
            skipped_reason=result.skipped_reason or (None if decision.due else decision.reason),
            error=result.error,
        )
    finally:
        db.close()
        _log(verbose, "stage=database_close")


def check_betfair_auth(*, verbose: bool = True) -> LocalOddsUpdateResult:
    _log(verbose, "mode=auth_check")
    _log(verbose, "stage=betfair_settings")
    settings = get_betfair_settings()
    if settings is None:
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            stage="betfair_settings",
            skipped_reason="Betfair credentials are not configured.",
        )
    _log_betfair_settings(verbose, settings)
    try:
        _log(verbose, "stage=betfair_cert_login")
        settings = login_betfair_with_certificate(settings)
    except Exception as exc:
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            stage="betfair_cert_login",
            error=str(exc),
        )
    _log(verbose, f"betfair_session_token_acquired={bool(settings.session_token)}")
    _log(verbose, "stage=betfair_keep_alive")
    keep_alive = keep_betfair_session_alive(settings)
    _log_keep_alive(verbose, keep_alive)
    if str(keep_alive.get("status", "")).upper() != "SUCCESS":
        return LocalOddsUpdateResult(
            attempted=False,
            updated_matches=0,
            locked_matches=0,
            unmatched_matches=0,
            stage="betfair_keep_alive",
            skipped_reason=f"Betfair keep-alive failed: {keep_alive.get('status', 'unknown')}",
        )
    return LocalOddsUpdateResult(
        attempted=True,
        updated_matches=0,
        locked_matches=0,
        unmatched_matches=0,
        stage="betfair_keep_alive",
    )


def backfill_synthetic_odds(
    *,
    config_path: Path = DEFAULT_EVENT_CONFIG,
    match_ids: list[str] | None = None,
    lambda_goals: float = 1.5,
    include_future: bool = False,
    now: datetime | None = None,
    verbose: bool = True,
) -> LocalOddsUpdateResult:
    current_time = now or datetime.now(timezone.utc)
    _log(verbose, "stage=config_load")
    _log(verbose, f"config_path={config_path}")
    config = load_event_config(config_path)
    _log(verbose, f"event_id={config.event_id}")
    _log(verbose, f"mode=synthetic_odds_backfill lambda_goals={lambda_goals} now={current_time.isoformat()}")
    _log(verbose, "stage=database_connect")
    db = connect(get_database_settings())
    try:
        _log(verbose, "stage=database_schema")
        ensure_schema(db)
        sync_event_config(db, config)
        result = seed_synthetic_equal_odds_backfill(
            db,
            config,
            current_time,
            match_ids=match_ids,
            lambda_goals=lambda_goals,
            include_future=include_future,
        )
        return LocalOddsUpdateResult(
            attempted=True,
            updated_matches=result.seeded_matches,
            locked_matches=result.locked_matches,
            unmatched_matches=0,
            stage="synthetic_odds_backfill",
            seeded_matches=result.seeded_matches,
            skipped_matches=result.skipped_matches,
        )
    finally:
        db.close()
        _log(verbose, "stage=database_close")


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


def _log(enabled: bool, message: str) -> None:
    if enabled:
        print(message, flush=True)


def _log_betfair_settings(enabled: bool, settings: Any) -> None:
    _log(enabled, f"betfair_app_key_configured={bool(settings.app_key)}")
    _log(enabled, f"betfair_username_configured={bool(settings.username)}")
    _log(enabled, f"betfair_password_configured={bool(settings.password)}")
    _log(enabled, f"betfair_session_token_configured={bool(settings.session_token)}")
    _log(enabled, f"betfair_cert_paths_configured={bool(settings.cert_path and settings.key_path)}")
    _log(enabled, f"betfair_cert_base64_configured={bool(settings.cert_base64 and settings.key_base64)}")
    auth_method = "certificate" if settings.has_certificate_login else "session_token"
    _log(enabled, f"betfair_auth_method={auth_method}")


def _log_keep_alive(enabled: bool, keep_alive: dict[str, Any]) -> None:
    _log(enabled, f"betfair_keep_alive_status={keep_alive.get('status', 'unknown')}")
    if "http_status" in keep_alive:
        _log(enabled, f"betfair_keep_alive_http_status={keep_alive['http_status']}")
    if "reason" in keep_alive:
        _log(enabled, f"betfair_keep_alive_reason={keep_alive['reason']}")
    if "body" in keep_alive:
        _log(enabled, f"betfair_keep_alive_body={keep_alive['body']}")


def _print_result(result: LocalOddsUpdateResult) -> None:
    print("stage=result")
    print(f"result_stage={result.stage}")
    print(f"attempted={result.attempted}")
    print(f"updated_matches={result.updated_matches}")
    print(f"unmatched_matches={result.unmatched_matches}")
    print(f"locked_matches={result.locked_matches}")
    print(f"seeded_matches={result.seeded_matches}")
    print(f"skipped_matches={result.skipped_matches}")
    if result.skipped_reason:
        print(f"skipped_reason={result.skipped_reason}")
    if result.error:
        print(f"error={result.error}")


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
    parser.add_argument(
        "--synthetic-backfill",
        action="store_true",
        help="Seed equal synthetic pre-game odds for past matches that do not already have a locked odds snapshot.",
    )
    parser.add_argument("--match-id", action="append", help="Limit --synthetic-backfill to one match ID. Can be repeated.")
    parser.add_argument("--lambda-goals", type=float, default=1.5, help="Expected goals per team for --synthetic-backfill.")
    parser.add_argument(
        "--include-future",
        action="store_true",
        help="Allow --synthetic-backfill to seed selected future matches too. Past matches only by default.",
    )
    args = parser.parse_args()

    if args.auth_check:
        result = check_betfair_auth()
    elif args.synthetic_backfill:
        result = backfill_synthetic_odds(
            config_path=args.config,
            match_ids=args.match_id,
            lambda_goals=float(args.lambda_goals),
            include_future=bool(args.include_future),
            now=_parse_now(args.now),
        )
    else:
        result = update_betting_odds(
            config_path=args.config,
            force=bool(args.force),
            all_upcoming=bool(args.all_upcoming),
            now=_parse_now(args.now),
        )
    _print_result(result)
    if args.strict and (failure_reason := _strict_failure_reason(result)):
        raise SystemExit(failure_reason)


if __name__ == "__main__":
    main()
