from __future__ import annotations

import hashlib
import random

import numpy as np
import pandas as pd

from .config import EventConfig, RuleConfig


TO_RANK = [8, 7, 6, 5, 4]
PROBABILITIES = [0.1, 0.2, 0.4, 0.2, 0.1]
KANONENWILLI_CHANCE_BY_LAST_RANK = {1: 0.66, 2: 0.50, 3: 0.33, 4: 0.16}
MARKET_EXOTIC_ALPHA = 0.6
MARKET_EXOTIC_Z_MAX = 3.0
MARKET_EXOTIC_MIN_CLOSENESS = 0.35
EPSILON = 1e-9


def _rule_for_row(config: EventConfig, round_name: str) -> RuleConfig:
    return config.rules.get(round_name) or config.rules.get("knockout") or config.rules["group"]


def _stable_random(seed: str, *parts: object) -> random.Random:
    digest = hashlib.sha256(":".join([seed, *[str(part) for part in parts]]).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:16], 16))


def _rocket_target(seed: str, match_id: str, username: str, last_rank: int) -> int | None:
    chance = KANONENWILLI_CHANCE_BY_LAST_RANK.get(int(last_rank), 0)
    rng = _stable_random(seed, match_id, username, last_rank)
    if rng.random() >= chance:
        return None
    return rng.choices(TO_RANK, weights=PROBABILITIES, k=1)[0]


def build_match_data(matches: pd.DataFrame, bets: pd.DataFrame, favorites: pd.DataFrame) -> pd.DataFrame:
    if matches.empty or bets.empty:
        return pd.DataFrame()
    df = bets.merge(matches, on=["event_id", "match_id"], how="inner", suffixes=("", "_match"))
    if favorites.empty:
        df["favorite_team_id"] = None
    else:
        df = df.merge(favorites.rename(columns={"team_id": "favorite_team_id"}), on="username", how="left")
    return df


def _closeness(pred_a: float, pred_b: float, result_a: float, result_b: float) -> float:
    score_dist = abs(pred_a - result_a) + abs(pred_b - result_b)
    diff_dist = abs((pred_a - pred_b) - (result_a - result_b))
    return float(0.7 * max(1 - score_dist / 4, 0) + 0.3 * max(1 - diff_dist / 3, 0))


def _old_exotic(scored: pd.DataFrame, config: EventConfig) -> pd.Series:
    by_match = scored.groupby(["match_id"])
    average_score_diff = by_match["score_diff"].transform("mean")
    average_score_dist = by_match["score_dist"].transform("mean")
    exotic_weight = scored["round_name"].apply(lambda value: _rule_for_row(config, str(value)).exotic)
    return (
        exotic_weight
        * (
            np.maximum((average_score_diff - scored["result_diff"]).abs() - (scored["result_diff"] - scored["score_diff"]).abs(), 0)
            + np.maximum(average_score_dist - scored["score_dist"], 0)
        )
        / 2
    ).astype(int)


def _market_exotic(scored: pd.DataFrame, probabilities: pd.DataFrame, config: EventConfig) -> pd.Series:
    exotic = _old_exotic(scored, config)
    if probabilities.empty:
        return exotic

    probability_by_match = {
        str(match_id): group[["score_a", "score_b", "probability"]].copy()
        for match_id, group in probabilities.groupby("match_id")
    }
    for match_id, group in scored.groupby("match_id"):
        probability_table = probability_by_match.get(str(match_id))
        if probability_table is None or probability_table.empty:
            continue

        probability_table = probability_table.dropna(subset=["score_a", "score_b", "probability"])
        probability_sum = float(probability_table["probability"].sum())
        if probability_sum <= 0:
            continue
        probability_table = probability_table.copy()
        probability_table["probability"] = probability_table["probability"].astype(float) / probability_sum

        actual_closeness = group.apply(
            lambda row: _closeness(row.score_a, row.score_b, row.result_a, row.result_b),
            axis=1,
        )
        average_closeness = float(actual_closeness.mean())
        round_name = str(group["round_name"].iloc[0])
        weight = _rule_for_row(config, round_name).exotic

        values: dict[int, int] = {}
        for index, row in group.iterrows():
            expected_values = probability_table.apply(
                lambda score_row: _closeness(row.score_a, row.score_b, score_row.score_a, score_row.score_b),
                axis=1,
            )
            mu = float((expected_values * probability_table["probability"]).sum())
            variance = float((((expected_values - mu) ** 2) * probability_table["probability"]).sum())
            sigma = float(np.sqrt(max(variance, 0)))
            k_value = float(actual_closeness.loc[index])
            if k_value < MARKET_EXOTIC_MIN_CLOSENESS:
                market_score = 0.0
            else:
                z_score = min(max((k_value - mu) / (sigma + EPSILON), 0.0), MARKET_EXOTIC_Z_MAX)
                market_score = z_score / MARKET_EXOTIC_Z_MAX
            crowd_score = max(k_value - average_closeness, 0.0) / (1 - average_closeness + EPSILON)
            values[index] = int(round(weight * (MARKET_EXOTIC_ALPHA * market_score + (1 - MARKET_EXOTIC_ALPHA) * crowd_score)))

        for index, value in values.items():
            exotic.at[index] = value
    return exotic


