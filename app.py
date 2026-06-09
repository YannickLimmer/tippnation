from __future__ import annotations

import os
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import plotly.express as px
import streamlit as st

from tippnation.admin import compute_and_store_points, initialize_database, set_match_results
from tippnation.config import DEFAULT_EVENT_CONFIG, EventConfig, config_as_json, load_event_config
from tippnation.db import Database, connect
from tippnation.i18n import LANGUAGES, t
from tippnation.odds import DISPLAY_SCORE_MAX
from tippnation.repository import (
    list_players,
    load_bets,
    load_display_score_probabilities,
    load_favorites,
    load_match_bet_usernames,
    load_locked_score_probabilities,
    load_matches,
    load_points,
    load_user_bets,
    lock_latest_pregame_odds,
    set_favorite,
    upsert_bets,
)
from tippnation.replay import (
    REPLAY_ADMIN_PASSWORD,
    REPLAY_USER_PASSWORD,
    ReplaySettings,
    build_replay_settings,
    replay_settings_for_snapshot,
    reset_replay_database,
)
from tippnation.scoring import compute_points
from tippnation.secrets import (
    get_admin_password,
    get_database_settings,
    get_user_password,
    list_auth_users,
    load_secret_sources,
    verify_password,
)


READ_REFRESH_INTERVAL = "60s"
POINT_DISPLAY_COLUMNS = ["base", "fbase", "exotic", "favorite", "kanonenwilli", "final"]
POINT_COMPOSITION_COLUMNS = ["fbase", "exotic", "favorite", "kanonenwilli"]


def rule_for_round(config: EventConfig, round_name: str):
    return config.rules.get(str(round_name), config.rules.get("knockout", config.rules["group"]))


def factor_budget_for_matches(config: EventConfig, matches: pd.DataFrame) -> int:
    return int(sum(rule_for_round(config, str(match.round_name)).max_factor for match in matches.itertuples(index=False)))


def factor_max_for_match(match_id: str, values: dict[str, int], budget: int) -> int:
    used_by_others = sum(value for other_match_id, value in values.items() if other_match_id != match_id)
    return max(1, int(budget) - int(used_by_others))


@st.cache_resource(show_spinner=False)
def get_database(config_path: str, replay_snapshot: str | None) -> Database:
    if replay_snapshot:
        settings = replay_settings_for_snapshot(replay_snapshot)
        config = load_event_config(Path(config_path))
        return reset_replay_database(settings, config)
    return connect(get_database_settings())


@st.cache_data(show_spinner=False)
def get_event_config(path: str) -> EventConfig:
    return load_event_config(Path(path))


def database_cache_key(db: Database) -> str:
    return f"{type(db).__name__}:{id(db)}"


