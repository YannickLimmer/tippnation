from __future__ import annotations

import hashlib
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from tippnation.admin import compute_and_store_points, initialize_database, set_match_results
from tippnation.config import DEFAULT_EVENT_CONFIG, EventConfig, load_event_config
from tippnation.db import Database, connect
from tippnation.i18n import LANGUAGES, t
from tippnation.odds import DISPLAY_SCORE_MAX, keep_betfair_session_alive, odds_refresh_decision, refresh_market_odds_if_due
from tippnation.repository import (
    list_players,
    load_bets,
    load_display_score_probabilities,
    load_favorites,
    load_locked_score_probabilities,
    load_matches,
    load_points,
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
    get_betfair_settings,
    get_database_settings,
    get_user_password,
    list_auth_users,
    load_secret_sources,
    verify_password,
)


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


@st.cache_data(show_spinner=False, ttl=3600)
def cached_betfair_keep_alive(settings_cache_key: str) -> dict[str, object]:
    settings = get_betfair_settings()
    if settings is None:
        return {"status": "NOT_CONFIGURED"}
    return keep_betfair_session_alive(settings)


def betfair_settings_cache_key() -> str | None:
    settings = get_betfair_settings()
    if settings is None:
        return None
    raw = f"{settings.app_key}:{settings.session_token}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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


def localize_match_times(df: pd.DataFrame, config: EventConfig) -> pd.DataFrame:
    if df.empty:
        return df
    local = df.copy()
    local["kickoff_local"] = local["kickoff_utc"].dt.tz_convert(config.timezone)
    local["date"] = local["kickoff_local"].dt.date
    return local


def current_local_date(config: EventConfig) -> date:
    return pd.Timestamp(now_utc()).tz_convert(config.timezone).date()


def first_kickoff_utc(config: EventConfig) -> datetime:
    return min(match.kickoff_utc for match in config.matches)


def favorites_locked(config: EventConfig) -> bool:
    return now_utc() >= first_kickoff_utc(config)


def default_match_date(matches: pd.DataFrame, config: EventConfig) -> date | None:
    if matches.empty:
        return None
    dates = sorted(matches["date"].unique())
    today = current_local_date(config)
    return next((date for date in dates if date >= today), dates[-1])


def bootstrap(db: Database, config: EventConfig) -> list[str]:
    secrets = load_secret_sources()
    usernames = list_auth_users(secrets)
    initialize_database(db, config, usernames)
    return list_players(db)


def render_market_odds_refresh(db: Database, config: EventConfig, replay: ReplaySettings | None, language: str) -> None:
    if replay:
        return
    matches = load_matches(db, config.event_id)
    settings = get_betfair_settings()
    if settings is not None:
        keep_alive_key = betfair_settings_cache_key()
        if keep_alive_key is not None:
            keep_alive_result = cached_betfair_keep_alive(keep_alive_key)
            if str(keep_alive_result.get("status", "")).upper() not in {"SUCCESS", "NOT_CONFIGURED"}:
                st.warning(t(language, "betfair_keep_alive_failed").format(status=keep_alive_result.get("status", "unknown")))
    current_time = now_utc()
    decision = odds_refresh_decision(db, config.event_id, matches, current_time)
    if settings and config.betfair_competition_id and decision.due:
        with st.status(t(language, "market_odds_updating"), expanded=False):
            st.write(decision.reason)
            result = refresh_market_odds_if_due(db, config, settings, matches, current_time)
    else:
        result = refresh_market_odds_if_due(db, config, settings, matches, current_time)

    if result.already_running:
        st.caption(t(language, "market_odds_running"))
    elif result.error:
        st.warning(t(language, "market_odds_failed").format(error=result.error[:240]))
    elif result.attempted and result.updated_matches:
        st.success(t(language, "market_odds_updated").format(matches=result.updated_matches))
    elif result.locked_matches:
        st.caption(t(language, "market_odds_locked").format(matches=result.locked_matches))


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
            if st.button(t(language, "logout"), use_container_width=True):
                st.session_state.pop("username", None)
                st.rerun()
            return str(st.session_state["username"])

        username = st.selectbox(t(language, "username"), options=["", *players])
        password = st.text_input(t(language, "password"), type="password")
        if st.button(t(language, "login"), use_container_width=True):
            replay_login = bool(replay and username and password == REPLAY_USER_PASSWORD)
            if username and (replay_login or verify_password(password, get_user_password(username))):
                st.session_state["username"] = username
                st.rerun()
            st.warning(t(language, "bad_login"))
    return None


