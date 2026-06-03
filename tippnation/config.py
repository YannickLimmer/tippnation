from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENT_CONFIG = ROOT / "data" / "events" / "international_friendlies_trial_2026.json"


@dataclass(frozen=True)
class RuleConfig:
    favorite: int
    max_factor: int
    exotic: int


@dataclass(frozen=True)
class MatchConfig:
    match_id: str
    sort_order: int
    kickoff_utc: datetime
    stage: str
    round_name: str
    group_name: str | None
    team_a_id: str
    team_b_id: str
    team_a_name: str
    team_b_name: str
    venue: str | None
    thesportsdb_event_id: str | None = None
    api_football_fixture_id: str | None = None


@dataclass(frozen=True)
class EventConfig:
    event_id: str
    name: str
    timezone: str
    language_default: str
    rules: dict[str, RuleConfig]
    teams: dict[str, str]
    matches: list[MatchConfig]
    kanonenwilli_seed: str
    betfair_competition_id: str | None = None
    betfair_event_type_id: str = "1"
    thesportsdb_league_id: str | None = None
    thesportsdb_season: str | None = None
    api_football_league_id: str | None = None
    api_football_season: str | None = None

    def local_timezone(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_event_config(path: Path = DEFAULT_EVENT_CONFIG) -> EventConfig:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = {
        key: RuleConfig(
            favorite=int(value["favorite"]),
            max_factor=int(value["max_factor"]),
            exotic=int(value["exotic"]),
        )
        for key, value in raw["rules"].items()
    }
    match_items = raw.get("matches") or _expand_matches(raw)
    matches = [
        MatchConfig(
            match_id=str(item["match_id"]),
            sort_order=int(item["sort_order"]),
            kickoff_utc=datetime.fromisoformat(item["kickoff_utc"].replace("Z", "+00:00")),
            stage=str(item["stage"]),
            round_name=str(item["round_name"]),
            group_name=item.get("group_name"),
            team_a_id=str(item["team_a_id"]),
            team_b_id=str(item["team_b_id"]),
            team_a_name=str(item["team_a_name"]),
            team_b_name=str(item["team_b_name"]),
            venue=item.get("venue"),
            thesportsdb_event_id=(
                str(item["thesportsdb_event_id"])
                if item.get("thesportsdb_event_id")
                else None
            ),
            api_football_fixture_id=(
                str(item["api_football_fixture_id"])
                if item.get("api_football_fixture_id")
                else None
            ),
        )
        for item in match_items
    ]
    return EventConfig(
        event_id=str(raw["event_id"]),
        name=str(raw["name"]),
        timezone=str(raw["timezone"]),
        language_default=str(raw.get("language_default", "en")),
        rules=rules,
        teams={str(key): str(value) for key, value in raw["teams"].items()},
        matches=matches,
        kanonenwilli_seed=str(raw.get("kanonenwilli_seed", raw["event_id"])),
        betfair_competition_id=(
            str(raw["betfair"]["competition_id"])
            if isinstance(raw.get("betfair"), dict) and raw["betfair"].get("competition_id")
            else None
        ),
        betfair_event_type_id=(
            str(raw["betfair"].get("event_type_id", "1"))
            if isinstance(raw.get("betfair"), dict)
            else "1"
        ),
        thesportsdb_league_id=(
            str(raw["thesportsdb"]["league_id"])
            if isinstance(raw.get("thesportsdb"), dict) and raw["thesportsdb"].get("league_id")
            else None
        ),
        thesportsdb_season=(
            str(raw["thesportsdb"]["season"])
            if isinstance(raw.get("thesportsdb"), dict) and raw["thesportsdb"].get("season")
            else None
        ),
        api_football_league_id=(
            str(raw["api_football"]["league_id"])
            if isinstance(raw.get("api_football"), dict) and raw["api_football"].get("league_id")
            else None
        ),
        api_football_season=(
            str(raw["api_football"]["season"])
            if isinstance(raw.get("api_football"), dict) and raw["api_football"].get("season")
            else None
        ),
    )


def _expand_matches(raw: dict) -> list[dict[str, object]]:
    if raw.get("event_id") != "world_cup_2026":
        raise ValueError("Event configs must define explicit matches unless they use the World Cup 2026 expander.")

    matches: list[dict[str, object]] = []
    explicit_group_fixtures = raw.get("group_stage_fixtures")
    if explicit_group_fixtures:
        for item in explicit_group_fixtures:
            matches.append(
                {
                    "match_id": str(item["match_id"]),
                    "sort_order": int(item["sort_order"]),
                    "kickoff_utc": str(item["kickoff_utc"]),
                    "stage": "group",
                    "round_name": "group",
                    "group_name": item.get("group_name"),
                    "team_a_id": str(item["team_a_id"]),
                    "team_b_id": str(item["team_b_id"]),
                    "team_a_name": str(raw["teams"][item["team_a_id"]]),
                    "team_b_name": str(raw["teams"][item["team_b_id"]]),
                    "venue": item.get("venue"),
                }
            )
        sort_order = max(int(item["sort_order"]) for item in explicit_group_fixtures) + 1
    else:
        sort_order = 1
        group_date_plan = raw["schedule_template"]["group_stage_dates"]
        pairings = [
            ("matchday_1", [("1", "2"), ("3", "4")]),
            ("matchday_2", [("1", "3"), ("4", "2")]),
            ("matchday_3", [("4", "1"), ("2", "3")]),
        ]
        for group in "ABCDEFGHIJKL":
            group_dates = group_date_plan[group]
            fixture_number = 1
            for matchday_index, (matchday, matchday_pairings) in enumerate(pairings):
                for pairing_index, (a_pos, b_pos) in enumerate(matchday_pairings):
                    date = group_dates[matchday_index]
                    if isinstance(date, list):
                        date = date[min(pairing_index, len(date) - 1)]
                    matches.append(
                        {
                            "match_id": f"{group}{fixture_number}",
                            "sort_order": sort_order,
                            "kickoff_utc": f"{date}T18:00:00+00:00",
                            "stage": "group",
                            "round_name": "group",
                            "group_name": group,
                            "team_a_id": f"{group}{a_pos}",
                            "team_b_id": f"{group}{b_pos}",
                            "team_a_name": f"Group {group} #{a_pos}",
                            "team_b_name": f"Group {group} #{b_pos}",
                            "venue": None,
                        }
                    )
                    fixture_number += 1
                    sort_order += 1

    knockout_rounds = [
        ("R32", "round_of_32", "Round of 32", "2026-06-28", 16),
        ("R16", "round_of_16", "Round of 16", "2026-07-04", 8),
        ("QF", "quarterfinal", "Quarterfinal", "2026-07-09", 4),
        ("SF", "semifinal", "Semifinal", "2026-07-14", 2),
        ("3P", "third_place", "Third place", "2026-07-18", 1),
        ("FIN", "final", "Final", "2026-07-19", 1),
    ]
    for prefix, round_name, label, first_date, count in knockout_rounds:
        first = datetime.fromisoformat(f"{first_date}T18:00:00+00:00")
        for number in range(1, count + 1):
            kickoff = first + timedelta(days=min(number - 1, 5 if prefix == "R32" else 3 if prefix == "R16" else 2))
            matches.append(
                {
                    "match_id": f"{prefix}{number}",
                    "sort_order": sort_order,
                    "kickoff_utc": kickoff.isoformat(),
                    "stage": "knockout",
                    "round_name": round_name,
                    "group_name": None,
                    "team_a_id": f"{prefix}{number}A",
                    "team_b_id": f"{prefix}{number}B",
                    "team_a_name": f"{label} {number} A",
                    "team_b_name": f"{label} {number} B",
                    "venue": None,
                }
            )
            sort_order += 1
    return matches


def config_as_json(config: EventConfig) -> str:
    return json.dumps(
        {
            "event_id": config.event_id,
            "name": config.name,
            "timezone": config.timezone,
            "language_default": config.language_default,
            "rules": {key: rule.__dict__ for key, rule in config.rules.items()},
            "teams": config.teams,
            "matches": [
                {
                    "match_id": match.match_id,
                    "sort_order": match.sort_order,
                    "kickoff_utc": match.kickoff_utc.isoformat(),
                    "stage": match.stage,
                    "round_name": match.round_name,
                    "group_name": match.group_name,
                    "team_a_id": match.team_a_id,
                    "team_b_id": match.team_b_id,
                    "team_a_name": match.team_a_name,
                    "team_b_name": match.team_b_name,
                    "venue": match.venue,
                    "thesportsdb_event_id": match.thesportsdb_event_id,
                    "api_football_fixture_id": match.api_football_fixture_id,
                }
                for match in config.matches
            ],
            "kanonenwilli_seed": config.kanonenwilli_seed,
            "betfair": {
                "competition_id": config.betfair_competition_id,
                "event_type_id": config.betfair_event_type_id,
            }
            if config.betfair_competition_id
            else None,
            "thesportsdb": {
                "league_id": config.thesportsdb_league_id,
                "season": config.thesportsdb_season,
            }
            if config.thesportsdb_league_id
            else None,
            "api_football": {
                "league_id": config.api_football_league_id,
                "season": config.api_football_season,
            }
            if config.api_football_league_id
            else None,
        },
        sort_keys=True,
    )