def score_rows(df: pd.DataFrame, config: EventConfig, market_probabilities: pd.DataFrame | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    scored = df.copy()
    scored = scored.dropna(subset=["score_a", "score_b", "result_a", "result_b"])
    if scored.empty:
        return scored

    scored["score_a"] = scored["score_a"].astype(int)
    scored["score_b"] = scored["score_b"].astype(int)
    scored["result_a"] = scored["result_a"].astype(int)
    scored["result_b"] = scored["result_b"].astype(int)
    scored["factor"] = scored["factor"].astype(int)
    scored["score_diff"] = scored["score_a"] - scored["score_b"]
    scored["result_diff"] = scored["result_a"] - scored["result_b"]
    scored["score_dist"] = (scored["score_a"] - scored["result_a"]).abs() + (scored["score_b"] - scored["result_b"]).abs()

    correct_outcome = (
        ((scored["result_a"] > scored["result_b"]) & (scored["score_a"] > scored["score_b"]))
        | ((scored["result_a"] == scored["result_b"]) & (scored["score_a"] == scored["score_b"]))
        | ((scored["result_a"] < scored["result_b"]) & (scored["score_a"] < scored["score_b"]))
    )
    scored["base"] = correct_outcome.astype(int) * 2 - 1
    scored["base"] += (scored["score_dist"] <= 1).astype(int)
    scored["base"] += (scored["score_diff"] == scored["result_diff"]).astype(int)
    scored["base"] += ((scored["score_a"] == scored["result_a"]) & (scored["score_b"] == scored["result_b"])).astype(int) * 2
    scored["fbase"] = scored["base"] * scored["factor"] + 3

    scored["exotic"] = _market_exotic(scored, market_probabilities if market_probabilities is not None else pd.DataFrame(), config)

    favorite_weight = scored["round_name"].apply(lambda value: _rule_for_row(config, str(value)).favorite)
    favorite_a = scored["favorite_team_id"] == scored["team_a_id"]
    favorite_b = scored["favorite_team_id"] == scored["team_b_id"]
    scored["favorite"] = 0
    scored.loc[favorite_a, "favorite"] = (
        favorite_weight[favorite_a] * (scored.loc[favorite_a, "result_a"] > scored.loc[favorite_a, "result_b"]).astype(int)
        + 3 * (scored.loc[favorite_a, "result_a"] == scored.loc[favorite_a, "result_b"]).astype(int)
        - 6 * (scored.loc[favorite_a, "result_a"] < scored.loc[favorite_a, "result_b"]).astype(int)
    )
    scored.loc[favorite_b, "favorite"] = (
        favorite_weight[favorite_b] * (scored.loc[favorite_b, "result_a"] < scored.loc[favorite_b, "result_b"]).astype(int)
        + 3 * (scored.loc[favorite_b, "result_a"] == scored.loc[favorite_b, "result_b"]).astype(int)
        - 6 * (scored.loc[favorite_b, "result_a"] > scored.loc[favorite_b, "result_b"]).astype(int)
    )

    scored["kanonenwilli"] = scored["kanonenwilli"].fillna(0).astype(int)
    scored["kanonenwilli_points"] = scored["kanonenwilli"] * correct_outcome.astype(int)
    scored["final"] = scored["fbase"] + scored["exotic"] + scored["favorite"] + scored["kanonenwilli_points"]
    return scored


def assign_missing_kanonenwilli(
    data: pd.DataFrame,
    config: EventConfig,
    market_probabilities: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if data.empty:
        return data, pd.DataFrame(columns=["match_id", "username", "kanonenwilli"])

    working = data.copy().sort_values(["sort_order", "username"])
    updates: list[dict[str, object]] = []
    for match_id in working["match_id"].drop_duplicates():
        match_mask = working["match_id"] == match_id
        if working.loc[match_mask, "kanonenwilli"].notna().all():
            continue

        prior = working[(working["sort_order"] < int(working.loc[match_mask, "sort_order"].iloc[0])) & working["kanonenwilli"].notna()]
        prior_scored = score_rows(prior, config, market_probabilities)
        if prior_scored.empty or "final" not in prior_scored.columns:
            values = {username: 0 for username in working.loc[match_mask, "username"]}
        else:
            standings = prior_scored.groupby("username", as_index=False)["final"].sum().sort_values("final", ascending=False)
            standings["last_rank"] = standings["final"].rank(method="min", ascending=True).astype(int)
            standings = standings.reset_index(drop=True)
            values = {}
            for row in standings.itertuples(index=False):
                target = _rocket_target(config.kanonenwilli_seed, str(match_id), str(row.username), int(row.last_rank))
                if target is None or target > len(standings):
                    values[str(row.username)] = 0
                    continue
                target_points = int(standings.iloc[target - 1]["final"])
                values[str(row.username)] = max(target_points - int(row.final), 0)
            for username in working.loc[match_mask, "username"]:
                values.setdefault(str(username), 0)

        for index, row in working.loc[match_mask].iterrows():
            value = int(values.get(str(row["username"]), 0))
            working.at[index, "kanonenwilli"] = value
            updates.append({"match_id": match_id, "username": row["username"], "kanonenwilli": value})

    return working, pd.DataFrame(updates)


def compute_points(
    matches: pd.DataFrame,
    bets: pd.DataFrame,
    favorites: pd.DataFrame,
    config: EventConfig,
    market_probabilities: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = build_match_data(matches, bets, favorites)
    if data.empty:
        return pd.DataFrame(), pd.DataFrame()
    completed = data.dropna(subset=["result_a", "result_b"])
    completed, kw_updates = assign_missing_kanonenwilli(completed, config, market_probabilities)
    scored = score_rows(completed, config, market_probabilities)
    columns = [
        "match_id",
        "username",
        "base",
        "fbase",
        "exotic",
        "favorite",
        "kanonenwilli_points",
        "final",
    ]
    return scored[columns] if not scored.empty else pd.DataFrame(columns=columns), kw_updates
