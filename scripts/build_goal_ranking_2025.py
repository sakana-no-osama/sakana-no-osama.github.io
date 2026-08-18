from __future__ import annotations

import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Set, Tuple

IN_CSV = "goal_events_2025_normalized.csv"
OUT_ALL = "goal_ranking_2025_all.csv"
OUT_DIV1 = "goal_ranking_2025_div1.csv"
OUT_DIV2 = "goal_ranking_2025_div2.csv"


@dataclass
class RankingRow:
    rank: int
    player: str
    team: str
    division: str
    goals: int
    match_count: int
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


def safe_int(value: str, label: str) -> int:
    s = (value or "").strip()
    if not s.isdigit():
        raise HoldError(f"invalid integer: {label}={value}")
    return int(s)


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def read_goal_events(path: Path) -> List[dict]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[dict] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {
            "match_id",
            "division",
            "match_date",
            "section",
            "team",
            "player",
            "goals",
            "goal_minutes",
            "source_url",
            "note",
        }

        missing_cols = required - set(reader.fieldnames or [])
        if missing_cols:
            raise HoldError(f"missing columns in goal_events_2025.csv: {sorted(missing_cols)}")

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
            if not team:
                raise HoldError(f"blank team at match_id={match_id}")
            if not player:
                raise HoldError(f"blank player at match_id={match_id}")

            goals = safe_int(goals_raw, f"goals at match_id={match_id}")

            if goals <= 0:
                # 得点ランキングなので0点行は集計対象外。
                # ただし、この時点で0点行があるなら構造確認対象として止める。
                raise HoldError(f"non-positive goals row found: match_id={match_id}, player={player}, goals={goals}")

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


def aggregate(rows: Sequence[dict], division_filter: str | None) -> List[RankingRow]:
    """
    division_filter:
      None = 総合
      "1部" = 1部のみ
      "2部" = 2部のみ
    """
    grouped: Dict[Tuple[str, str, str], dict] = {}

    for r in rows:
        division = r["division"]

        if division_filter is not None and division != division_filter:
            continue

        player = r["player"]
        team = r["team"]
        goals = r["goals"]
        match_id = r["match_id"]
        note = r["note"]

        out_division = division if division_filter is not None else "ALL"
        key = (player, team, out_division)

        if key not in grouped:
            grouped[key] = {
                "player": player,
                "team": team,
                "division": out_division,
                "goals": 0,
                "match_ids": set(),
                "notes": set(),
            }

        grouped[key]["goals"] += goals
        grouped[key]["match_ids"].add(match_id)

        if note:
            grouped[key]["notes"].add(note)

    raw_rows: List[RankingRow] = []

    for item in grouped.values():
        notes = sorted(n for n in item["notes"] if n)
        raw_rows.append(
            RankingRow(
                rank=0,
                player=item["player"],
                team=item["team"],
                division=item["division"],
                goals=int(item["goals"]),
                match_count=len(item["match_ids"]),
                note=" | ".join(notes),
            )
        )

    raw_rows.sort(
        key=lambda r: (
            -r.goals,
            r.team,
            r.player,
            r.division,
        )
    )

    ranked: List[RankingRow] = []
    prev_goals: int | None = None
    current_rank = 0

    for idx, row in enumerate(raw_rows, start=1):
        if prev_goals is None or row.goals != prev_goals:
            current_rank = idx
            prev_goals = row.goals

        ranked.append(
            RankingRow(
                rank=current_rank,
                player=row.player,
                team=row.team,
                division=row.division,
                goals=row.goals,
                match_count=row.match_count,
                note=row.note,
            )
        )

    return ranked


def write_ranking(rows: Sequence[RankingRow], path: Path) -> None:
    backup_existing(path)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "rank",
            "player",
            "team",
            "division",
            "goals",
            "match_count",
            "note",
        ])

        for r in rows:
            writer.writerow([
                r.rank,
                r.player,
                r.team,
                r.division,
                r.goals,
                r.match_count,
                r.note,
            ])


def summarize(name: str, rows: Sequence[RankingRow]) -> str:
    players = len(rows)
    goals = sum(r.goals for r in rows)
    note_rows = sum(1 for r in rows if r.note.strip())
    top = rows[0].goals if rows else 0
    return f"{name}: players={players}; goals={goals}; top_goals={top}; note_rows={note_rows}"


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