def now_bucket(seconds: int) -> int:
    return int(now_utc().timestamp() // seconds)


@st.cache_data(show_spinner=False, ttl=300)
def bootstrap_cached(
    _db: Database,
    db_key: str,
    _config: EventConfig,
    config_json: str,
    usernames: tuple[str, ...],
) -> tuple[str, ...]:
    initialize_database(_db, _config, list(usernames))
    return tuple(list_players(_db))


@st.cache_data(show_spinner=False, ttl=30)
def cached_load_matches(
    _db: Database,
    db_key: str,
    event_id: str,
    refresh_bucket: int | None = None,
) -> pd.DataFrame:
    return load_matches(_db, event_id)


@st.cache_data(show_spinner=False, ttl=10)
def cached_load_bets(_db: Database, db_key: str, event_id: str) -> pd.DataFrame:
    return load_bets(_db, event_id)


@st.cache_data(show_spinner=False, ttl=10)
def cached_load_user_bets(_db: Database, db_key: str, event_id: str, username: str) -> pd.DataFrame:
    return load_user_bets(_db, event_id, username)


@st.cache_data(show_spinner=False, ttl=10)
def cached_load_match_bet_usernames(_db: Database, db_key: str, event_id: str, match_id: str) -> list[str]:
    return load_match_bet_usernames(_db, event_id, match_id)


@st.cache_data(show_spinner=False, ttl=10)
def cached_load_favorites(_db: Database, db_key: str, event_id: str) -> pd.DataFrame:
    return load_favorites(_db, event_id)


@st.cache_data(show_spinner=False, ttl=10)
def cached_load_points(
    _db: Database,
    db_key: str,
    event_id: str,
    refresh_bucket: int | None = None,
) -> pd.DataFrame:
    return load_points(_db, event_id)


@st.cache_data(show_spinner=False, ttl=60)
def cached_load_locked_score_probabilities(_db: Database, db_key: str, event_id: str) -> pd.DataFrame:
    return load_locked_score_probabilities(_db, event_id)


@st.cache_data(show_spinner=False, ttl=60)
def cached_load_display_score_probabilities(
    _db: Database,
    db_key: str,
    event_id: str,
    match_id: str,
    current_bucket: int,
) -> tuple[pd.DataFrame, dict[str, object] | None]:
    return load_display_score_probabilities(_db, event_id, match_id, now_utc())


@st.cache_data(show_spinner=False, ttl=30)
def cached_lock_latest_pregame_odds(_db: Database, db_key: str, event_id: str, current_bucket: int) -> int:
    return lock_latest_pregame_odds(_db, event_id, now_utc())


def clear_read_caches() -> None:
    cached_load_matches.clear()
    cached_load_bets.clear()
    cached_load_user_bets.clear()
    cached_load_match_bet_usernames.clear()
    cached_load_favorites.clear()
    cached_load_points.clear()
    cached_load_locked_score_probabilities.clear()
    cached_load_display_score_probabilities.clear()
    cached_lock_latest_pregame_odds.clear()


def now_utc() -> datetime:
    replay_now = st.session_state.get("replay_now_utc")
    if isinstance(replay_now, datetime):
        return replay_now
    return datetime.now(timezone.utc)


def selected_replay_settings() -> ReplaySettings | None:
    replay = os.getenv("TIPPNATION_REPLAY")
    snapshot = os.getenv("TIPPNATION_REPLAY_SNAPSHOT")
    try:
        replay = str(st.query_params.get("replay") or replay or "")
        snapshot = str(st.query_params.get("snapshot") or snapshot or "")
    except Exception:
        pass
    return build_replay_settings(replay, snapshot)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def browser_timezone(config: EventConfig) -> ZoneInfo:
    try:
        timezone_name = getattr(st.context, "timezone", None)
    except Exception:
        timezone_name = None
    if not timezone_name:
        timezone_name = config.timezone
    try:
        return ZoneInfo(str(timezone_name))
    except ZoneInfoNotFoundError:
        return ZoneInfo(config.timezone)


def localize_match_times(df: pd.DataFrame, user_timezone: ZoneInfo) -> pd.DataFrame:
    if df.empty:
        return df
    local = df.copy()
    local["kickoff"] = local["kickoff_utc"].dt.tz_convert(user_timezone)
    local["date"] = local["kickoff"].dt.date
    return local


def current_local_date(user_timezone: ZoneInfo) -> date:
    return pd.Timestamp(now_utc()).tz_convert(user_timezone).date()


def first_kickoff_utc(config: EventConfig) -> datetime:
    return min(match.kickoff_utc for match in config.matches)


def favorites_locked(config: EventConfig) -> bool:
    return now_utc() >= first_kickoff_utc(config)


def default_match_date(matches: pd.DataFrame, user_timezone: ZoneInfo) -> date | None:
    if matches.empty:
        return None
    dates = sorted(matches["date"].unique())
    today = current_local_date(user_timezone)
    return next((date for date in dates if date >= today), dates[-1])


def bootstrap(db: Database, config: EventConfig) -> list[str]:
    secrets = load_secret_sources()
    usernames = tuple(list_auth_users(secrets))
    return list(bootstrap_cached(db, database_cache_key(db), config, config_as_json(config), usernames))


def render_market_odds_status(db: Database, config: EventConfig, replay: ReplaySettings | None, language: str) -> None:
    if replay:
        return
    locked_matches = cached_lock_latest_pregame_odds(db, database_cache_key(db), config.event_id, now_bucket(30))
    if locked_matches:
        cached_load_locked_score_probabilities.clear()
        cached_load_display_score_probabilities.clear()
        st.caption(t(language, "market_odds_locked").format(matches=locked_matches))


def sidebar_auth(players: list[str], language: str, replay: ReplaySettings | None = None) -> str | None:
    with st.sidebar:
        if replay:
            st.caption(f"Replay: {replay.snapshot.label}")
            st.caption(f"Simulated now: {replay.snapshot.now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
            st.caption(f"Local user password: {REPLAY_USER_PASSWORD}")
            st.caption(f"Local admin password: {REPLAY_ADMIN_PASSWORD}")
        st.selectbox(
            t(language, "language"),
            options=list(LANGUAGES.keys()),
            format_func=lambda key: LANGUAGES[key],
            key="language",
        )
        if st.session_state.get("username"):
            st.caption(f"{t(language, 'logged_in_as')}: {st.session_state['username']}")
            if st.button(t(language, "logout"), width="stretch"):
                st.session_state.pop("username", None)
                st.rerun()
            return str(st.session_state["username"])

        username = st.selectbox(t(language, "username"), options=["", *players])
        password = st.text_input(t(language, "password"), type="password")
        if st.button(t(language, "login"), width="stretch"):
            replay_login = bool(replay and username and password == REPLAY_USER_PASSWORD)
            if username and (replay_login or verify_password(password, get_user_password(username))):
                st.session_state["username"] = username
                st.rerun()
            st.warning(t(language, "bad_login"))
    return None


def render_favorite_picker(db: Database, config: EventConfig, username: str, language: str) -> None:
    favorites = cached_load_favorites(db, database_cache_key(db), config.event_id)
    selected = None
    if not favorites.empty:
        row = favorites[favorites["username"] == username]
        if not row.empty:
            selected = str(row.iloc[0]["team_id"])

    if favorites_locked(config):
        message = t(language, "favorite_locked")
        if selected in config.teams:
            message += f" {t(language, 'favorite_locked_choice').format(team=config.teams[selected])}"
        st.info(message)
        return

    st.info(t(language, "favorite_rules"))
    team_ids = list(config.teams.keys())
    index = team_ids.index(selected) if selected in team_ids else None
    cols = st.columns([3, 1])
    with cols[0]:
        choice = st.selectbox(
            t(language, "favorite"),
            options=team_ids,
            format_func=lambda key: config.teams[key],
            index=index,
            placeholder=t(language, "favorite"),
        )
    with cols[1]:
        st.write("")
        st.write("")
        if st.button(t(language, "save_favorite"), width="stretch"):
            set_favorite(db, config.event_id, username, choice)
            cached_load_favorites.clear()
            st.success(t(language, "favorite_saved"))


def render_next_match_status(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    db_key = database_cache_key(db)
    user_timezone = browser_timezone(config)
    matches = localize_match_times(cached_load_matches(db, db_key, config.event_id), user_timezone)
    upcoming = matches[matches["kickoff_utc"] >= pd.Timestamp(now_utc())]
    if upcoming.empty:
        return
    next_match = upcoming.iloc[0]
    match_bets = set(cached_load_match_bet_usernames(db, db_key, config.event_id, str(next_match["match_id"])))
    submitted = [player for player in players if player in match_bets]
    missing = [player for player in players if player not in match_bets]
    with st.container(border=True):
        cols = st.columns([3, 1])
        cols[0].markdown(
            f"**{t(language, 'next_match_status')}** · "
            f"{next_match['team_a_name']} vs {next_match['team_b_name']} · "
            f"{next_match['kickoff'].strftime('%d %b %H:%M')}"
        )
        cols[1].markdown(
            f"**{t(language, 'submitted_count').format(submitted=len(submitted), total=len(players))}**"
        )
        if missing:
            st.caption(t(language, "missing_players").format(players=", ".join(missing)))
        else:
            st.caption(", ".join(submitted))


def render_score_probability_table(db: Database, config: EventConfig, match: pd.Series, language: str) -> None:
    probabilities, metadata = cached_load_display_score_probabilities(
        db,
        database_cache_key(db),
        config.event_id,
        str(match["match_id"]),
        now_bucket(60),
    )
    if probabilities.empty:
        return

    display = probabilities[
        (probabilities["score_a"] <= DISPLAY_SCORE_MAX) & (probabilities["score_b"] <= DISPLAY_SCORE_MAX)
    ].copy()
    if display.empty:
        return
    matrix = (
        display.pivot_table(index="score_a", columns="score_b", values="probability", aggfunc="sum")
        .fillna(0.0)
        .sort_index()
        .sort_index(axis=1)
    )
    captured = metadata.get("captured_at") if metadata else None
    provider = metadata.get("provider") if metadata else None
    with st.expander(t(language, "market_score_probabilities"), expanded=False):
        if captured:
            st.caption(t(language, "market_score_snapshot").format(provider=provider or "market", captured=str(captured)[:16]))
        fig = px.imshow(
            matrix.values,
            text_auto=".1%",
            x=[int(value) for value in matrix.columns],
            y=[int(value) for value in matrix.index],
            color_continuous_scale="YlGnBu",
            aspect="auto",
            labels={
                "x": f"{match['team_b_name']} goals",
                "y": f"{match['team_a_name']} goals",
                "color": "Probability",
            },
        )
        fig.update_xaxes(side="top", dtick=1)
        fig.update_yaxes(autorange="reversed", dtick=1)
        fig.update_traces(hovertemplate=f"{match['team_a_name']} %{{y}} - %{{x}} {match['team_b_name']}<br>Probability: %{{z:.2%}}<extra></extra>")
        fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 8}, coloraxis_colorbar_tickformat=".0%")
        st.plotly_chart(fig, width="stretch")


def render_bets(db: Database, config: EventConfig, players: list[str], username: str | None, language: str) -> None:
    status_placeholder = st.empty()

    def render_status() -> None:
        with status_placeholder.container():
            render_next_match_status(db, config, players, language)

    if username is None:
        render_status()
        st.info(t(language, "login_required"))
        return

    render_favorite_picker(db, config, username, language)
    db_key = database_cache_key(db)
    user_timezone = browser_timezone(config)
    matches = localize_match_times(cached_load_matches(db, db_key, config.event_id), user_timezone)
    selected_date = st.date_input(t(language, "select_date"), value=default_match_date(matches, user_timezone))
    selected = matches[matches["date"] == selected_date].copy()
    if selected.empty:
        render_status()
        st.info(t(language, "no_matches"))
        return

    bets = cached_load_user_bets(db, db_key, config.event_id, username)
    own_bets = bets.set_index("match_id") if not bets.empty else pd.DataFrame()

    selected_matches = list(selected.itertuples(index=False))
    factor_budget = factor_budget_for_matches(config, selected)
    factor_values: dict[str, int] = {}
    for match in selected_matches:
        factor_key = f"factor_{match.match_id}"
        existing = own_bets.loc[match.match_id] if match.match_id in own_bets.index else None
        default_factor = int(existing["factor"]) if existing is not None else 1
        current_factor = int(st.session_state.get(factor_key, default_factor))
        factor_values[str(match.match_id)] = max(1, current_factor)

    editable_rows = []
    for match in selected_matches:
        is_locked = match.kickoff_utc.to_pydatetime() <= now_utc()
        existing = own_bets.loc[match.match_id] if match.match_id in own_bets.index else None
        factor_key = f"factor_{match.match_id}"
        current_factor = factor_values[str(match.match_id)]
        max_factor = current_factor if is_locked else factor_max_for_match(str(match.match_id), factor_values, factor_budget)
        if not is_locked and current_factor > max_factor:
            current_factor = max_factor
            factor_values[str(match.match_id)] = current_factor
            st.session_state[factor_key] = current_factor

        with st.container(border=True):
            st.markdown(
                f"**{match.team_a_name} vs {match.team_b_name}** · "
                f"{match.kickoff.strftime('%H:%M')} · {match.round_name}"
            )
            cols = st.columns([1, 1, 2])
            score_a = cols[0].number_input(
                match.team_a_name,
                min_value=0,
                max_value=30,
                value=int(existing["score_a"]) if existing is not None else 0,
                disabled=is_locked,
                key=f"score_a_{match.match_id}",
            )
            score_b = cols[1].number_input(
                match.team_b_name,
                min_value=0,
                max_value=30,
                value=int(existing["score_b"]) if existing is not None else 0,
                disabled=is_locked,
                key=f"score_b_{match.match_id}",
            )
            if is_locked:
                factor = cols[2].number_input(
                    "Factor",
                    min_value=current_factor,
                    max_value=current_factor,
                    value=current_factor,
                    disabled=True,
                    key=f"{factor_key}_locked",
                )
            elif max_factor == 1:
                st.session_state[factor_key] = 1
                factor = cols[2].number_input(
                    "Factor",
                    min_value=1,
                    max_value=1,
                    value=1,
                    disabled=True,
                    key=f"{factor_key}_fixed",
                )
            else:
                factor = cols[2].slider(
                    "Factor",
                    min_value=1,
                    max_value=max_factor,
                    value=current_factor,
                    disabled=is_locked,
                    key=factor_key,
                )
            factor_values[str(match.match_id)] = int(factor)
            if is_locked:
                st.caption(t(language, "past_locked"))
            else:
                render_score_probability_table(db, config, pd.Series(match._asdict()), language)
                editable_rows.append(
                    {
                        "match_id": match.match_id,
                        "score_a": int(score_a),
                        "score_b": int(score_b),
                        "factor": int(factor),
                    }
                )

    factor_sum = sum(factor_values.values())
    st.caption(f"{t(language, 'factor_budget')}: {factor_sum} / {factor_budget}")
    submitted = st.button(
        t(language, "submit_bets"),
        type="primary",
        disabled=not editable_rows,
        width="stretch",
    )

    if editable_rows and submitted:
        if factor_sum > factor_budget:
            st.warning(f"{t(language, 'factor_budget')}: {factor_sum} / {factor_budget}")
            return
        upsert_bets(db, config.event_id, username, editable_rows)
        cached_load_bets.clear()
        cached_load_user_bets.clear()
        cached_load_match_bet_usernames.clear()
        st.success(t(language, "bets_saved"))
    render_status()


@st.fragment(run_every=READ_REFRESH_INTERVAL)
def render_entries(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    db_key = database_cache_key(db)
    favorites = cached_load_favorites(db, db_key, config.event_id)
    if favorites_locked(config) and not favorites.empty:
        favorites["team"] = favorites["team_id"].map(config.teams)
        st.markdown(f"### {t(language, 'favorites')}")
        st.dataframe(favorites[["username", "team"]], hide_index=True, width="stretch")

    user_timezone = browser_timezone(config)
    matches = localize_match_times(cached_load_matches(db, db_key, config.event_id, now_bucket(60)), user_timezone)
    bets = cached_load_bets(db, db_key, config.event_id)
    if bets.empty:
        st.info(t(language, "no_matches"))
        return
    visible_matches = matches[matches["kickoff_utc"] < pd.Timestamp(now_utc())]
    rows = bets.merge(visible_matches, on=["event_id", "match_id"], how="inner")
    if rows.empty:
        st.info(t(language, "visible_after_kickoff"))
        return
    selected_players = st.multiselect(t(language, "username"), options=players, default=players)
    rows = rows[rows["username"].isin(selected_players)]
    rows["bet"] = rows["score_a"].astype(str) + ":" + rows["score_b"].astype(str) + " ×" + rows["factor"].astype(str)
    if "auto_generated" in rows.columns:
        rows.loc[rows["auto_generated"].fillna(0).astype(int) == 1, "bet"] += " (auto)"
    rows["kickoff"] = rows["kickoff"].dt.strftime("%Y-%m-%d %H:%M")
    display = rows.pivot_table(
        index=["kickoff", "team_a_name", "team_b_name", "result_a", "result_b"],
        columns="username",
        values="bet",
        aggfunc="first",
    ).reset_index().sort_values("kickoff", ascending=False)
    st.dataframe(display, hide_index=True, width="stretch")


@st.fragment(run_every=READ_REFRESH_INTERVAL)
def render_stats(db: Database, config: EventConfig, language: str) -> None:
    points = cached_load_points(db, database_cache_key(db), config.event_id, now_bucket(60))
    if points.empty:
        st.info(t(language, "no_points"))
        return

    st.markdown(f"### {t(language, 'standings')}")
    standings = (
        points.groupby("username", as_index=False)[["base", "fbase", "exotic", "favorite", "kanonenwilli", "final"]]
        .sum()
        .sort_values("final", ascending=False)
    )
    standings.insert(0, "rank", standings["final"].rank(method="min", ascending=False).astype(int))
    st.dataframe(standings, hide_index=True, width="stretch")
    standings_chart_data = standings[["username", *POINT_COMPOSITION_COLUMNS]].melt(
        id_vars="username",
        value_vars=POINT_COMPOSITION_COLUMNS,
        var_name="component",
        value_name="points",
    )
    fig = px.bar(standings_chart_data, x="username", y="points", color="component")
    fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 8}, xaxis_title=t(language, "username"), yaxis_title="Points")
    st.plotly_chart(fig, width="stretch")

    st.markdown(f"### {t(language, 'points_by_match')}")
    points_by_match = points.copy()
    points_by_match["kickoff"] = points_by_match["kickoff_utc"].dt.tz_convert(browser_timezone(config)).dt.strftime(
        "%Y-%m-%d %H:%M"
    )
    by_match = points_by_match.pivot_table(
        index=["kickoff", "team_a_name", "team_b_name", "result_a", "result_b"],
        columns="username",
        values="final",
        aggfunc="sum",
    ).reset_index().sort_values("kickoff", ascending=False)
    st.dataframe(by_match, hide_index=True, width="stretch")

    progression = points.sort_values(["sort_order", "username"]).copy()
    progression["match_number"] = progression["sort_order"].astype(int)
    progression["running"] = progression.groupby("username")["final"].cumsum()
    chart = progression.pivot_table(index="match_number", columns="username", values="running", aggfunc="max")
    st.line_chart(chart)


