from __future__ import annotations

import hashlib
import json
import math
import os
import re
import ssl
import tempfile
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from base64 import b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from .config import EventConfig
from .db import Database
from .repository import (
    acquire_odds_refresh_lock,
    insert_odds_snapshot,
    latest_odds_captured_at,
    latest_odds_captured_at_for_match,
    lock_latest_pregame_odds,
    release_odds_refresh_lock,
)
from .secrets import BetfairSettings


BETFAIR_SOCCER_EVENT_TYPE_ID = "1"
BETFAIR_WORLD_CUP_COMPETITION_ID = "12469077"
BETFAIR_URL = "https://api.betfair.com/exchange/betting/json-rpc/v1"
BETFAIR_KEEP_ALIVE_URL = "https://identitysso.betfair.com/api/keepAlive"
BETFAIR_CERT_LOGIN_URL = "https://identitysso-cert.betfair.com/api/certlogin"
CORE_MARKET_TYPES = [
    "MATCH_ODDS",
    "CORRECT_SCORE",
    "OVER_UNDER_25",
    "ALT_TOTAL_GOALS",
    "BOTH_TEAMS_TO_SCORE",
    "OVER_UNDER_05",
    "ASIAN_HANDICAP",
]
DISPLAY_SCORE_MAX = 6
MODEL_SCORE_MAX = 8
FIT_SCORE_MAX = 12
REFRESH_LOCK_TTL = timedelta(minutes=20)
MIN_REFRESH_INTERVAL = timedelta(hours=1)
CLOSE_REFRESH_WINDOW = timedelta(hours=5)
LAST_HOUR_TARGET = timedelta(hours=1)
FAR_REFRESH_INTERVAL = timedelta(hours=12)


TEAM_ALIASES = {
    "bosnia": "bosnia and herzegovina",
    "bosnia-herzegovina": "bosnia and herzegovina",
    "cabo verde": "cape verde",
    "congo dr": "dr congo",
    "cote divoire": "ivory coast",
    "cote d ivoire": "ivory coast",
    "cote d'ivoire": "ivory coast",
    "côte divoire": "ivory coast",
    "côte d'ivoire": "ivory coast",
    "curacao": "curacao",
    "curaçao": "curacao",
    "czech republic": "czechia",
    "d r congo": "dr congo",
    "south korea": "south korea",
    "korea republic": "south korea",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "usa": "united states",
    "u s a": "united states",
    "us": "united states",
}


EURO_2024_STRENGTHS = {
    "FRA": 2.05,
    "ENG": 1.95,
    "ESP": 1.9,
    "GER": 1.78,
    "POR": 1.76,
    "NED": 1.66,
    "ITA": 1.62,
    "BEL": 1.58,
    "CRO": 1.42,
    "DEN": 1.35,
    "SUI": 1.34,
    "AUT": 1.26,
    "TUR": 1.14,
    "UKR": 1.08,
    "SRB": 1.04,
    "HUN": 1.0,
    "POL": 0.98,
    "CZE": 0.97,
    "ROU": 0.93,
    "SVK": 0.9,
    "SVN": 0.86,
    "SCO": 0.84,
    "ALB": 0.78,
    "GEO": 0.74,
}


@dataclass(frozen=True)
class EventMapping:
    match_id: str
    provider_event_id: str
    provider_name: str
    provider_home: str
    provider_away: str
    swapped: bool


@dataclass(frozen=True)
class OddsRefreshDecision:
    due: bool
    reason: str
    target_match_ids: list[str]
    next_match_id: str | None = None


@dataclass(frozen=True)
class OddsRefreshResult:
    attempted: bool
    updated_matches: int = 0
    locked_matches: int = 0
    skipped_reason: str | None = None
    error: str | None = None
    already_running: bool = False
    unmatched_matches: int = 0


