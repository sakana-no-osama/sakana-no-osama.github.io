"""Build 2026 league standings from played matches with explicit aliases."""
from __future__ import annotations
import csv
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATCHES = DATA / "matches_2026.csv"
MASTER = DATA / "team_master_2026.csv"
ALIASES = DATA / "team_name_alias_2026.csv"
OUTPUTS = {
    "1部": DATA / "league_standings_2026_div1.csv",
    "2部": DATA / "league_standings_2026_div2.csv",
}
FIELDS = ["rank","team","division","played","wins","draws","losses","goals_for","goals_against","goal_difference","points","note"]

class HoldError(RuntimeError):
    pass

@dataclass
class Standing:
    rank: int
    team: str
    division: str
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0
    note: str = ""

def rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise HoldError(f"missing file: {path.relative_to(ROOT)}")
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]

def load_names() -> tuple[dict[str, set[str]], dict[tuple[str, str], str]]:
    masters = {division: set() for division in OUTPUTS}
    for row in rows(MASTER):
        year = (row.get("year") or "").strip()
        division = (row.get("division") or "").strip()
        team = (row.get("team") or "").strip()
        if year != "2026" or division not in masters or not team:
            raise HoldError(f"invalid team master row: {row}")
        if team in masters[division]:
            raise HoldError(f"duplicate team master: {division} {team}")
        masters[division].add(team)
    for division, teams in masters.items():
        if len(teams) != 8:
            raise HoldError(f"{division} team master count={len(teams)} expected=8")

    aliases: dict[tuple[str, str], str] = {}
    for row in rows(ALIASES):
        raw = (row.get("raw_team") or "").strip()
        canonical = (row.get("canonical_team") or "").strip()
        division = (row.get("division") or "").strip()
        key = (division, raw)
        if not raw or not canonical or division not in masters:
            raise HoldError(f"invalid alias row: {row}")
        if key in aliases:
            raise HoldError(f"duplicate alias: {division} {raw}")
        if canonical not in masters[division]:
            raise HoldError(f"alias target not in team master: {division} {canonical}")
        aliases[key] = canonical
    return masters, aliases

def canonical_team(raw: str, division: str, masters: dict[str, set[str]], aliases: dict[tuple[str, str], str]) -> tuple[str, bool]:
    source = (raw or "").strip()
    if not source:
        raise HoldError(f"blank team: {division}")
    canonical = aliases.get((division, source), source)
    if canonical not in masters[division]:
        raise HoldError(f"team not in master after alias: {division} {source!r}")
    return canonical, canonical != source

def number(value: str, label: str) -> int:
    text = (value or "").strip()
    if not text.isdigit():
        raise HoldError(f"invalid score: {label}={text!r}")
    return int(text)

def build_division(matches: list[dict[str, str]], division: str, masters: dict[str, set[str]], aliases: dict[tuple[str, str], str]) -> tuple[list[Standing], int]:
    stats: dict[str, Standing] = {}
    alias_uses = 0
    selected = [row for row in matches if (row.get("status") or "").strip() == "played" and (row.get("division") or "").strip() == division]
    if not selected:
        raise HoldError(f"no played matches: {division}")
    ids = [(row.get("match_id") or "").strip() for row in selected]
    if any(not match_id for match_id in ids) or len(ids) != len(set(ids)):
        raise HoldError(f"blank or duplicate played match_id: {division}")

    for match in selected:
        match_id = (match.get("match_id") or "").strip()
        home, home_alias = canonical_team(match.get("home_team") or "", division, masters, aliases)
        away, away_alias = canonical_team(match.get("away_team") or "", division, masters, aliases)
        alias_uses += int(home_alias) + int(away_alias)
        if home == away:
            raise HoldError(f"same home and away team after alias: {match_id}")
        hs = number(match.get("home_score") or "", f"{match_id}.home_score")
        aws = number(match.get("away_score") or "", f"{match_id}.away_score")
        h = stats.setdefault(home, Standing(0, home, division))
        a = stats.setdefault(away, Standing(0, away, division))
        h.played += 1; a.played += 1
        h.goals_for += hs; h.goals_against += aws
        a.goals_for += aws; a.goals_against += hs
        if hs > aws:
            h.wins += 1; a.losses += 1
        elif hs < aws:
            a.wins += 1; h.losses += 1
        else:
            h.draws += 1; a.draws += 1

    if set(stats) != masters[division]:
        raise HoldError(f"{division} team set mismatch: missing={sorted(masters[division]-set(stats))}")
    for row in stats.values():
        row.goal_difference = row.goals_for - row.goals_against
        row.points = row.wins * 3 + row.draws

    ordered = sorted(stats.values(), key=lambda row: (-row.points, -row.goal_difference, -row.goals_for))
    keys = [(row.points, row.goal_difference, row.goals_for) for row in ordered]
    ties = {key for key, count in Counter(keys).items() if count > 1}
    previous = None
    rank = 0
    for position, row in enumerate(ordered, 1):
        key = (row.points, row.goal_difference, row.goals_for)
        if key != previous:
            rank = position
            previous = key
        row.rank = rank
        row.note = "tied_hold" if key in ties else ""
    return ordered, alias_uses

def write_output(path: Path, standings: list[Standing]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(asdict(row) for row in standings)

def main() -> int:
    try:
        masters, aliases = load_names()
        matches = rows(MATCHES)
        unknown_divisions = {(row.get("division") or "").strip() for row in matches if (row.get("status") or "").strip() == "played"} - set(OUTPUTS)
        if unknown_divisions:
            raise HoldError(f"unknown played divisions: {sorted(unknown_divisions)}")
        built = {division: build_division(matches, division, masters, aliases) for division in OUTPUTS}
        for division, output in OUTPUTS.items():
            standings, alias_uses = built[division]
            write_output(output, standings)
            print(f"{division}: teams={len(standings)} matches={sum(row.played for row in standings)//2} alias_uses={alias_uses} tied_hold={sum(row.note == 'tied_hold' for row in standings)}")
        print("VERDICT=PASS")
        return 0
    except (HoldError, OSError, csv.Error) as exc:
        print(f"VERDICT=HOLD\nHOLD_REASON={exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())