"""Prepare verified update candidates from saved official HTML; never publish."""
from __future__ import annotations
import argparse
import csv
from collections import defaultdict
from dataclasses import asdict
from datetime import date, datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import build_goal_events_2026 as goal_events
import build_matches_2026_from_sources as match_pages
import build_goal_ranking_2026 as player_ranking
import build_team_ranking_2026 as team_ranking
import build_league_standings_2026 as standings
import build_next_fixtures_2026 as fixtures
from official_division import parse_matches
from ranking_checks import read_csv, check_matches, check_rankings
from workflow_io import atomic_text_writer


def write(path: Path, rows: list[dict], fields: list[str]) -> None:
    with atomic_text_writer(path, encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prepare(raw: Path, output: Path, as_of: date) -> dict:
    if output.resolve() == (ROOT / "data").resolve():
        raise ValueError("Candidate output must not be the official data directory")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty candidate directory to preserve prior candidates")
    masters, aliases = standings.load_names()
    old_matches = read_csv(ROOT / "data/matches_2026.csv")
    old_by_id = {row["match_id"]: row for row in old_matches}
    old_events = read_csv(ROOT / "data/goal_events_2026.csv")
    old_event_groups = defaultdict(list)
    for row in old_events:
        old_event_groups[row["match_id"]].append(row)
    all_matches, all_events, next_games, source_rows = [], [], [], []
    added = []
    evidence = {}
    def snapshot(path):
        body = path.read_bytes()
        evidence[path.name] = hashlib.sha256(body).hexdigest()
        return body.decode("utf-8")
    for number, division in ((1, "1部"), (2, "2部")):
        page_path = raw / f"div{number}.html"
        page = snapshot(page_path)
        stamp = datetime.fromtimestamp(page_path.stat().st_mtime, timezone(timedelta(hours=9))).isoformat(timespec="seconds")
        source_page = f"https://u15.kantolsl.com/2026/div{number}"
        source_rows.append(dict(year="2026", division=f"D{number}", source_type="primary_division_page",
                                source_url=source_page, discovered_from="https://u15.kantolsl.com/"))
        rows = parse_matches(page, division, stamp, masters[division])
        for row in rows:
            source_rows.append(dict(year="2026", division=f"D{number}", source_type="primary_match_page",
                                    source_url=row["source_url"], discovered_from=source_page))
            if row["status"] == "played":
                body = snapshot(raw / f'{row["match_id"]}.html')
                detail = match_pages.parse_match_page(row["source_url"], body)
                for field in ("match_date", "kickoff", "home_score", "away_score"):
                    if detail[field] != row[field]:
                        raise ValueError(f'{row["match_id"]}: official listing/detail mismatch: {field}')
                row["section"] = detail["section"]
                previous = old_by_id.get(row["match_id"])
                if previous and previous["status"] == "played":
                    for field in ("match_date", "home_score", "away_score"):
                        if previous[field] != row[field]:
                            raise ValueError(f'{row["match_id"]}: historical result changed: {field}')
                    for field in ("home_team", "away_team"):
                        canonical = aliases.get((division, previous[field]), previous[field])
                        if canonical != row[field]:
                            raise ValueError(f'{row["match_id"]}: historical team changed')
                    # Keep historical metadata and diagnostics after rechecking the facts.
                    row = dict(previous)
                else:
                    added.append(row["match_id"])
                match = goal_events.MatchRow(row["match_id"], division, row["match_date"], row["section"],
                    row["home_team"], row["away_team"], int(row["home_score"]), int(row["away_score"]), row["source_url"])
                events = [asdict(event) for event in goal_events.parse_goal_events_for_match(match, body)]
                previous_events = old_event_groups.get(row["match_id"])
                if previous_events:
                    signature = lambda values: [(r["team"], r["player"], str(r["goals"]), r["goal_minutes"]) for r in values]
                    if signature(events) != signature(previous_events):
                        raise ValueError(f'{row["match_id"]}: historical scorer facts changed; review source')
                    events = previous_events
                all_events.extend(events)
            all_matches.append(row)
        next_games.extend(asdict(item) for item in fixtures.parse_page(page, division, source_page, as_of, masters[division]))
    if {row["match_id"] for row in all_matches} != set(old_by_id):
        raise ValueError("Official match inventory changed; review before updating")
    new_played = {row["match_id"] for row in all_matches if row["status"] == "played"}
    if {row["match_id"] for row in old_matches if row["status"] == "played"} - new_played:
        raise ValueError("Previously played matches disappeared")
    output.mkdir(parents=True, exist_ok=True)
    for original in (ROOT / "data").glob("*.csv"):
        shutil.copy2(original, output / original.name)
    write(output / "matches_2026.csv", all_matches, list(old_matches[0]))
    write(output / "matches_2026_played.csv", [r for r in all_matches if r["status"] == "played"], list(old_matches[0]))
    write(output / "goal_events_2026.csv", all_events, list(old_events[0]))
    write(output / "match_sources_2026.csv", source_rows, list(source_rows[0]))
    write(output / "next_fixtures_2026.csv", next_games, fixtures.FIELDS)
    parsed_events = player_ranking.read_goal_events(output / "goal_events_2026.csv")
    for scope, division in (("all", None), ("div1", "1部"), ("div2", "2部")):
        for kind, module in (("goal", player_ranking), ("team", team_ranking)):
            ranked = [asdict(r) for r in module.aggregate(parsed_events, division)]
            write(output / f"{kind}_ranking_2026_{scope}.csv", ranked, list(ranked[0]))
    for division, suffix in (("1部", "div1"), ("2部", "div2")):
        ranked, _ = standings.build_division(all_matches, division, masters, aliases)
        write(output / f"league_standings_2026_{suffix}.csv", [asdict(r) for r in ranked], standings.FIELDS)
    report = dict(as_of=as_of.isoformat(), added_matches=added, matches=check_matches(output),
                  rankings=check_rankings(output), source_sha256=evidence)
    (output.parent / "update_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    try:
        result = prepare(args.raw_dir, args.output_dir, args.as_of)
        print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, ensure_ascii=False))
        print("Candidate data ready; full standings/fixtures and HTML verification still required")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"VERDICT=HOLD\nHOLD_REASON={exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
