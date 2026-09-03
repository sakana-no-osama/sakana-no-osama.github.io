from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

IN_CSV = "goal_events_2026.csv"
OUT_ALL = "team_ranking_2026_all.csv"
OUT_DIV1 = "team_ranking_2026_div1.csv"
OUT_DIV2 = "team_ranking_2026_div2.csv"


@dataclass
class TeamRankingRow:
    rank: int
    team: str
    division: str
    goals: int
    scorer_count: int
    match_count: int
    top_scorer: str
    note: str


class HoldError(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def backup_existing(path: Path) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{now_stamp()}")
        path.replace(backup)
        print(f"backup={backup}")


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def safe_int(value: str, label: str) -> int:
    s = normalize_text(value)
    if not s.isdigit():
        raise HoldError(f"invalid integer: {label}={value}")
    return int(s)


def read_goal_events(path: Path) -> List[dict]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[dict] = []

    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required_cols = {
            "match_id",
            "division",
            "team",
            "player",
            "goals",
            "goal_minutes",
            "source_url",
            "note",
        }

        missing_cols = required_cols - set(reader.fieldnames or [])
        if missing_cols:
            raise HoldError(f"missing columns in goal_events_2026.csv: {sorted(missing_cols)}")

        for i, r in enumerate(reader, start=2):
            match_id = normalize_text(r.get("match_id", ""))
            division = normalize_text(r.get("division", ""))
            team = normalize_text(r.get("team", ""))
            player = normalize_text(r.get("player", ""))
            goals_raw = normalize_text(r.get("goals", ""))
            note = normalize_text(r.get("note", ""))

            if not match_id:
                raise HoldError(f"blank match_id at csv line {i}")
            if not division:
                raise HoldError(f"blank division at match_id={match_id}")

            goals = safe_int(goals_raw, f"goals at match_id={match_id}")

            # 0-0試合などの診断行はCSVには残すが、ランキング集計からは除外する。
            if goals <= 0:
                continue

            if not team:
                raise HoldError(f"blank team at match_id={match_id}")
            if not player:
                raise HoldError(f"blank player at match_id={match_id}")

            rows.append(
                {
                    "match_id": match_id,
                    "division": division,
                    "team": team,
                    "player": player,
                    "goals": goals,
                    "note": note,
                }
            )

    if not rows:
        raise HoldError("no goal event rows found")

    return rows

def aggregate(rows: Sequence[dict], division_filter: str | None) -> List[TeamRankingRow]:
    grouped: Dict[Tuple[str, str], dict] = {}

    for r in rows:
        division = r["division"]

        if division_filter is not None and division != division_filter:
            continue

        out_division = division if division_filter is not None else "ALL"
        team = r["team"]
        player = r["player"]
        goals = r["goals"]
        match_id = r["match_id"]
        note = r["note"]

        key = (team, out_division)

        if key not in grouped:
            grouped[key] = {
                "team": team,
                "division": out_division,
                "goals": 0,
                "scorers": set(),
                "match_ids": set(),
                "player_goals": defaultdict(int),
                "notes": set(),
            }

        grouped[key]["goals"] += goals
        grouped[key]["scorers"].add(player)
        grouped[key]["match_ids"].add(match_id)
        grouped[key]["player_goals"][player] += goals

        if note:
            grouped[key]["notes"].add(note)

    raw_rows: List[TeamRankingRow] = []

    for item in grouped.values():
        player_goals = dict(item["player_goals"])
        if not player_goals:
            top_scorer = ""
        else:
            max_goals = max(player_goals.values())
            top_players = sorted(
                player for player, g in player_goals.items()
                if g == max_goals
            )
            top_scorer = "|".join(f"{p}({max_goals})" for p in top_players)

        notes = sorted(n for n in item["notes"] if n)

        raw_rows.append(
            TeamRankingRow(
                rank=0,
                team=item["team"],
                division=item["division"],
                goals=int(item["goals"]),
                scorer_count=len(item["scorers"]),
                match_count=len(item["match_ids"]),
                top_scorer=top_scorer,
                note=" | ".join(notes),
            )
        )

    raw_rows.sort(
        key=lambda r: (
            -r.goals,
            r.team,
            r.division,
        )
    )

    ranked: List[TeamRankingRow] = []
    prev_goals: int | None = None
    current_rank = 0

    for idx, row in enumerate(raw_rows, start=1):
        if prev_goals is None or row.goals != prev_goals:
            current_rank = idx
            prev_goals = row.goals

        ranked.append(
            TeamRankingRow(
                rank=current_rank,
                team=row.team,
                division=row.division,
                goals=row.goals,
                scorer_count=row.scorer_count,
                match_count=row.match_count,
                top_scorer=row.top_scorer,
                note=row.note,
            )
        )

    return ranked


def write_ranking(rows: Sequence[TeamRankingRow], path: Path) -> None:
    backup_existing(path)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rank",
            "team",
            "division",
            "goals",
            "scorer_count",
            "match_count",
            "top_scorer",
            "note",
        ])

        for r in rows:
            writer.writerow([
                r.rank,
                r.team,
                r.division,
                r.goals,
                r.scorer_count,
                r.match_count,
                r.top_scorer,
                r.note,
            ])


def summarize(name: str, rows: Sequence[TeamRankingRow]) -> str:
    teams = len(rows)
    goals = sum(r.goals for r in rows)
    top = rows[0].goals if rows else 0
    note_rows = sum(1 for r in rows if r.note.strip())
    return f"{name}: teams={teams}; goals={goals}; top_goals={top}; note_rows={note_rows}"


def main(argv: Sequence[str]) -> int:
    in_csv = Path(argv[1]) if len(argv) > 1 else Path(IN_CSV)

    try:
        events = read_goal_events(in_csv)

        all_rows = aggregate(events, None)
        div1_rows = aggregate(events, "1部")
        div2_rows = aggregate(events, "2部")

        write_ranking(all_rows, Path(OUT_ALL))
        write_ranking(div1_rows, Path(OUT_DIV1))
        write_ranking(div2_rows, Path(OUT_DIV2))

        print(summarize("ALL", all_rows))
        print(summarize("DIV1", div1_rows))
        print(summarize("DIV2", div2_rows))
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
