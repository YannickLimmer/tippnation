from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import EventConfig, MatchConfig, ROOT
from .db import Database


THESPORTSDB_BASE_URL = "https://www.thesportsdb.com/api/v1/json"
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_THESPORTSDB_KEY = "123"
DEFAULT_STATE_PATH = ROOT / "data" / "result_poll_state.json"
DEFAULT_MATCH_DURATION = timedelta(hours=2)
DEFAULT_RESULT_GRACE = timedelta(minutes=15)
DEFAULT_RESULT_SETTLE_WINDOW = timedelta(hours=4)
DEFAULT_LOOKBACK = timedelta(days=2)
DEFAULT_LATE_RECHECK = timedelta(minutes=15)
DEFAULT_MAX_LATE_RECHECK = timedelta(hours=2)
DEFAULT_MAX_API_REQUESTS = 20
DEFAULT_API_FOOTBALL_DAILY_BUDGET = 7500
API_FOOTBALL_FINAL_STATUSES = {"FT", "AET", "PEN"}
API_FOOTBALL_UNSCORABLE_STATUSES = {"NS", "TBD", "PST", "CANC", "ABD", "AWD", "WO"}
TEAM_ALIASES = {
    "cabo verde": "cape verde",
    "cape verde islands": "cape verde",
    "congo dr": "dr congo",
    "cote d ivoire": "ivory coast",
    "czech republic": "czechia",
    "d r congo": "dr congo",
    "korea republic": "south korea",
    "rep of ireland": "ireland",
    "republic of ireland": "ireland",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "usa": "united states",
    "u s a": "united states",
    "us": "united states",
}
SEARCH_NAME_ALIASES = {
    "Cape Verde": ["Cape Verde", "Cabo Verde", "Cape Verde Islands"],
    "Côte d'Ivoire": ["Côte d'Ivoire", "Ivory Coast"],
    "Czechia": ["Czechia", "Czech Republic"],
    "DR Congo": ["DR Congo", "Congo DR", "Democratic Republic of Congo"],
    "Republic of Ireland": ["Republic of Ireland", "Ireland"],
    "Türkiye": ["Türkiye", "Turkey"],
    "USA": ["USA", "United States"],
}


@dataclass(frozen=True)
class ResultPollResult:
    attempted_api: bool
    checked_db: bool
    candidates: int
    already_completed: int
    updated_matches: int
    unmatched_matches: int
    api_requests: int
    recomputed_points: bool
    skipped_reason: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class ProviderResult:
    event_id: str
    home: str
    away: str
    kickoff_utc: datetime | None
    home_score: int
    away_score: int
    status: str | None
    provider: str = "unknown"
    is_final: bool = False


