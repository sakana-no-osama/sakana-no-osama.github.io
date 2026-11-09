"""Independent, read-only checks of the saved 2026 source and derived data."""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"
PENDING_FILE = "pending_scorers_2026.csv"
PENDING_FIELDS = ["match_id", "home_score", "away_score", "source_url", "checked_on", "source_sha256", "reason"]


def read_pending_scorers(data: Path = DATA) -> dict[str, dict]:
    path = data / PENDING_FILE
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != PENDING_FIELDS:
            raise ValueError("pending scorers: invalid columns")
        pending = {}
        for row in reader:
            mid = row.get("match_id")
            if None in row or None in row.values() or not mid or mid in pending:
                raise ValueError("pending scorers: malformed or duplicate row")
            if row["reason"] != "official_scorers_not_published":
                raise ValueError(f"{mid}: unsupported pending reason")
            date.fromisoformat(row["checked_on"])
            if not re.fullmatch(r"[0-9a-f]{64}", row["source_sha256"]):
                raise ValueError(f"{mid}: missing source evidence hash")
            pending[mid] = row
    return pending


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path.name}: missing or duplicate columns")
        rows = list(reader)
    if not rows or any(None in row or None in row.values() for row in rows):
        raise ValueError(f"{path.name}: empty or malformed CSV")
    return rows


def integer(value: str, label: str) -> int:
    if not re.fullmatch(r"[0-9]+", value or ""):
        raise ValueError(f"{label}: invalid nonnegative integer {value!r}")
    return int(value)


def check_matches(data: Path = DATA) -> dict:
    master = read_csv(data / "matches_2026.csv")
    matches = read_csv(data / "matches_2026_played.csv")
    if matches != [row for row in master if row.get("status") == "played"]:
        raise ValueError("matches_2026_played.csv: not the exact played subset of master")
    aliases = {(r["division"], r["raw_team"]): r["canonical_team"]
               for r in read_csv(data / "team_name_alias_2026.csv")}
    by_id = {}
    for match in matches:
        mid = match["match_id"]
        if not mid or mid in by_id or match["division"] not in {"1部", "2部"}:
            raise ValueError(f"invalid/duplicate match: {mid}")
        by_id[mid] = match
    pending = read_pending_scorers(data)
    for mid, item in pending.items():
        if mid not in by_id:
            raise ValueError(f"{mid}: pending entry is not a played match")
        match = by_id[mid]
        if any(item[k] != match[k] for k in ("home_score", "away_score")) or item["source_url"].rstrip("/") != match["source_url"].rstrip("/"):
            raise ValueError(f"{mid}: pending evidence differs from match")
        if integer(item["home_score"], mid) + integer(item["away_score"], mid) == 0:
            raise ValueError(f"{mid}: zero score cannot be pending")
    events = read_csv(data / "goal_events_2026.csv")
    sums = Counter()
    diagnostics = Counter()
    seen = set()
    for line, row in enumerate(events, 2):
        mid = row["match_id"]
        if mid not in by_id:
            raise ValueError(f"goal_events_2026.csv:{line}: unknown match {mid}")
        match = by_id[mid]
        if row["division"] != match["division"] or row["match_date"] != match["match_date"]:
            raise ValueError(f"{mid}: event division/date differs from match")
        goals = integer(row["goals"], f"{mid}.goals")
        if row.get("note", "").startswith("fetch_failed"):
            raise ValueError(f"{mid}: unresolved fetch failure")
        if goals == 0:
            if mid not in pending and (integer(match["home_score"], mid) + integer(match["away_score"], mid)) != 0:
                raise ValueError(f"{mid}: diagnostic row for a nonzero match")
            if row["team"] or row["player"] or row.get("goal_minutes") or row.get("note") != "scorers_block_not_found":
                raise ValueError(f"{mid}: unsupported zero-goal diagnostic")
            diagnostics[mid] += 1
            continue
        if mid in pending:
            raise ValueError(f"{mid}: pending entry must be resolved before adding scorer events")
        if not row["team"].strip() or not row["player"].strip():
            raise ValueError(f"{mid}: positive goal with blank team/player")
        identity = tuple(sorted(row.items()))
        if identity in seen:
            raise ValueError(f"{mid}: duplicate goal event")
        seen.add(identity)
        team = aliases.get((row["division"], row["team"]), row["team"])
        teams = [aliases.get((match["division"], match[f]), match[f])
                 for f in ("home_team", "away_team")]
        if team not in teams:
            raise ValueError(f"{mid}: scorer team not in match: {team}")
        sums[mid, team] += goals
    for mid, match in by_id.items():
        if mid in pending:
            if diagnostics[mid] != 1:
                raise ValueError(f"{mid}: pending match needs exactly one unpublished diagnostic")
            continue
        for side in ("home", "away"):
            team = aliases.get((match["division"], match[f"{side}_team"]), match[f"{side}_team"])
            expected = integer(match[f"{side}_score"], f"{mid}.{side}_score")
            if sums[mid, team] != expected:
                raise ValueError(f"{mid}: {side} score/scorers expected={expected} actual={sums[mid, team]}")
    score_goals = sum(integer(r[side + "_score"], r["match_id"]) for r in matches for side in ("home", "away"))
    return {"matches": len(matches), "goals": sum(sums.values()), "score_goals": score_goals,
            "pending_matches": len(pending), "pending_goals": score_goals - sum(sums.values()),
            "scorer_completeness": "HOLD" if pending else "PASS",
            "latest": max(row["match_date"] for row in matches)}