def render_favorite_picker(db: Database, config: EventConfig, username: str, language: str) -> None:
    favorites = load_favorites(db, config.event_id)
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
        if st.button(t(language, "save_favorite"), use_container_width=True):
            set_favorite(db, config.event_id, username, choice)
            st.success(t(language, "favorite_saved"))


def render_next_match_status(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    matches = localize_match_times(load_matches(db, config.event_id), config)
    upcoming = matches[matches["kickoff_utc"] >= pd.Timestamp(now_utc())]
    if upcoming.empty:
        return
    next_match = upcoming.iloc[0]
    bets = load_bets(db, config.event_id)
    match_bets = set() if bets.empty else set(bets[bets["match_id"] == next_match["match_id"]]["username"])
    submitted = [player for player in players if player in match_bets]
    missing = [player for player in players if player not in match_bets]
    with st.container(border=True):
        cols = st.columns([3, 1])
        cols[0].markdown(
            f"**{t(language, 'next_match_status')}** · "
            f"{next_match['team_a_name']} vs {next_match['team_b_name']} · "
            f"{next_match['kickoff_local'].strftime('%d %b %H:%M')}"
        )
        cols[1].markdown(
            f"**{t(language, 'submitted_count').format(submitted=len(submitted), total=len(players))}**"
        )
        if missing:
            st.caption(t(language, "missing_players").format(players=", ".join(missing)))
        else:
            st.caption(", ".join(submitted))


def render_score_probability_table(db: Database, config: EventConfig, match: pd.Series, language: str) -> None:
    probabilities, metadata = load_display_score_probabilities(db, config.event_id, str(match["match_id"]), now_utc())
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
        st.plotly_chart(fig, use_container_width=True)


def render_bets(db: Database, config: EventConfig, players: list[str], username: str | None, language: str) -> None:
    render_next_match_status(db, config, players, language)
    if username is None:
        st.info(t(language, "login_required"))
        return

    feedback_key = f"bets_saved_message_{config.event_id}_{username}"
    if feedback_key in st.session_state:
        st.success(st.session_state.pop(feedback_key))

    render_favorite_picker(db, config, username, language)
    matches = localize_match_times(load_matches(db, config.event_id), config)
    selected_date = st.date_input(t(language, "select_date"), value=default_match_date(matches, config))
    selected = matches[matches["date"] == selected_date].copy()
    if selected.empty:
        st.info(t(language, "no_matches"))
        return

    bets = load_bets(db, config.event_id)
    own_bets = pd.DataFrame()
    if not bets.empty:
        own_bets = bets[bets["username"] == username].set_index("match_id")

    editable_rows = []
    factor_sum = 0
    max_factor_sum = 0
    for match in selected.itertuples(index=False):
        rule = config.rules.get(str(match.round_name), config.rules.get("knockout", config.rules["group"]))
        max_factor_sum += rule.max_factor
        is_locked = match.kickoff_utc.to_pydatetime() <= now_utc()
        existing = own_bets.loc[match.match_id] if match.match_id in own_bets.index else None
        with st.container(border=True):
            st.markdown(
                f"**{match.team_a_name} vs {match.team_b_name}** · "
                f"{match.kickoff_local.strftime('%H:%M')} · {match.round_name}"
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
            factor = cols[2].slider(
                "Factor",
                min_value=1,
                max_value=rule.max_factor,
                value=int(existing["factor"]) if existing is not None else 1,
                disabled=is_locked,
                key=f"factor_{match.match_id}",
            )
            factor_sum += int(factor)
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

    st.caption(f"{t(language, 'factor_budget')}: {factor_sum} / {max_factor_sum}")
    if editable_rows and st.button(t(language, "submit_bets"), type="primary", use_container_width=True):
        if factor_sum > max_factor_sum:
            st.warning(f"{t(language, 'factor_budget')}: {factor_sum} / {max_factor_sum}")
            return
        upsert_bets(db, config.event_id, username, editable_rows)
        st.session_state[feedback_key] = t(language, "bets_saved")
        st.rerun()


def render_entries(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    favorites = load_favorites(db, config.event_id)
    if favorites_locked(config) and not favorites.empty:
        favorites["team"] = favorites["team_id"].map(config.teams)
        st.markdown(f"### {t(language, 'favorites')}")
        st.dataframe(favorites[["username", "team"]], hide_index=True, use_container_width=True)

    matches = localize_match_times(load_matches(db, config.event_id), config)
    bets = load_bets(db, config.event_id)
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
    display = rows.pivot_table(
        index=["kickoff_local", "team_a_name", "team_b_name", "result_a", "result_b"],
        columns="username",
        values="bet",
        aggfunc="first",
    ).reset_index().sort_values("kickoff_local", ascending=False)
    st.dataframe(display, hide_index=True, use_container_width=True)


def render_stats(db: Database, config: EventConfig, language: str) -> None:
    points = load_points(db, config.event_id)
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
    st.dataframe(standings, hide_index=True, use_container_width=True)

    st.markdown(f"### {t(language, 'points_by_match')}")
    by_match = points.pivot_table(
        index=["kickoff_utc", "team_a_name", "team_b_name", "result_a", "result_b"],
        columns="username",
        values="final",
        aggfunc="sum",
    ).reset_index().sort_values("kickoff_utc", ascending=False)
    st.dataframe(by_match, hide_index=True, use_container_width=True)

    progression = points.sort_values(["kickoff_utc"]).copy()
    progression["running"] = progression.groupby("username")["final"].cumsum()
    chart = progression.pivot_table(index="kickoff_utc", columns="username", values="running", aggfunc="max")
    st.line_chart(chart)


def render_heatmaps(db: Database, config: EventConfig, players: list[str], language: str) -> None:
    matches = localize_match_times(load_matches(db, config.event_id), config)
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
    bets = load_bets(db, config.event_id)
    favorites = load_favorites(db, config.event_id)
    market_probabilities = load_locked_score_probabilities(db, config.event_id)
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
    st.plotly_chart(fig, use_container_width=True)


def render_help(language: str) -> None:
    manual = "MANUAL_DE.md" if language == "de" else "MANUAL_EN.md"
    instructions = "Instructions_DE.md" if language == "de" else "Instructions_EN.md"
    for path in (manual, instructions):
        if Path(path).exists():
            with st.expander(path):
                st.markdown(Path(path).read_text(encoding="utf-8"))


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

    if st.button(t(language, "initialize_db"), use_container_width=True):
        initialize_database(db, config, players)
        st.success("Database synced.")

    matches = load_matches(db, config.event_id)
    editable = matches[["match_id", "team_a_name", "team_b_name", "kickoff_utc", "result_a", "result_b", "status"]].copy()
    edited = st.data_editor(
        editable,
        hide_index=True,
        use_container_width=True,
        column_config={
            "result_a": st.column_config.NumberColumn("Result A", min_value=0, max_value=30, step=1),
            "result_b": st.column_config.NumberColumn("Result B", min_value=0, max_value=30, step=1),
            "status": st.column_config.SelectboxColumn("Status", options=["scheduled", "completed"]),
        },
    )
    cols = st.columns(2)
    if cols[0].button(t(language, "set_results"), use_container_width=True):
        set_match_results(db, config.event_id, edited)
        st.success(t(language, "results_saved"))
    if cols[1].button(t(language, "recompute_points"), type="primary", use_container_width=True):
        points = compute_and_store_points(db, config)
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
    render_market_odds_refresh(db, config, replay, language)
    tabs = st.tabs(
        [
            t(language, "bets"),
            t(language, "entries"),
            t(language, "heatmaps"),
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
        render_stats(db, config, language)
    with tabs[4]:
        render_help(language)
    with tabs[5]:
        render_admin(db, config, players, language, replay)


if __name__ == "__main__":
    main()