class TheSportsDBClient:
    def __init__(self, api_key: str = DEFAULT_THESPORTSDB_KEY, timeout: int = 20) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def events_for_day(self, day: date, sport: str = "Soccer") -> list[dict[str, Any]]:
        return self._get(
            "eventsday.php",
            {"d": day.isoformat(), "s": sport},
        ).get("events") or []

    def past_league_events(self, league_id: str, season: str | None = None) -> list[dict[str, Any]]:
        params = {"id": league_id}
        if season:
            params["s"] = season
        return self._get("eventspastleague.php", params).get("events") or []

    def search_events(self, event_name: str, season: str | None = None) -> list[dict[str, Any]]:
        params = {"e": event_name}
        if season:
            params["s"] = season
        return self._get("searchevents.php", params).get("event") or []

    def lookup_event(self, event_id: str) -> list[dict[str, Any]]:
        return self._get("lookupevent.php", {"id": event_id}).get("events") or []

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{THESPORTSDB_BASE_URL}/{self.api_key}/{endpoint}?{query}"
        request = urllib.request.Request(url, headers={"User-Agent": "tippnation-results/0.1"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"TheSportsDB {endpoint} failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"TheSportsDB {endpoint} failed: {exc.reason}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"TheSportsDB {endpoint} returned non-JSON response: {raw[:300]}") from exc
        return data if isinstance(data, dict) else {}


class ApiFootballClient:
    def __init__(self, api_key: str, timeout: int = 20) -> None:
        self.api_key = api_key
        self.timeout = timeout

    def fixtures_by_ids(self, fixture_ids: list[str]) -> list[dict[str, Any]]:
        if not fixture_ids:
            return []
        return self._get("fixtures", {"ids": "-".join(fixture_ids)}).get("response") or []

    def fixtures_by_window(
        self,
        *,
        league_id: str,
        season: str,
        start: date,
        end: date,
    ) -> list[dict[str, Any]]:
        return self._get(
            "fixtures",
            {
                "league": league_id,
                "season": season,
                "from": start.isoformat(),
                "to": end.isoformat(),
                "timezone": "UTC",
            },
        ).get("response") or []

    def fixtures_by_date(self, day: date) -> list[dict[str, Any]]:
        return self._get(
            "fixtures",
            {
                "date": day.isoformat(),
                "timezone": "UTC",
            },
        ).get("response") or []

    def _get(self, endpoint: str, params: dict[str, str]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{API_FOOTBALL_BASE_URL}/{endpoint}?{query}"
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "tippnation-results/0.1",
                "x-apisports-key": self.api_key,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"API-FOOTBALL {endpoint} failed: HTTP {exc.code} {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"API-FOOTBALL {endpoint} failed: {exc.reason}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"API-FOOTBALL {endpoint} returned non-JSON response: {raw[:300]}") from exc
        if not isinstance(data, dict):
            return {}
        errors = data.get("errors")
        if errors:
            raise RuntimeError(f"API-FOOTBALL {endpoint} returned errors: {json.dumps(errors, sort_keys=True)[:300]}")
        return data


def poll_match_results(
    db: Database,
    config: EventConfig,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    api_key: str = DEFAULT_THESPORTSDB_KEY,
    api_football_key: str | None = None,
    provider: str = "auto",
    now: datetime | None = None,
    force: bool = False,
    backfill: bool = False,
    dry_run: bool = False,
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
    api_football_daily_budget: int = DEFAULT_API_FOOTBALL_DAILY_BUDGET,
) -> ResultPollResult:
    current_time = _to_utc(now or datetime.now(timezone.utc))
    state = _load_state(state_path)
    candidates = _local_candidates(config, state, current_time, force, backfill)
    if not candidates:
        return ResultPollResult(False, False, 0, 0, 0, 0, 0, False, skipped_reason="No locally due matches.")

    existing = _load_match_result_status(db, config.event_id, [match.match_id for match in candidates])
    unresolved: list[MatchConfig] = []
    already_completed = 0
    for match in candidates:
        row = existing.get(match.match_id)
        entry = _state_entry(state, config.event_id, match.match_id)
        if backfill and row and _db_row_completed(row):
            already_completed += 1
            continue
        if row and _db_row_completed(row) and not force and not _state_provider_owned(entry):
            already_completed += 1
            if not dry_run:
                _mark_completed(state, config.event_id, match.match_id, current_time, "database")
            continue
        unresolved.append(match)

    if not unresolved:
        if not dry_run:
            _save_state(state_path, state)
        return ResultPollResult(False, True, len(candidates), already_completed, 0, 0, 0, False, skipped_reason="Due matches already have results.")

    provider_name = _select_provider(config, unresolved, provider, api_football_key)
    effective_max_api_requests = max_api_requests
    if provider_name == "api-football":
        remaining_budget = _api_football_remaining_budget(state, current_time, api_football_daily_budget)
        if remaining_budget <= 0:
            return ResultPollResult(
                attempted_api=False,
                checked_db=True,
                candidates=len(candidates),
                already_completed=already_completed,
                updated_matches=0,
                unmatched_matches=len(unresolved),
                api_requests=0,
                recomputed_points=False,
                skipped_reason="Local API-FOOTBALL daily budget is exhausted.",
            )
        effective_max_api_requests = min(max_api_requests, remaining_budget)
    try:
        provider_events, api_requests = _load_provider_events(
            config,
            unresolved,
            provider_name=provider_name,
            thesportsdb_key=api_key,
            api_football_key=api_football_key,
            max_api_requests=effective_max_api_requests,
        )
    except Exception as exc:
        if not dry_run:
            _schedule_retry(state, config.event_id, unresolved, current_time)
            _save_state(state_path, state)
        return ResultPollResult(True, True, len(candidates), already_completed, 0, len(unresolved), 0, False, error=str(exc))

    updates: list[dict[str, Any]] = []
    score_updates = 0
    unmatched: list[MatchConfig] = []
    for match in unresolved:
        result = _match_provider_result(match, provider_events)
        if result is None:
            unmatched.append(match)
            continue
        result_a, result_b = (result.away_score, result.home_score) if _is_swapped(match, result) else (result.home_score, result.away_score)
        row = existing.get(match.match_id)
        score_changed = (
            row is None
            or row.get("result_a") is None
            or row.get("result_b") is None
            or int(row["result_a"]) != result_a
            or int(row["result_b"]) != result_b
        )
        status = "completed" if result.is_final else "live"
        status_changed = row is None or str(row.get("status") or "") != status
        if not score_changed and not status_changed:
            if not dry_run:
                _mark_provider_seen(state, config.event_id, match.match_id, current_time, result, result_a, result_b)
            continue
        if score_changed:
            score_updates += 1
        updates.append(
            {
                "match_id": match.match_id,
                "result_a": result_a,
                "result_b": result_b,
                "status": status,
            }
        )
        if not dry_run:
            _mark_provider_seen(state, config.event_id, match.match_id, current_time, result, result_a, result_b)
            if result.is_final and current_time >= _settle_until(match):
                _mark_completed(state, config.event_id, match.match_id, current_time, result.provider)

    if unmatched and not dry_run and any(current_time > _settle_until(match) for match in unmatched):
        _schedule_retry(state, config.event_id, unmatched, current_time)
    if provider_name == "api-football" and api_requests and not dry_run:
        _record_api_football_requests(state, current_time, api_requests)
    if updates and not dry_run:
        from .admin import compute_and_store_points
        from .knockout import sync_knockout_advancement
        from .repository import update_results

        update_results(db, config.event_id, updates)
        sync_knockout_advancement(db, config)
        if score_updates:
            compute_and_store_points(db, config)
    if not dry_run:
        _save_state(state_path, state)
    return ResultPollResult(
        attempted_api=True,
        checked_db=True,
        candidates=len(candidates),
        already_completed=already_completed,
        updated_matches=score_updates,
        unmatched_matches=len(unmatched),
        api_requests=api_requests,
        recomputed_points=bool(score_updates and not dry_run),
    )


def local_due_match_count(
    config: EventConfig,
    *,
    state_path: Path = DEFAULT_STATE_PATH,
    now: datetime | None = None,
    force: bool = False,
    backfill: bool = False,
) -> int:
    current_time = _to_utc(now or datetime.now(timezone.utc))
    state = _load_state(state_path)
    return len(_local_candidates(config, state, current_time, force, backfill))


def _load_provider_events(
    config: EventConfig,
    matches: list[MatchConfig],
    *,
    provider_name: str,
    thesportsdb_key: str,
    api_football_key: str | None,
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
) -> tuple[list[dict[str, Any]], int]:
    if provider_name == "api-football":
        if not api_football_key:
            raise RuntimeError("API_FOOTBALL_KEY is not configured.")
        client = ApiFootballClient(api_football_key)
        return _load_api_football_events(client, config, matches, max_api_requests)
    client = TheSportsDBClient(thesportsdb_key)
    if config.thesportsdb_league_id:
        return _load_provider_events_by_match(client, config, matches, max_api_requests)
    days = sorted({match.kickoff_utc.date() for match in matches})
    events: list[dict[str, Any]] = []
    requests = 0
    for day in days:
        if requests >= max_api_requests:
            break
        events.extend(client.events_for_day(day))
        requests += 1
    return events, requests


def _select_provider(
    config: EventConfig,
    matches: list[MatchConfig],
    requested: str,
    api_football_key: str | None,
) -> str:
    if requested in {"api-football", "thesportsdb"}:
        return requested
    if requested != "auto":
        raise ValueError(f"Unknown result provider: {requested}")
    has_api_football_metadata = bool(
        config.api_football_league_id
        or any(match.api_football_fixture_id for match in matches)
    )
    if api_football_key and has_api_football_metadata:
        return "api-football"
    return "thesportsdb"


def _load_api_football_events(
    client: ApiFootballClient,
    config: EventConfig,
    matches: list[MatchConfig],
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    requests = 0
    fixture_ids = [str(match.api_football_fixture_id) for match in matches if match.api_football_fixture_id]
    if fixture_ids:
        for chunk in _chunks(fixture_ids, 20):
            if requests >= max_api_requests:
                break
            events.extend(client.fixtures_by_ids(chunk))
            requests += 1
        return events, requests

    if config.api_football_league_id:
        days = sorted({match.kickoff_utc.date() for match in matches})
        for day in days:
            if requests >= max_api_requests:
                break
            for event in client.fixtures_by_date(day):
                league = event.get("league") if isinstance(event.get("league"), dict) else {}
                if str(league.get("id") or "") == config.api_football_league_id:
                    events.append(event)
            requests += 1
        return events, requests

    return events, requests


def _load_provider_events_by_match(
    client: TheSportsDBClient,
    config: EventConfig,
    matches: list[MatchConfig],
    max_api_requests: int = DEFAULT_MAX_API_REQUESTS,
) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    seen_event_ids: set[str] = set()
    requests = 0
    for match in matches:
        if requests >= max_api_requests:
            break
        if match.thesportsdb_event_id:
            requests += 1
            for event in client.lookup_event(match.thesportsdb_event_id):
                event_id = str(event.get("idEvent") or "")
                if event_id and event_id not in seen_event_ids:
                    seen_event_ids.add(event_id)
                    events.append(event)
            continue
        for event_name in _search_event_names(match):
            if requests >= max_api_requests:
                break
            requests += 1
            search_results = client.search_events(event_name, config.thesportsdb_season)
            usable = []
            for event in search_results:
                result = _provider_result(event, require_score=False)
                if result is None or result.kickoff_utc is None:
                    continue
                if abs(result.kickoff_utc - match.kickoff_utc) <= timedelta(hours=8):
                    usable.append(event)
            if usable:
                for event in usable:
                    event_id = str(event.get("idEvent") or "")
                    if event_id and event_id not in seen_event_ids:
                        seen_event_ids.add(event_id)
                        events.append(event)
                break
    return events, requests


def _search_event_names(match: MatchConfig) -> list[str]:
    names: list[str] = []
    team_a_names = SEARCH_NAME_ALIASES.get(match.team_a_name, [match.team_a_name])
    team_b_names = SEARCH_NAME_ALIASES.get(match.team_b_name, [match.team_b_name])
    for left, right in ((team_a_names, team_b_names), (team_b_names, team_a_names)):
        for home in left:
            for away in right:
                names.append(f"{home}_vs_{away}")
    return list(dict.fromkeys(names))


def _local_candidates(
    config: EventConfig,
    state: dict[str, Any],
    now: datetime,
    force: bool,
    backfill: bool,
) -> list[MatchConfig]:
    due_after = now - DEFAULT_LOOKBACK
    candidates: list[MatchConfig] = []
    for match in config.matches:
        if match.kickoff_utc > now:
            continue
        if not backfill and match.kickoff_utc < due_after:
            continue
        next_check_at = _parse_datetime(_state_entry(state, config.event_id, match.match_id).get("next_check_at"))
        if not (force or backfill) and next_check_at and now < next_check_at:
            continue
        candidates.append(match)
    return candidates


def _settle_until(match: MatchConfig) -> datetime:
    return match.kickoff_utc + DEFAULT_RESULT_SETTLE_WINDOW


def _load_match_result_status(db: Database, event_id: str, match_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    rows = db.query(
        f"""
        SELECT match_id, result_a, result_b, status
        FROM matches
        WHERE event_id = ? AND match_id IN ({placeholders})
        """,
        (event_id, *match_ids),
    )
    return {str(row["match_id"]): row for row in rows}


def _db_row_completed(row: dict[str, Any]) -> bool:
    return row.get("result_a") is not None and row.get("result_b") is not None and str(row.get("status") or "") == "completed"


def _db_row_has_score(row: dict[str, Any]) -> bool:
    return row.get("result_a") is not None and row.get("result_b") is not None


def _state_provider_owned(entry: dict[str, Any]) -> bool:
    return str(entry.get("source") or "") in {"api-football", "thesportsdb"} or bool(entry.get("provider_event_id"))


def _match_provider_result(match: MatchConfig, events: list[dict[str, Any]]) -> ProviderResult | None:
    expected_a = _team_key(match.team_a_name)
    expected_b = _team_key(match.team_b_name)
    for event in events:
        result = _api_football_result(event, require_final=False) if "fixture" in event else _provider_result(event)
        if result is None:
            continue
        if match.api_football_fixture_id and result.provider == "api-football" and result.event_id != match.api_football_fixture_id:
            continue
        if match.thesportsdb_event_id and result.provider == "thesportsdb" and result.event_id != match.thesportsdb_event_id:
            continue
        if result.kickoff_utc and abs(result.kickoff_utc - match.kickoff_utc) > timedelta(hours=8):
            continue
        home = _team_key(result.home)
        away = _team_key(result.away)
        if (home == expected_a and away == expected_b) or (home == expected_b and away == expected_a):
            return result
    return None


def _provider_result(event: dict[str, Any], require_score: bool = True) -> ProviderResult | None:
    home_score = _parse_int(event.get("intHomeScore"))
    away_score = _parse_int(event.get("intAwayScore"))
    if require_score and (home_score is None or away_score is None):
        return None
    home = str(event.get("strHomeTeam") or "")
    away = str(event.get("strAwayTeam") or "")
    if not home or not away:
        return None
    return ProviderResult(
        event_id=str(event.get("idEvent") or ""),
        home=home,
        away=away,
        kickoff_utc=_event_kickoff(event),
        home_score=home_score if home_score is not None else 0,
        away_score=away_score if away_score is not None else 0,
        status=str(event.get("strStatus") or "") or None,
        provider="thesportsdb",
        is_final=True,
    )


def _api_football_result(event: dict[str, Any], require_final: bool = True) -> ProviderResult | None:
    fixture = event.get("fixture") if isinstance(event.get("fixture"), dict) else {}
    teams = event.get("teams") if isinstance(event.get("teams"), dict) else {}
    status = fixture.get("status") if isinstance(fixture.get("status"), dict) else {}
    status_short = str(status.get("short") or "")
    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    home_score, away_score = _api_football_display_score(event, status_short)
    if require_final and status_short not in API_FOOTBALL_FINAL_STATUSES:
        return None
    if not require_final and status_short in API_FOOTBALL_UNSCORABLE_STATUSES:
        return None
    if require_final and (home_score is None or away_score is None):
        return None
    if home_score is None or away_score is None:
        return None
    home_name = str(home.get("name") or "")
    away_name = str(away.get("name") or "")
    if not home_name or not away_name:
        return None
    return ProviderResult(
        event_id=str(fixture.get("id") or ""),
        home=home_name,
        away=away_name,
        kickoff_utc=_parse_datetime(fixture.get("date")),
        home_score=home_score if home_score is not None else 0,
        away_score=away_score if away_score is not None else 0,
        status=status_short or None,
        provider="api-football",
        is_final=status_short in API_FOOTBALL_FINAL_STATUSES,
    )


def _api_football_display_score(event: dict[str, Any], status_short: str) -> tuple[int | None, int | None]:
    goals = event.get("goals") if isinstance(event.get("goals"), dict) else {}
    score = event.get("score") if isinstance(event.get("score"), dict) else {}
    home_score = _parse_int(goals.get("home"))
    away_score = _parse_int(goals.get("away"))
    if status_short == "PEN":
        extratime = score.get("extratime") if isinstance(score.get("extratime"), dict) else {}
        fulltime = score.get("fulltime") if isinstance(score.get("fulltime"), dict) else {}
        base_home = home_score if home_score is not None else _parse_int(extratime.get("home"))
        base_away = away_score if away_score is not None else _parse_int(extratime.get("away"))
        if base_home is None:
            base_home = _parse_int(fulltime.get("home"))
        if base_away is None:
            base_away = _parse_int(fulltime.get("away"))
        if base_home is None or base_away is None:
            return None, None
        penalty = score.get("penalty") if isinstance(score.get("penalty"), dict) else {}
        penalty_home = _parse_int(penalty.get("home"))
        penalty_away = _parse_int(penalty.get("away"))
        winner = _api_football_winner(event)
        if base_home == base_away:
            if penalty_home is not None and penalty_away is not None and penalty_home != penalty_away:
                return (base_home + 1, base_away) if penalty_home > penalty_away else (base_home, base_away + 1)
            if winner == "home":
                return base_home + 1, base_away
            if winner == "away":
                return base_home, base_away + 1
        return base_home, base_away
    return home_score, away_score


def _api_football_winner(event: dict[str, Any]) -> str | None:
    teams = event.get("teams") if isinstance(event.get("teams"), dict) else {}
    home = teams.get("home") if isinstance(teams.get("home"), dict) else {}
    away = teams.get("away") if isinstance(teams.get("away"), dict) else {}
    if home.get("winner") is True:
        return "home"
    if away.get("winner") is True:
        return "away"
    return None


def _event_kickoff(event: dict[str, Any]) -> datetime | None:
    timestamp = event.get("strTimestamp")
    if timestamp:
        return _parse_datetime(str(timestamp))
    date_value = event.get("dateEvent")
    time_value = event.get("strTime") or "00:00:00"
    if not date_value:
        return None
    return _parse_datetime(f"{date_value}T{time_value}+00:00")


def _is_swapped(match: MatchConfig, result: ProviderResult) -> bool:
    return _team_key(result.home) == _team_key(match.team_b_name) and _team_key(result.away) == _team_key(match.team_a_name)


def _schedule_retry(state: dict[str, Any], event_id: str, matches: list[MatchConfig], now: datetime) -> None:
    for match in matches:
        entry = _state_entry(state, event_id, match.match_id)
        attempts = int(entry.get("attempts") or 0) + 1
        delay = min(DEFAULT_LATE_RECHECK * attempts, DEFAULT_MAX_LATE_RECHECK)
        entry["attempts"] = attempts
        entry["last_checked_at"] = now.isoformat()
        entry["next_check_at"] = (now + delay).isoformat()


def _mark_completed(
    state: dict[str, Any],
    event_id: str,
    match_id: str,
    now: datetime,
    source: str,
    provider_event_id: str | None = None,
) -> None:
    entry = _state_entry(state, event_id, match_id)
    entry["completed_at"] = now.isoformat()
    entry["source"] = source
    entry.pop("next_check_at", None)
    if provider_event_id:
        entry["provider_event_id"] = provider_event_id


def _mark_provider_seen(
    state: dict[str, Any],
    event_id: str,
    match_id: str,
    now: datetime,
    result: ProviderResult,
    result_a: int,
    result_b: int,
) -> None:
    entry = _state_entry(state, event_id, match_id)
    entry["source"] = result.provider
    entry["provider_event_id"] = result.event_id
    entry["last_seen_at"] = now.isoformat()
    entry["last_status"] = result.status
    entry["last_result_a"] = result_a
    entry["last_result_b"] = result_b
    entry.pop("next_check_at", None)


def _state_entry(state: dict[str, Any], event_id: str, match_id: str) -> dict[str, Any]:
    events = state.setdefault("events", {})
    event = events.setdefault(event_id, {})
    matches = event.setdefault("matches", {})
    return matches.setdefault(match_id, {})


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


def _api_football_remaining_budget(state: dict[str, Any], now: datetime, daily_budget: int) -> int:
    if daily_budget <= 0:
        return 0
    today = now.date().isoformat()
    entry = state.setdefault("providers", {}).setdefault("api-football", {}).setdefault("daily", {}).setdefault(today, {})
    return max(0, daily_budget - int(entry.get("requests") or 0))


def _record_api_football_requests(state: dict[str, Any], now: datetime, requests: int) -> None:
    today = now.date().isoformat()
    entry = state.setdefault("providers", {}).setdefault("api-football", {}).setdefault("daily", {}).setdefault(today, {})
    entry["requests"] = int(entry.get("requests") or 0) + int(requests)
    entry["updated_at"] = now.isoformat()


def _parse_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return _to_utc(parsed)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _team_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    normalized = TEAM_ALIASES.get(normalized, normalized)
    return re.sub(r"\s+", " ", normalized)


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]