class BetfairClient:
    def __init__(self, settings: BetfairSettings) -> None:
        if not settings.session_token:
            raise ValueError("Betfair session token is required for exchange API calls.")
        self.settings = settings
        self.context = ssl.create_default_context()

    def call(self, method: str, params: dict[str, Any]) -> Any:
        payload = [{"jsonrpc": "2.0", "method": f"SportsAPING/v1.0/{method}", "params": params, "id": 1}]
        request = urllib.request.Request(
            BETFAIR_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "tippnation-odds/0.1",
                "X-Application": self.settings.app_key,
                "X-Authentication": self.settings.session_token,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=45, context=self.context) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Betfair exchange {method} failed: HTTP {exc.code} {_sanitize_betfair_body(body)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Betfair exchange {method} failed: {exc.reason}") from exc
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Betfair exchange {method} returned non-JSON response: {_sanitize_betfair_body(body)}") from exc
        first = data[0]
        if "error" in first:
            raise RuntimeError(f"Betfair exchange {method} returned API error: {_sanitize_betfair_body(json.dumps(first['error'], sort_keys=True))}")
        return first.get("result")

    def list_competition_events(
        self,
        start: datetime,
        end: datetime,
        competition_id: str,
        event_type_id: str = BETFAIR_SOCCER_EVENT_TYPE_ID,
    ) -> list[dict[str, Any]]:
        return self.call(
            "listEvents",
            {
                "filter": {
                    "eventTypeIds": [event_type_id],
                    "competitionIds": [competition_id],
                    "marketStartTime": {"from": _utc_z(start), "to": _utc_z(end)},
                }
            },
        )

    def list_market_catalogue(
        self,
        provider_event_ids: list[str],
        market_type: str,
        competition_id: str,
        event_type_id: str = BETFAIR_SOCCER_EVENT_TYPE_ID,
    ) -> list[dict[str, Any]]:
        if not provider_event_ids:
            return []
        return self.call(
            "listMarketCatalogue",
            {
                "filter": {
                    "eventTypeIds": [event_type_id],
                    "competitionIds": [competition_id],
                    "eventIds": provider_event_ids,
                    "marketTypeCodes": [market_type],
                },
                "maxResults": "1000",
                "sort": "FIRST_TO_START",
                "marketProjection": ["EVENT", "MARKET_START_TIME", "MARKET_DESCRIPTION", "RUNNER_DESCRIPTION"],
            },
        )

    def list_market_book(self, market_ids: list[str]) -> list[dict[str, Any]]:
        books: list[dict[str, Any]] = []
        for chunk in _chunks(market_ids, 5):
            books.extend(
                self.call(
                    "listMarketBook",
                    {
                        "marketIds": chunk,
                        "priceProjection": {
                            "priceData": ["EX_BEST_OFFERS"],
                            "exBestOffersOverrides": {"bestPricesDepth": 1},
                            "virtualise": True,
                        },
                    },
                )
            )
        return books


def keep_betfair_session_alive(settings: BetfairSettings) -> dict[str, Any]:
    if not settings.session_token:
        return {"status": "MISSING_SESSION_TOKEN"}
    request = urllib.request.Request(
        BETFAIR_KEEP_ALIVE_URL,
        data=b"",
        headers={
            "Accept": "application/json",
            "User-Agent": "tippnation-odds/0.1",
            "X-Application": settings.app_key,
            "X-Authentication": settings.session_token,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl.create_default_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "HTTP_ERROR", "http_status": exc.code, "body": _sanitize_betfair_body(body)}
    except urllib.error.URLError as exc:
        return {"status": "URL_ERROR", "reason": str(exc.reason)}
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return {"status": "NON_JSON_RESPONSE", "body": _sanitize_betfair_body(body)}
    return data if isinstance(data, dict) else {"status": "UNKNOWN_RESPONSE", "body": data}


def login_betfair_with_certificate(settings: BetfairSettings) -> BetfairSettings:
    if not settings.has_certificate_login:
        return settings
    if not settings.username or not settings.password:
        raise RuntimeError("Betfair certificate login requires BETFAIR_USERNAME and BETFAIR_PASSWORD.")

    with _betfair_cert_files(settings) as cert_files:
        context = ssl.create_default_context()
        try:
            context.load_cert_chain(certfile=str(cert_files.cert_path), keyfile=str(cert_files.key_path))
        except ssl.SSLError as exc:
            raise RuntimeError(f"Betfair certificate/key could not be loaded: {exc}") from exc
        payload = urllib.parse.urlencode({"username": settings.username, "password": settings.password}).encode("utf-8")
        request = urllib.request.Request(
            BETFAIR_CERT_LOGIN_URL,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "tippnation-odds/0.1",
                "X-Application": settings.app_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30, context=context) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Betfair certificate login failed: HTTP {exc.code} {_sanitize_betfair_body(body)}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Betfair certificate login failed: {exc.reason}") from exc

    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Betfair certificate login returned non-JSON response: {_sanitize_betfair_body(body)}") from exc

    session_token = data.get("sessionToken") if isinstance(data, dict) else None
    if not session_token:
        login_status = data.get("loginStatus") if isinstance(data, dict) else "UNKNOWN_RESPONSE"
        raise RuntimeError(f"Betfair certificate login failed: {login_status}")
    return replace(settings, session_token=str(session_token))


def _sanitize_betfair_body(body: str, limit: int = 500) -> str:
    redacted = re.sub(r'("sessionToken"\s*:\s*")[^"]+(")', r"\1<redacted>\2", body)
    redacted = re.sub(r'("X-Authentication"\s*:\s*")[^"]+(")', r"\1<redacted>\2", redacted)
    redacted = redacted.replace("\n", " ").replace("\r", " ")
    return redacted[:limit]


@dataclass(frozen=True)
class _BetfairCertFiles:
    cert_path: Path
    key_path: Path


class _betfair_cert_files:
    def __init__(self, settings: BetfairSettings) -> None:
        self.settings = settings
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    def __enter__(self) -> _BetfairCertFiles:
        if self.settings.cert_path and self.settings.key_path:
            cert_path = Path(self.settings.cert_path)
            key_path = Path(self.settings.key_path)
            cert_bytes = cert_path.read_bytes()
            if b"-----BEGIN CERTIFICATE-----" in cert_bytes:
                return _BetfairCertFiles(cert_path, key_path)
            self._temporary_directory = tempfile.TemporaryDirectory(prefix="tippnation-betfair-")
            normalized_cert_path = Path(self._temporary_directory.name) / "betfair.crt"
            normalized_cert_path.write_bytes(_certificate_pem_bytes(cert_bytes))
            return _BetfairCertFiles(normalized_cert_path, key_path)
        if not self.settings.cert_base64 or not self.settings.key_base64:
            raise RuntimeError("Betfair certificate login requires cert/key paths or base64 payloads.")

        self._temporary_directory = tempfile.TemporaryDirectory(prefix="tippnation-betfair-")
        directory = Path(self._temporary_directory.name)
        cert_path = directory / "betfair.crt"
        key_path = directory / "betfair.key"
        cert_path.write_bytes(_certificate_pem_bytes(_decode_base64_secret(self.settings.cert_base64, "BETFAIR_CERT_BASE64")))
        key_path.write_bytes(_decode_base64_secret(self.settings.key_base64, "BETFAIR_KEY_BASE64"))
        os.chmod(key_path, 0o600)
        return _BetfairCertFiles(cert_path, key_path)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._temporary_directory is not None:
            self._temporary_directory.cleanup()


def _decode_base64_secret(value: str, name: str) -> bytes:
    compact = "".join(value.split()).replace("-", "+").replace("_", "/")
    padding = (-len(compact)) % 4
    try:
        return b64decode(compact + ("=" * padding), validate=True)
    except Base64Error as exc:
        raise RuntimeError(f"{name} is not valid base64.") from exc


def _certificate_pem_bytes(value: bytes) -> bytes:
    if b"-----BEGIN CERTIFICATE-----" in value:
        return value
    try:
        return ssl.DER_cert_to_PEM_cert(value).encode("ascii")
    except ValueError as exc:
        raise RuntimeError("BETFAIR_CERT_BASE64 is not a valid PEM or DER certificate.") from exc


def odds_refresh_decision(db: Database, event_id: str, matches: pd.DataFrame, now: datetime) -> OddsRefreshDecision:
    target = _target_upcoming_matches(matches, now)
    if target.empty:
        return OddsRefreshDecision(False, "No upcoming matches.", [])

    target_match_ids = [str(value) for value in target["match_id"].tolist()]
    latest_any = latest_odds_captured_at(db, event_id, target_match_ids)
    next_match = target.sort_values("kickoff_utc").iloc[0]
    next_match_id = str(next_match["match_id"])
    next_kickoff = _to_datetime(next_match["kickoff_utc"])
    latest_next = latest_odds_captured_at_for_match(db, event_id, next_match_id)

    if latest_any is not None and now - latest_any < MIN_REFRESH_INTERVAL:
        return OddsRefreshDecision(False, "Market odds were refreshed less than one hour ago.", target_match_ids, next_match_id)

    missing = [match_id for match_id in target_match_ids if latest_odds_captured_at_for_match(db, event_id, match_id) is None]
    if missing:
        return OddsRefreshDecision(True, f"Missing odds for {len(missing)} upcoming matches.", target_match_ids, next_match_id)

    if latest_next is None:
        return OddsRefreshDecision(True, "Missing odds for the next match.", target_match_ids, next_match_id)

    time_to_next = next_kickoff - now
    if timedelta(0) < time_to_next <= LAST_HOUR_TARGET and latest_next < next_kickoff - LAST_HOUR_TARGET:
        return OddsRefreshDecision(True, "Need a pre-game odds snapshot inside the final hour.", target_match_ids, next_match_id)

    if timedelta(0) < time_to_next <= CLOSE_REFRESH_WINDOW:
        return OddsRefreshDecision(True, "Next kickoff is inside the five-hour refresh window.", target_match_ids, next_match_id)

    if latest_any is None or now - latest_any >= FAR_REFRESH_INTERVAL:
        return OddsRefreshDecision(True, "Periodic market odds refresh is due.", target_match_ids, next_match_id)

    return OddsRefreshDecision(False, "Market odds are fresh enough.", target_match_ids, next_match_id)


def refresh_market_odds_if_due(
    db: Database,
    config: EventConfig,
    settings: BetfairSettings | None,
    matches: pd.DataFrame,
    now: datetime,
) -> OddsRefreshResult:
    locked = lock_latest_pregame_odds(db, config.event_id, now)
    if settings is None:
        return OddsRefreshResult(False, locked_matches=locked, skipped_reason="Betfair credentials are not configured.")
    if not config.betfair_competition_id:
        return OddsRefreshResult(False, locked_matches=locked, skipped_reason="Live Betfair refresh is not enabled for this event.")

    decision = odds_refresh_decision(db, config.event_id, matches, now)
    if not decision.due:
        return OddsRefreshResult(False, locked_matches=locked, skipped_reason=decision.reason)

    owner = str(uuid4())
    lock_key = f"{config.event_id}:betfair-refresh"
    acquired = acquire_odds_refresh_lock(db, lock_key, owner, now, now + REFRESH_LOCK_TTL)
    if not acquired:
        return OddsRefreshResult(False, locked_matches=locked, already_running=True, skipped_reason="Another odds refresh is already running.")

    try:
        updated, unmatched = refresh_betfair_odds(db, config, settings, matches, decision.target_match_ids, now)
        locked += lock_latest_pregame_odds(db, config.event_id, now)
        return OddsRefreshResult(True, updated_matches=updated, locked_matches=locked, unmatched_matches=unmatched)
    except Exception as exc:
        return OddsRefreshResult(True, locked_matches=locked, error=str(exc))
    finally:
        release_odds_refresh_lock(db, lock_key, owner)


def refresh_betfair_odds(
    db: Database,
    config: EventConfig,
    settings: BetfairSettings,
    matches: pd.DataFrame,
    match_ids: list[str],
    captured_at: datetime,
) -> tuple[int, int]:
    target = matches[matches["match_id"].isin(match_ids)].copy()
    if target.empty:
        return 0, 0

    client = BetfairClient(settings)
    start = _to_datetime(target["kickoff_utc"].min()) - timedelta(hours=6)
    end = _to_datetime(target["kickoff_utc"].max()) + timedelta(hours=6)
    if not config.betfair_competition_id:
        return 0, len(target)
    provider_events = client.list_competition_events(
        start,
        end,
        config.betfair_competition_id,
        config.betfair_event_type_id,
    )
    mappings = _map_provider_events(config, target, provider_events)
    if not mappings:
        return 0, len(target)

    provider_event_ids = [mapping.provider_event_id for mapping in mappings]
    catalogue: list[dict[str, Any]] = []
    for market_type in CORE_MARKET_TYPES:
        catalogue.extend(
            client.list_market_catalogue(
                provider_event_ids,
                market_type,
                config.betfair_competition_id,
                config.betfair_event_type_id,
            )
        )
    books = client.list_market_book([market["marketId"] for market in catalogue])
    book_by_id = {book["marketId"]: book for book in books}

    markets_by_provider_event: dict[str, list[dict[str, Any]]] = {}
    for market in catalogue:
        provider_event_id = str(market.get("event", {}).get("id") or "")
        book = book_by_id.get(market["marketId"], {})
        markets_by_provider_event.setdefault(provider_event_id, []).append(_market_payload(market, book))

    match_by_id = {str(row.match_id): row for row in target.itertuples(index=False)}
    updated = 0
    for mapping in mappings:
        row = match_by_id[mapping.match_id]
        market_payloads = markets_by_provider_event.get(mapping.provider_event_id, [])
        if not market_payloads:
            continue
        probabilities, diagnostics = fit_score_probabilities(
            market_payloads,
            home_name=mapping.provider_home,
            away_name=mapping.provider_away,
            score_max=MODEL_SCORE_MAX,
        )
        if mapping.swapped and not probabilities.empty:
            probabilities = probabilities.rename(columns={"score_a": "score_b", "score_b": "score_a"})[["score_a", "score_b", "probability"]]
        diagnostics["provider_event_name"] = mapping.provider_name
        diagnostics["provider_event_id"] = mapping.provider_event_id
        diagnostics["provider_swapped"] = mapping.swapped
        snapshot_id = _snapshot_id(config.event_id, mapping.match_id, captured_at, "betfair")
        insert_odds_snapshot(
            db,
            event_id=config.event_id,
            match_id=mapping.match_id,
            snapshot_id=snapshot_id,
            provider="betfair",
            provider_event_id=mapping.provider_event_id,
            captured_at=captured_at,
            kickoff_utc=_to_datetime(row.kickoff_utc),
            market_count=len(market_payloads),
            score_max=MODEL_SCORE_MAX,
            diagnostics=diagnostics,
            markets=market_payloads,
            probabilities=probabilities,
        )
        updated += 1

    return updated, len(target) - updated


def fit_score_probabilities(
    markets: list[dict[str, Any]],
    *,
    home_name: str,
    away_name: str,
    score_max: int = MODEL_SCORE_MAX,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    targets = _build_fit_targets(markets, home_name, away_name)
    if not targets:
        lambda_home, lambda_away = 1.25, 1.05
    else:
        lambda_home, lambda_away = _fit_lambdas(targets)
    table = score_probability_grid(lambda_home, lambda_away, score_max=score_max)
    diagnostics = {
        "lambda_home": round(lambda_home, 4),
        "lambda_away": round(lambda_away, 4),
        "fit_targets": len(targets),
        "market_types": sorted({str(market["market_type"]) for market in markets}),
    }
    return table, diagnostics


def score_probability_grid(lambda_home: float, lambda_away: float, score_max: int = MODEL_SCORE_MAX) -> pd.DataFrame:
    home = _poisson_probs(lambda_home, score_max)
    away = _poisson_probs(lambda_away, score_max)
    rows = []
    total = 0.0
    for score_a in range(score_max + 1):
        for score_b in range(score_max + 1):
            probability = float(home[score_a] * away[score_b])
            rows.append({"score_a": score_a, "score_b": score_b, "probability": probability})
            total += probability
    if total <= 0:
        return pd.DataFrame(rows)
    df = pd.DataFrame(rows)
    df["probability"] = df["probability"] / total
    return df


def seed_synthetic_replay_odds(db: Database, config: EventConfig, replay_now: datetime) -> None:
    for match in config.matches:
        captured_at = replay_now if match.kickoff_utc > replay_now else match.kickoff_utc - timedelta(minutes=55)
        lambda_a, lambda_b = _synthetic_lambdas(config, match.match_id, match.team_a_id, match.team_b_id, match.round_name)
        probabilities = score_probability_grid(lambda_a, lambda_b, score_max=MODEL_SCORE_MAX)
        diagnostics = {
            "lambda_home": round(lambda_a, 4),
            "lambda_away": round(lambda_b, 4),
            "fit_targets": 0,
            "synthetic_seed": config.kanonenwilli_seed,
            "synthetic_replay": True,
        }
        markets = _synthetic_markets(match.team_a_name, match.team_b_name, probabilities)
        snapshot_id = _snapshot_id(config.event_id, match.match_id, captured_at, "synthetic")
        insert_odds_snapshot(
            db,
            event_id=config.event_id,
            match_id=match.match_id,
            snapshot_id=snapshot_id,
            provider="synthetic",
            provider_event_id=None,
            captured_at=captured_at,
            kickoff_utc=match.kickoff_utc,
            market_count=len(markets),
            score_max=MODEL_SCORE_MAX,
            diagnostics=diagnostics,
            markets=markets,
            probabilities=probabilities,
        )
    lock_latest_pregame_odds(db, config.event_id, replay_now)


def _target_upcoming_matches(matches: pd.DataFrame, now: datetime) -> pd.DataFrame:
    if matches.empty:
        return matches
    upcoming = matches[matches["kickoff_utc"] > pd.Timestamp(now)].sort_values("kickoff_utc")
    if upcoming.empty:
        return upcoming
    next_round = str(upcoming.iloc[0]["round_name"])
    return upcoming[upcoming["round_name"] == next_round].copy()


def _build_fit_targets(markets: list[dict[str, Any]], home_name: str, away_name: str) -> list[tuple[str, tuple[float, ...], float, float]]:
    targets: list[tuple[str, tuple[float, ...], float, float]] = []
    home_key = _team_key(home_name)
    away_key = _team_key(away_name)
    for market in markets:
        market_type = str(market["market_type"])
        runners = market.get("runners", [])
        total_matched = float(market.get("total_matched") or 0.0)
        liquidity_weight = 0.5 + min(math.log10(total_matched + 1.0), 4.0) / 4.0
        if market_type == "MATCH_ODDS":
            probs = _normalised_runner_probabilities(runners)
            for runner_key, probability in probs.items():
                name = _team_key(str(runner_key[0]))
                if name == home_key:
                    targets.append(("home_win", (), probability, 5.0 * liquidity_weight))
                elif name == away_key:
                    targets.append(("away_win", (), probability, 5.0 * liquidity_weight))
                elif "draw" in name:
                    targets.append(("draw", (), probability, 5.0 * liquidity_weight))
        elif market_type in {"OVER_UNDER_25", "OVER_UNDER_05"}:
            line = 2.5 if market_type == "OVER_UNDER_25" else 0.5
            _add_over_under_targets(targets, runners, line, 2.5 * liquidity_weight)
        elif market_type == "ALT_TOTAL_GOALS":
            grouped: dict[float, list[dict[str, Any]]] = {}
            for runner in runners:
                handicap = runner.get("handicap")
                if handicap is None:
                    continue
                line = float(handicap)
                if not _is_half_line(line):
                    continue
                grouped.setdefault(line, []).append(runner)
            for line, line_runners in grouped.items():
                _add_over_under_targets(targets, line_runners, line, 1.5 * liquidity_weight)
        elif market_type == "BOTH_TEAMS_TO_SCORE":
            probs = _normalised_runner_probabilities(runners)
            for runner_key, probability in probs.items():
                name = str(runner_key[0]).strip().lower()
                if name == "yes":
                    targets.append(("btts", (), probability, 2.0 * liquidity_weight))
        elif market_type == "CORRECT_SCORE":
            probs = _normalised_runner_probabilities(runners)
            for runner_key, probability in probs.items():
                parsed = _parse_score_name(str(runner_key[0]))
                if parsed is None:
                    continue
                score_a, score_b = parsed
                if score_a <= 5 and score_b <= 5:
                    targets.append(("score", (float(score_a), float(score_b)), probability, 0.75 * liquidity_weight))
        elif market_type == "ASIAN_HANDICAP":
            by_abs_line: dict[float, list[dict[str, Any]]] = {}
            for runner in runners:
                handicap = runner.get("handicap")
                if handicap is None:
                    continue
                line = float(handicap)
                if not _is_half_line(abs(line)):
                    continue
                by_abs_line.setdefault(abs(line), []).append(runner)
            for line_runners in by_abs_line.values():
                if len(line_runners) < 2:
                    continue
                probs = _normalised_runner_probabilities(line_runners)
                for runner_key, probability in probs.items():
                    name, handicap = runner_key
                    if _team_key(str(name)) == home_key and handicap is not None:
                        targets.append(("asian_home", (float(handicap),), probability, 1.25 * liquidity_weight))
    return targets


def _fit_lambdas(targets: list[tuple[str, tuple[float, ...], float, float]]) -> tuple[float, float]:
    best = (1.25, 1.05)
    best_loss = float("inf")
    for home_lambda in np.arange(0.2, 4.81, 0.1):
        for away_lambda in np.arange(0.2, 4.81, 0.1):
            loss = _fit_loss(float(home_lambda), float(away_lambda), targets)
            if loss < best_loss:
                best = (float(home_lambda), float(away_lambda))
                best_loss = loss
    home_center, away_center = best
    for home_lambda in np.arange(max(0.05, home_center - 0.18), home_center + 0.181, 0.02):
        for away_lambda in np.arange(max(0.05, away_center - 0.18), away_center + 0.181, 0.02):
            loss = _fit_loss(float(home_lambda), float(away_lambda), targets)
            if loss < best_loss:
                best = (float(home_lambda), float(away_lambda))
                best_loss = loss
    return best


def _fit_loss(lambda_home: float, lambda_away: float, targets: list[tuple[str, tuple[float, ...], float, float]]) -> float:
    grid = _score_grid(lambda_home, lambda_away, FIT_SCORE_MAX)
    loss = 0.0
    for kind, params, target, weight in targets:
        model = _model_probability(grid, kind, params)
        loss += weight * (model - target) ** 2
    return loss


def _model_probability(grid: np.ndarray, kind: str, params: tuple[float, ...]) -> float:
    max_score = grid.shape[0] - 1
    if kind == "home_win":
        return float(np.tril(grid, k=-1).sum())
    if kind == "away_win":
        return float(np.triu(grid, k=1).sum())
    if kind == "draw":
        return float(np.trace(grid))
    if kind == "over":
        line = params[0]
        return float(sum(grid[h, a] for h in range(max_score + 1) for a in range(max_score + 1) if h + a > line))
    if kind == "btts":
        return float(grid[1:, 1:].sum())
    if kind == "score":
        h, a = int(params[0]), int(params[1])
        return float(grid[h, a]) if h <= max_score and a <= max_score else 0.0
    if kind == "asian_home":
        handicap = params[0]
        return float(sum(grid[h, a] for h in range(max_score + 1) for a in range(max_score + 1) if h + handicap > a))
    return 0.0


def _add_over_under_targets(
    targets: list[tuple[str, tuple[float, ...], float, float]],
    runners: list[dict[str, Any]],
    line: float,
    weight: float,
) -> None:
    probs = _normalised_runner_probabilities(runners)
    for runner_key, probability in probs.items():
        name = str(runner_key[0]).lower()
        if name == "over" or name.startswith("over "):
            targets.append(("over", (line,), probability, weight))


def _normalised_runner_probabilities(runners: list[dict[str, Any]]) -> dict[tuple[str, float | None], float]:
    raw: dict[tuple[str, float | None], float] = {}
    for runner in runners:
        price = _runner_mid_price(runner)
        if price is None or price <= 1:
            continue
        key = (str(runner.get("name") or ""), runner.get("handicap"))
        raw[key] = 1.0 / price
    total = sum(raw.values())
    if total <= 0:
        return {}
    return {key: value / total for key, value in raw.items()}


def _runner_mid_price(runner: dict[str, Any]) -> float | None:
    back = runner.get("back")
    lay = runner.get("lay")
    if back is not None and lay is not None:
        return (float(back) + float(lay)) / 2
    if back is not None:
        return float(back)
    if lay is not None:
        return float(lay)
    return None


def _score_grid(lambda_home: float, lambda_away: float, score_max: int) -> np.ndarray:
    home = _poisson_probs(lambda_home, score_max)
    away = _poisson_probs(lambda_away, score_max)
    grid = np.outer(home, away)
    total = grid.sum()
    return grid / total if total > 0 else grid


def _poisson_probs(lam: float, score_max: int) -> np.ndarray:
    values = np.array([math.exp(-lam) * lam**k / math.factorial(k) for k in range(score_max + 1)], dtype=float)
    return values


def _market_payload(catalogue: dict[str, Any], book: dict[str, Any]) -> dict[str, Any]:
    runner_names = {runner["selectionId"]: runner.get("runnerName") for runner in catalogue.get("runners", [])}
    runners = []
    for runner in book.get("runners", []):
        ex = runner.get("ex", {})
        backs = ex.get("availableToBack") or []
        lays = ex.get("availableToLay") or []
        runners.append(
            {
                "selection_id": runner.get("selectionId"),
                "name": runner_names.get(runner.get("selectionId")),
                "handicap": runner.get("handicap"),
                "status": runner.get("status"),
                "back": backs[0]["price"] if backs else None,
                "lay": lays[0]["price"] if lays else None,
            }
        )
    description = catalogue.get("description", {})
    return {
        "market_id": catalogue.get("marketId"),
        "market_name": catalogue.get("marketName"),
        "market_type": description.get("marketType"),
        "status": book.get("status"),
        "total_matched": float(book.get("totalMatched") or 0.0),
        "runners": runners,
    }


def _map_provider_events(config: EventConfig, matches: pd.DataFrame, provider_events: list[dict[str, Any]]) -> list[EventMapping]:
    match_rows = []
    for row in matches.itertuples(index=False):
        match_rows.append(
            {
                "match_id": str(row.match_id),
                "team_a": _team_key(str(row.team_a_name)),
                "team_b": _team_key(str(row.team_b_name)),
                "kickoff": _to_datetime(row.kickoff_utc),
            }
        )
    mappings: list[EventMapping] = []
    used: set[str] = set()
    for item in provider_events:
        event = item.get("event", {})
        provider_event_id = str(event.get("id") or "")
        name = str(event.get("name") or "")
        parsed = _parse_provider_event_name(name)
        if parsed is None or provider_event_id in used:
            continue
        home_name, away_name = parsed
        home_key = _team_key(home_name)
        away_key = _team_key(away_name)
        open_date = datetime.fromisoformat(str(event.get("openDate")).replace("Z", "+00:00"))
        for match in match_rows:
            if abs(open_date - match["kickoff"]) > timedelta(hours=4):
                continue
            if home_key == match["team_a"] and away_key == match["team_b"]:
                mappings.append(EventMapping(match["match_id"], provider_event_id, name, home_name, away_name, False))
                used.add(provider_event_id)
                break
            if home_key == match["team_b"] and away_key == match["team_a"]:
                mappings.append(EventMapping(match["match_id"], provider_event_id, name, home_name, away_name, True))
                used.add(provider_event_id)
                break
    return mappings


def _parse_provider_event_name(name: str) -> tuple[str, str] | None:
    if " v " not in name:
        return None
    home, away = name.split(" v ", 1)
    return home.strip(), away.strip()


def _parse_score_name(name: str) -> tuple[int, int] | None:
    match = re.match(r"^\s*(\d+)\s*-\s*(\d+)\s*$", name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _team_key(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().replace("&", " and ")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized).strip()
    normalized = TEAM_ALIASES.get(normalized, normalized)
    return re.sub(r"\s+", " ", normalized)


def _is_half_line(value: float) -> bool:
    doubled = round(value * 2)
    return abs(value * 2 - doubled) < 1e-9 and doubled % 2 == 1


def _to_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _utc_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


def _snapshot_id(event_id: str, match_id: str, captured_at: datetime, provider: str) -> str:
    raw = f"{event_id}:{match_id}:{captured_at.isoformat()}:{provider}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _synthetic_lambdas(config: EventConfig, match_id: str, team_a_id: str, team_b_id: str, round_name: str) -> tuple[float, float]:
    strength_a = EURO_2024_STRENGTHS.get(team_a_id, 1.0)
    strength_b = EURO_2024_STRENGTHS.get(team_b_id, 1.0)
    seed = hashlib.sha256(f"{config.kanonenwilli_seed}:{match_id}:odds".encode("utf-8")).hexdigest()
    noise = (int(seed[:8], 16) / 0xFFFFFFFF - 0.5) * 0.22
    total_goals = 2.52 if round_name == "group" else 2.34
    diff = math.log(strength_a / strength_b) + noise
    if team_a_id == "GER" and config.event_id.startswith("euro_2024"):
        diff += 0.12
    lambda_a = total_goals / 2 * math.exp(diff / 2)
    lambda_b = total_goals / 2 * math.exp(-diff / 2)
    return max(0.25, min(lambda_a, 4.5)), max(0.25, min(lambda_b, 4.5))


def _synthetic_markets(team_a: str, team_b: str, probabilities: pd.DataFrame) -> list[dict[str, Any]]:
    grid = probabilities.pivot(index="score_a", columns="score_b", values="probability").fillna(0.0)
    home = float(sum(grid.loc[h, a] for h in grid.index for a in grid.columns if h > a))
    draw = float(sum(grid.loc[h, a] for h in grid.index for a in grid.columns if h == a))
    away = float(sum(grid.loc[h, a] for h in grid.index for a in grid.columns if h < a))
    over_25 = float(sum(grid.loc[h, a] for h in grid.index for a in grid.columns if h + a > 2.5))
    btts = float(sum(grid.loc[h, a] for h in grid.index for a in grid.columns if h > 0 and a > 0))
    return [
        _synthetic_market("MATCH_ODDS", "Match Odds", [(team_a, home), ("The Draw", draw), (team_b, away)]),
        _synthetic_market("OVER_UNDER_25", "Over/Under 2.5 Goals", [("Under 2.5 Goals", 1 - over_25), ("Over 2.5 Goals", over_25)]),
        _synthetic_market("BOTH_TEAMS_TO_SCORE", "Both teams to Score?", [("Yes", btts), ("No", 1 - btts)]),
    ]


def _synthetic_market(market_type: str, market_name: str, runners: list[tuple[str, float]]) -> dict[str, Any]:
    payload_runners = []
    for index, (name, probability) in enumerate(runners, start=1):
        fair = 1 / max(probability, 0.001)
        payload_runners.append(
            {
                "selection_id": index,
                "name": name,
                "handicap": None,
                "status": "ACTIVE",
                "back": round(fair * 0.98, 2),
                "lay": round(fair * 1.02, 2),
            }
        )
    return {
        "market_id": f"synthetic-{market_type.lower()}",
        "market_name": market_name,
        "market_type": market_type,
        "status": "OPEN",
        "total_matched": 1000.0,
        "runners": payload_runners,
    }