@st.fragment(run_every=READ_REFRESH_INTERVAL)
def render_breakdown(db: Database, config: EventConfig, players: list[str], username: str | None, language: str) -> None:
    db_key = database_cache_key(db)
    points = cached_load_points(db, db_key, config.event_id, now_bucket(60))
    if points.empty:
        st.info(t(language, "no_points"))
        return

    user_timezone = browser_timezone(config)
    display_points = points.copy()
    bets = cached_load_bets(db, db_key, config.event_id)
    if not bets.empty:
        bet_columns = ["match_id", "username", "score_a", "score_b", "factor"]
        if "auto_generated" in bets.columns:
            bet_columns.append("auto_generated")
        bet_scores = bets[bet_columns].copy()
        display_points = display_points.merge(bet_scores, on=["match_id", "username"], how="left")
    else:
        display_points["score_a"] = pd.NA
        display_points["score_b"] = pd.NA
        display_points["factor"] = pd.NA
        display_points["auto_generated"] = 0
    if "auto_generated" not in display_points.columns:
        display_points["auto_generated"] = 0
    display_points["kickoff"] = display_points["kickoff_utc"].dt.tz_convert(user_timezone).dt.strftime("%Y-%m-%d %H:%M")
    display_points["match_number"] = display_points["sort_order"].astype(int)
    display_points["match"] = display_points["team_a_name"] + " vs " + display_points["team_b_name"]
    display_points["result"] = (
        display_points["result_a"].astype("Int64").astype(str) + ":" + display_points["result_b"].astype("Int64").astype(str)
    )
    display_points["bet"] = (
        display_points["score_a"].astype("Int64").astype(str) + ":" + display_points["score_b"].astype("Int64").astype(str)
        + " (x"
        + display_points["factor"].astype("Int64").astype(str)
        + ")"
    )
    display_points.loc[display_points["auto_generated"].fillna(0).astype(int) == 1, "bet"] += " (auto)"

    st.markdown(f"### {t(language, 'match_breakdown')}")
    match_options = (
        display_points[["match_id", "match_number", "kickoff", "match", "result"]]
        .drop_duplicates("match_id")
        .sort_values("match_number", ascending=False)
    )
    selected_match_id = st.selectbox(
        t(language, "select_match"),
        options=list(match_options["match_id"]),
        format_func=lambda match_id: _format_match_option(match_options, str(match_id)),
        key="breakdown_match",
    )
    match_rows = display_points[display_points["match_id"] == selected_match_id].sort_values("final", ascending=False)
    st.dataframe(match_rows[["username", "bet", *POINT_DISPLAY_COLUMNS]], hide_index=True, width="stretch")
    match_chart_data = match_rows[["username", *POINT_COMPOSITION_COLUMNS]].melt(
        id_vars="username",
        value_vars=POINT_COMPOSITION_COLUMNS,
        var_name="component",
        value_name="points",
    )
    fig = px.bar(match_chart_data, x="username", y="points", color="component")
    fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 8}, xaxis_title=t(language, "username"), yaxis_title="Points")
    st.plotly_chart(fig, width="stretch")

    st.markdown(f"### {t(language, 'user_breakdown')}")
    user_options = [player for player in players if player in set(display_points["username"])]
    default_user_index = user_options.index(username) if username in user_options else None
    selected_user = st.selectbox(
        t(language, "select_user"),
        options=user_options,
        index=default_user_index,
        placeholder=t(language, "select_user"),
        key=f"breakdown_user_{username or 'anonymous'}",
    )
    if selected_user is None:
        return

    user_rows = display_points[display_points["username"] == selected_user].sort_values("match_number", ascending=False)
    st.dataframe(
        user_rows[["kickoff", "match", "bet", "result", *POINT_DISPLAY_COLUMNS]],
        hide_index=True,
        width="stretch",
    )

    st.markdown(f"### {t(language, 'points_composition')}")
    progression = display_points[display_points["username"] == selected_user].sort_values("match_number").copy()
    progression[POINT_COMPOSITION_COLUMNS] = progression[POINT_COMPOSITION_COLUMNS].cumsum()
    chart_data = progression[["match_number", *POINT_COMPOSITION_COLUMNS]].melt(
        id_vars="match_number",
        value_vars=POINT_COMPOSITION_COLUMNS,
        var_name="component",
        value_name="points",
    )
    fig = px.area(chart_data, x="match_number", y="points", color="component")
    fig.update_layout(margin={"l": 8, "r": 8, "t": 8, "b": 8}, xaxis_title=t(language, "select_match"), yaxis_title="Points")
    st.plotly_chart(fig, width="stretch")


