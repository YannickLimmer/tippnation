from __future__ import annotations

import pandas as pd

from .config import EventConfig
from .db import Database, ensure_schema
from .repository import (
    load_bets,
    load_favorites,
    load_locked_score_probabilities,
    load_matches,
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


def set_match_results(
    db: Database,
    event_id: str,
    results: pd.DataFrame,
    config: EventConfig | None = None,
) -> None:
    update_results(db, event_id, results.to_dict("records"))
    if config is not None:
        from .knockout import sync_knockout_advancement

        sync_knockout_advancement(db, config)


def compute_and_store_points(db: Database, config: EventConfig) -> pd.DataFrame:
    matches = load_matches(db, config.event_id)
    bets = load_bets(db, config.event_id)
    favorites = load_favorites(db, config.event_id)
    market_probabilities = load_locked_score_probabilities(db, config.event_id)
    points, kanonenwilli_updates = compute_points(matches, bets, favorites, config, market_probabilities)
    update_kanonenwilli(db, config.event_id, kanonenwilli_updates)
    replace_points(db, config.event_id, points)
    return points
