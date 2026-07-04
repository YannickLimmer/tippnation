from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from .config import EventConfig, MatchConfig
from .db import Database, ensure_schema
from .repository import (
    event_config_is_current,
    load_bets,
    load_favorites,
    load_locked_score_probabilities,
    load_matches,
    lock_latest_pregame_odds,
    replace_points,
    sync_event_config,
    sync_players,
    update_kanonenwilli,
    update_results,
)
from .scoring import compute_points


def initialize_database(db: Database, config: EventConfig, usernames: list[str]) -> None:
    ensure_schema(db)
    sync_event_config(db, config)
    sync_players(db, usernames)


def initialize_database_if_needed(db: Database, config: EventConfig, usernames: list[str]) -> bool:
    ensure_schema(db)
    synced = False
    if not event_config_is_current(db, config):
        sync_event_config(db, config)
        synced = True
    sync_players(db, usernames)
    return synced


def set_match_results(
    db: Database,
    event_id: str,
    results: pd.DataFrame,
    config: EventConfig | None = None,
) -> int:
    generated_auto_bets = 0
    if config is not None and event_id == config.event_id:
        now = datetime.now(timezone.utc)
        auto_bet_matches = _matches_needing_auto_bets(results, config, now)
        if auto_bet_matches:
            from .autobet_cli import fill_missing_bets_for_matches

            lock_latest_pregame_odds(db, event_id, now)
            _, _, _, generated_auto_bets = fill_missing_bets_for_matches(
                db,
                config,
                auto_bet_matches,
                now=now,
            )
    update_results(db, event_id, results.to_dict("records"))
    if config is not None:
        from .knockout import sync_knockout_advancement

        sync_knockout_advancement(db, config)
    return generated_auto_bets


def _matches_needing_auto_bets(results: pd.DataFrame, config: EventConfig, now: datetime) -> list[MatchConfig]:
    if results.empty or "match_id" not in results.columns:
        return []
    if "result_a" not in results.columns or "result_b" not in results.columns:
        return []
    scored = results[
        results["result_a"].notna()
        & results["result_b"].notna()
    ]
    if scored.empty:
        return []
    scored_match_ids = {str(match_id) for match_id in scored["match_id"]}
    return [
        match
        for match in config.matches
        if match.match_id in scored_match_ids and match.kickoff_utc <= now
    ]


def compute_and_store_points(db: Database, config: EventConfig) -> pd.DataFrame:
    matches = load_matches(db, config.event_id)
    bets = load_bets(db, config.event_id)
    favorites = load_favorites(db, config.event_id)
    market_probabilities = load_locked_score_probabilities(db, config.event_id)
    points, kanonenwilli_updates = compute_points(matches, bets, favorites, config, market_probabilities)
    update_kanonenwilli(db, config.event_id, kanonenwilli_updates)
    replace_points(db, config.event_id, points)
    return points