def _format_match_option(match_options: pd.DataFrame, match_id: str) -> str:
    row = match_options.set_index("match_id").loc[match_id]
    return f"{int(row['match_number'])} · {row['kickoff']} · {row['match']} ({row['result']})"


def render_heatmaps(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    db_key = database_cache_key(db)
    matches = localize_match_times(cached_load_matches(db, db_key, config.event_id), browser_timezone(config))
    visible_matches = matches[matches["kickoff_utc"] < pd.Timestamp(now_utc())]
    if visible_matches.empty:
        st.info(t(language, "visible_after_kickoff"))
        return
    selected_match_id = st.selectbox(
        "Match",
        options=list(visible_matches["match_id"]),
        format_func=lambda match_id: (
            visible_matches.set_index("match_id").loc[match_id, "team_a_name"]
            + " vs "
            + visible_matches.set_index("match_id").loc[match_id, "team_b_name"]
        ),
    )
    player = st.selectbox("Player", options=players)
    opponent = st.selectbox("Opponent", options=["", *[name for name in players if name != player]])
    bets = cached_load_bets(db, db_key, config.event_id)
    favorites = cached_load_favorites(db, db_key, config.event_id)
    market_probabilities = cached_load_locked_score_probabilities(db, db_key, config.event_id)
    match_data = matches[matches["match_id"] == selected_match_id].copy()
    if bets.empty or bets[bets["match_id"] == selected_match_id].empty:
        st.info(t(language, "no_matches"))
        return

    values = []
    for result_a in range(6):
        row = []
        for result_b in range(6):
            simulated = match_data.copy()
            simulated["result_a"] = result_a
            simulated["result_b"] = result_b
            points, _ = compute_points(simulated, bets[bets["match_id"] == selected_match_id], favorites, config, market_probabilities)
            player_points = int(points[points["username"] == player]["final"].sum())
            opponent_points = int(points[points["username"] == opponent]["final"].sum()) if opponent else 0
            row.append(player_points - opponent_points)
        values.append(row)

    fig = px.imshow(
        values,
        text_auto=True,
        x=list(range(6)),
        y=list(range(6)),
        labels={"x": "Team B goals", "y": "Team A goals", "color": "Points"},
    )
    fig.update_xaxes(side="top")
    st.plotly_chart(fig, width="stretch")


def render_help(language: str) -> None:
    manual = "docs/MANUAL_DE.md" if language == "de" else "docs/MANUAL_EN.md"
    if Path(manual).exists():
        st.markdown(Path(manual).read_text(encoding="utf-8"))


def render_admin(
    db: Database,
    config: EventConfig,
    players: list[str],
    language: str,
    replay: ReplaySettings | None = None,
) -> None:
    password = st.text_input(t(language, "admin_password"), type="password")
    replay_admin = bool(replay and password == REPLAY_ADMIN_PASSWORD)
    if not (replay_admin or verify_password(password, get_admin_password())):
        st.stop()

    if st.button(t(language, "initialize_db"), width="stretch"):
        initialize_database(db, config, players)
        clear_read_caches()
        bootstrap_cached.clear()
        st.success("Database synced.")

    matches = cached_load_matches(db, database_cache_key(db), config.event_id)
    editable = matches[["match_id", "team_a_name", "team_b_name", "kickoff_utc", "result_a", "result_b", "status"]].copy()
    edited = st.data_editor(
        editable,
        hide_index=True,
        width="stretch",
        column_config={
            "result_a": st.column_config.NumberColumn("Result A", min_value=0, max_value=30, step=1),
            "result_b": st.column_config.NumberColumn("Result B", min_value=0, max_value=30, step=1),
            "status": st.column_config.SelectboxColumn("Status", options=["scheduled", "live", "completed"]),
        },
    )
    cols = st.columns(2)
    if cols[0].button(t(language, "set_results"), width="stretch"):
        set_match_results(db, config.event_id, edited)
        cached_load_matches.clear()
        cached_load_points.clear()
        st.success(t(language, "results_saved"))
    if cols[1].button(t(language, "recompute_points"), type="primary", width="stretch"):
        points = compute_and_store_points(db, config)
        cached_load_bets.clear()
        cached_load_user_bets.clear()
        cached_load_match_bet_usernames.clear()
        cached_load_points.clear()
        st.success(f"{t(language, 'points_saved')} ({len(points)} rows)")


def main() -> None:
    st.set_page_config(page_title="TippNation", page_icon="🏆", layout="wide")
    replay = selected_replay_settings()
    if replay:
        st.session_state["replay_now_utc"] = replay.snapshot.now_utc
        config_path = replay.config_path
    else:
        st.session_state.pop("replay_now_utc", None)
        config_path = DEFAULT_EVENT_CONFIG

    config = get_event_config(str(config_path))
    db = get_database(str(config_path), replay.snapshot.key if replay else None)
    players = bootstrap(db, config)
    language = st.session_state.get("language", config.language_default)
    username = sidebar_auth(players, language, replay)
    language = st.session_state.get("language", language)

    st.title(f"TippNation · {config.name}")
    if replay:
        st.info(
            f"{replay.snapshot.label}: {replay.snapshot.description} "
            f"The local scratch database is {display_path(replay.db_path)} and resets when this replay is restarted."
        )
    render_market_odds_status(db, config, replay, language)
    tabs = st.tabs(
        [
            t(language, "bets"),
            t(language, "entries"),
            t(language, "heatmaps"),
            t(language, "breakdown"),
            t(language, "stats"),
            t(language, "help"),
            t(language, "admin"),
        ]
    )
    with tabs[0]:
        render_bets(db, config, players, username, language)
    with tabs[1]:
        render_entries(db, config, players, language)
    with tabs[2]:
        render_heatmaps(db, config, players, language)
    with tabs[3]:
        render_breakdown(db, config, players, username, language)
    with tabs[4]:
        render_stats(db, config, language)
    with tabs[5]:
        render_help(language)
    with tabs[6]:
        render_admin(db, config, players, language, replay)


if __name__ == "__main__":
    main()