def check_rankings(data: Path = DATA) -> dict:
    events = read_csv(data / "goal_events_2026.csv")
    positive = []
    for row in events:
        goals = integer(row["goals"], "event.goals")
        if row["division"] not in {"1部", "2部"}:
            raise ValueError("event: invalid division")
        if goals:
            if not all(row[k].strip() for k in ("team", "player", "match_id")):
                raise ValueError("positive event: blank team/player/match_id")
            positive.append(row)
    totals = {}
    for scope, division in (("all", "ALL"), ("div1", "1部"), ("div2", "2部")):
        selected = [r for r in positive if scope == "all" or r["division"] == division]
        totals[scope] = sum(int(r["goals"]) for r in selected)
        for kind in ("goal", "team"):
            grouped = defaultdict(list)
            for row in selected:
                key = (row["team"], row["player"]) if kind == "goal" else (row["team"],)
                grouped[key].append(row)
            expected = {}
            for key, group in grouped.items():
                result = {"team": key[0], "division": division,
                          "goals": str(sum(int(r["goals"]) for r in group)),
                          "match_count": str(len({r["match_id"] for r in group})),
                          "note": " | ".join(sorted({r["note"] for r in group if r["note"]}))}
                if kind == "goal":
                    result["player"] = key[1]
                else:
                    players = Counter()
                    for row in group:
                        players[row["player"]] += int(row["goals"])
                    top = max(players.values())
                    result["scorer_count"] = str(len(players))
                    result["top_scorer"] = "|".join(f"{p}({top})" for p in sorted(players) if players[p] == top)
                expected[key] = result
            ordered = sorted(expected.values(), key=lambda r: (-int(r["goals"]), r["team"], r.get("player", "")))
            previous = None
            for position, row in enumerate(ordered, 1):
                if row["goals"] != previous:
                    rank = position
                row["rank"] = str(rank)
                previous = row["goals"]
            name = f"{kind}_ranking_2026_{scope}.csv"
            actual = read_csv(data / name)
            if actual != ordered:
                mismatch = next((i for i, (a, e) in enumerate(zip(actual, ordered), 2) if a != e), None)
                raise ValueError(f"{name}: row-level mismatch (line={mismatch}, rows={len(actual)}/{len(ordered)})")
    if totals["all"] != totals["div1"] + totals["div2"]:
        raise ValueError("ALL != DIV1 + DIV2")
    return totals
