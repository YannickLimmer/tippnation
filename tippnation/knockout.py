from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .config import EventConfig, MatchConfig
from .db import Database
from .repository import iso_now


Outcome = Literal["winner", "loser"]


@dataclass(frozen=True)
class AdvancementSource:
    outcome: Outcome
    official_match_number: int


@dataclass(frozen=True)
class AdvancementRule:
    target_match_id: str
    team_a_source: AdvancementSource
    team_b_source: AdvancementSource


OFFICIAL_TO_MATCH_ID = {
    73: "R321",
    76: "R322",
    74: "R323",
    75: "R324",
    78: "R325",
    77: "R326",
    79: "R327",
    80: "R328",
    82: "R329",
    81: "R3210",
    84: "R3211",
    83: "R3212",
    85: "R3213",
    88: "R3214",
    86: "R3215",
    87: "R3216",
    90: "R161",
    89: "R162",
    91: "R163",
    92: "R164",
    93: "R165",
    94: "R166",
    95: "R167",
    96: "R168",
    97: "QF1",
    98: "QF2",
    99: "QF3",
    100: "QF4",
    101: "SF1",
    102: "SF2",
    103: "3P1",
    104: "FIN1",
}


ADVANCEMENT_RULES = [
    AdvancementRule("R161", AdvancementSource("winner", 73), AdvancementSource("winner", 75)),
    AdvancementRule("R162", AdvancementSource("winner", 74), AdvancementSource("winner", 77)),
    AdvancementRule("R163", AdvancementSource("winner", 76), AdvancementSource("winner", 78)),
    AdvancementRule("R164", AdvancementSource("winner", 79), AdvancementSource("winner", 80)),
    AdvancementRule("R165", AdvancementSource("winner", 83), AdvancementSource("winner", 84)),
    AdvancementRule("R166", AdvancementSource("winner", 81), AdvancementSource("winner", 82)),
    AdvancementRule("R167", AdvancementSource("winner", 86), AdvancementSource("winner", 88)),
    AdvancementRule("R168", AdvancementSource("winner", 85), AdvancementSource("winner", 87)),
    AdvancementRule("QF1", AdvancementSource("winner", 89), AdvancementSource("winner", 90)),
    AdvancementRule("QF2", AdvancementSource("winner", 93), AdvancementSource("winner", 94)),
    AdvancementRule("QF3", AdvancementSource("winner", 91), AdvancementSource("winner", 92)),
    AdvancementRule("QF4", AdvancementSource("winner", 95), AdvancementSource("winner", 96)),
    AdvancementRule("SF1", AdvancementSource("winner", 97), AdvancementSource("winner", 98)),
    AdvancementRule("SF2", AdvancementSource("winner", 99), AdvancementSource("winner", 100)),
    AdvancementRule("3P1", AdvancementSource("loser", 101), AdvancementSource("loser", 102)),
    AdvancementRule("FIN1", AdvancementSource("winner", 101), AdvancementSource("winner", 102)),
]


def sync_knockout_advancement(db: Database, config: EventConfig) -> int:
    if config.event_id != "world_cup_2026":
        return 0

    rows = db.query(
        """
        SELECT match_id, team_a_id, team_b_id, team_a_name, team_b_name,
               result_a, result_b, status
        FROM matches
        WHERE event_id = ?
        """,
        (config.event_id,),
    )
    by_match_id = {str(row["match_id"]): dict(row) for row in rows}
    defaults = {match.match_id: match for match in config.matches}
    updates = []

    for rule in ADVANCEMENT_RULES:
        default = defaults.get(rule.target_match_id)
        current = by_match_id.get(rule.target_match_id)
        if default is None or current is None:
            continue

        desired = _default_team_values(default)
        team_a = _resolved_team(by_match_id, rule.team_a_source)
        team_b = _resolved_team(by_match_id, rule.team_b_source)
        if team_a is not None:
            desired["team_a_id"], desired["team_a_name"] = team_a
        if team_b is not None:
            desired["team_b_id"], desired["team_b_name"] = team_b

        if any(str(current.get(key) or "") != str(value) for key, value in desired.items()):
            desired["match_id"] = rule.target_match_id
            updates.append(desired)
            by_match_id[rule.target_match_id] = {**current, **desired}

    if not updates:
        return 0

    db.executemany(
        """
        UPDATE matches
        SET team_a_id = ?, team_b_id = ?, team_a_name = ?, team_b_name = ?, updated_at = ?
        WHERE event_id = ? AND match_id = ?
        """,
        [
            (
                row["team_a_id"],
                row["team_b_id"],
                row["team_a_name"],
                row["team_b_name"],
                iso_now(),
                config.event_id,
                row["match_id"],
            )
            for row in updates
        ],
    )
    return len(updates)


def _default_team_values(match: MatchConfig) -> dict[str, str]:
    return {
        "team_a_id": match.team_a_id,
        "team_b_id": match.team_b_id,
        "team_a_name": match.team_a_name,
        "team_b_name": match.team_b_name,
    }


def _resolved_team(
    by_match_id: dict[str, dict[str, object]],
    source: AdvancementSource,
) -> tuple[str, str] | None:
    source_match_id = OFFICIAL_TO_MATCH_ID[source.official_match_number]
    row = by_match_id.get(source_match_id)
    if row is None or str(row.get("status") or "") != "completed":
        return None
    result_a = row.get("result_a")
    result_b = row.get("result_b")
    if result_a is None or result_b is None:
        return None
    result_a = int(result_a)
    result_b = int(result_b)
    if result_a == result_b:
        return None

    team_a = (str(row["team_a_id"]), str(row["team_a_name"]))
    team_b = (str(row["team_b_id"]), str(row["team_b_name"]))
    if source.outcome == "winner":
        return team_a if result_a > result_b else team_b
    return team_b if result_a > result_b else team_a
