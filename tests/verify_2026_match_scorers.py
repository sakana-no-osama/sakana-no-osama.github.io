from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATCHES = DATA / "matches_2026_played.csv"
EVENTS = DATA / "goal_events_2026.csv"
ALIASES = DATA / "team_name_alias_2026.csv"


def read_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"{path.name}: no rows")
    return rows


def main() -> int:
    try:
        matches = read_csv(MATCHES)
        events = read_csv(EVENTS)
        alias_rows = read_csv(ALIASES)
        aliases = {
            ((row.get("division") or "").strip(), (row.get("raw_team") or "").strip()):
            (row.get("canonical_team") or "").strip()
            for row in alias_rows
        }

        events_by_match: dict[str, list[dict]] = {}
        positive_goals = 0
        for line, event in enumerate(events, start=2):
            goals_text = (event.get("goals") or "").strip()
            if not goals_text.isdigit():
                raise ValueError(f"{EVENTS.name}:{line}: invalid goals")
            goals = int(goals_text)
            if goals == 0:
                continue
            team = (event.get("team") or "").strip()
            player = (event.get("player") or "").strip()
            if not team or not player:
                raise ValueError(f"{EVENTS.name}:{line}: positive goal with blank team/player")
            normalized = dict(event)
            division = (event.get("division") or "").strip()
            normalized["team"] = aliases.get((division, team), team)
            events_by_match.setdefault((event.get("match_id") or "").strip(), []).append(normalized)
            positive_goals += goals

        match_ids = set()
        score_goals = 0
        zero_zero_matches = 0
        normalized_matches = []
        for line, match in enumerate(matches, start=2):
            match_id = (match.get("match_id") or "").strip()
            division = (match.get("division") or "").strip()
            if not match_id or match_id in match_ids:
                raise ValueError(f"{MATCHES.name}:{line}: blank or duplicate match_id")
            match_ids.add(match_id)
            if (match.get("status") or "").strip() != "played":
                raise ValueError(f"{match_id}: status is not played")
            home_score = int((match.get("home_score") or "").strip())
            away_score = int((match.get("away_score") or "").strip())
            home_raw = (match.get("home_team") or "").strip()
            away_raw = (match.get("away_team") or "").strip()
            home = aliases.get((division, home_raw), home_raw)
            away = aliases.get((division, away_raw), away_raw)
            scorers = events_by_match.get(match_id, [])
            unknown = {event["team"] for event in scorers} - {home, away}
            if unknown:
                raise ValueError(f"{match_id}: scorer team not in match: {sorted(unknown)}")
            expected = home_score + away_score
            actual = sum(int(event["goals"]) for event in scorers)
            if actual != expected:
                raise ValueError(f"{match_id}: score/scorer mismatch expected={expected} actual={actual}")
            if expected == 0:
                zero_zero_matches += 1
            score_goals += expected
            normalized_matches.append({
                "match_id": match_id,
                "match_date": (match.get("match_date") or "").strip(),
                "kickoff": (match.get("kickoff") or "").strip(),
                "division": division,
                "home_team": home,
                "away_team": away,
            })

        orphan_events = set(events_by_match) - match_ids
        if orphan_events:
            raise ValueError(f"events for unknown matches: {sorted(orphan_events)}")
        if score_goals != positive_goals:
            raise ValueError(f"total mismatch scores={score_goals} events={positive_goals}")

        normalized_matches.sort(
            key=lambda row: (row["match_date"], row["kickoff"], row["match_id"]),
            reverse=True,
        )
        latest = normalized_matches[0]
        print(
            f"matches={len(matches)} goals={positive_goals} zero_zero={zero_zero_matches} "
            f"latest={latest['match_id']} {latest['match_date']} {latest['kickoff']} "
            f"{latest['home_team']} vs {latest['away_team']}"
        )
        print("VERDICT=PASS")
        return 0
    except (OSError, csv.Error, ValueError) as exc:
        print(f"VERDICT=FAIL\nFAIL_REASON={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
