"""Build the next 2026 fixtures from official division pages."""
from __future__ import annotations
import csv
import html
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MASTER = DATA / "team_master_2026.csv"
OUTPUT = DATA / "next_fixtures_2026.csv"
SOURCES = {
    "1部": "https://u15.kantolsl.com/2026/div1/",
    "2部": "https://u15.kantolsl.com/2026/div2/",
}
DIV_CODES = {"1部": "D1", "2部": "D2"}
FIELDS = ["division","section","match_id","match_date","kickoff","home_team","away_team","venue","source_url","status","note"]
TIMEOUT = 30

class HoldError(RuntimeError):
    pass

@dataclass
class Fixture:
    division: str
    section: str
    match_id: str
    match_date: str
    kickoff: str
    home_team: str
    away_team: str
    venue: str
    source_url: str
    status: str = "scheduled"
    note: str = ""

def text_content(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value).replace("\xa0", " ")).strip()

def fetch(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 standings-fixtures/1.0"})
    with urlopen(request, timeout=TIMEOUT) as response:
        return response.read().decode("utf-8", "replace")

def master_teams() -> dict[str, set[str]]:
    result = {division: set() for division in SOURCES}
    with MASTER.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if (row.get("year") or "").strip() != "2026":
                continue
            division = (row.get("division") or "").strip()
            team = (row.get("team") or "").strip()
            if division not in result or not team or team in result[division]:
                raise HoldError(f"invalid team master row: {row}")
            result[division].add(team)
    if any(len(teams) != 8 for teams in result.values()):
        raise HoldError(f"team master must contain 8 teams per division")
    return result

def capture(segment: str, pattern: str, label: str) -> str:
    match = re.search(pattern, segment, re.S | re.I)
    if not match:
        raise HoldError(f"missing {label} in official match block")
    value = text_content(match.group(1))
    if not value:
        raise HoldError(f"blank {label} in official match block")
    return value

def parse_page(page: str, division: str, source_page: str, as_of: date, teams: set[str]) -> list[Fixture]:
    token_pattern = re.compile(
        r'(?P<section><div\s+class="sec"[^>]*>.*?</div>)|'
        r'(?P<game><div\s+class="anwp-fl-game\s+match-list__item[^>]*>)',
        re.S | re.I,
    )
    tokens = list(token_pattern.finditer(page))
    current_section = ""
    fixtures: list[Fixture] = []
    for index, token in enumerate(tokens):
        if token.group("section"):
            next_section = text_content(token.group("section"))
            if fixtures and next_section != fixtures[0].section:
                break
            current_section = next_section
            continue
        opening = token.group("game") or ""
        end = tokens[index + 1].start() if index + 1 < len(tokens) else len(page)
        segment = page[token.start():end]
        if "game-status-0" not in opening:
            continue
        if not current_section:
            raise HoldError(f"{division}: scheduled match without section")

        dt_match = re.search(r'data-fl-game-datetime="([^"]+)"', opening)
        if not dt_match:
            raise HoldError(f"{division} {current_section}: missing datetime")
        datetime_text = dt_match.group(1)
        if not datetime_text.startswith("2026-"):
            continue
        try:
            kickoff_at = datetime.fromisoformat(datetime_text)
        except ValueError as exc:
            raise HoldError(f"{division}: invalid datetime {datetime_text!r}") from exc
        if kickoff_at.date() < as_of:
            continue

        scores = [
            text_content(value)
            for value in re.findall(
                r'match-slim__scores-(?:home|away)[^>]*>(.*?)</span>',
                segment,
                re.S | re.I,
            )
        ]
        if scores != ["-", "-"]:
            raise HoldError(f"{division} {current_section}: scheduled score markers={scores}")

        home = capture(segment, r'match-slim__team-home-title[^>]*>(.*?)</div>', "home_team")
        away = capture(segment, r'match-slim__team-away-title[^>]*>(.*?)</div>', "away_team")
        venue = capture(segment, r'match-slim__stadium[^>]*>(.*?)</div>', "venue")
        link_match = re.search(
            r'<a\s+class="anwp-link-cover[^"]*"\s+href="([^"]+)"',
            segment,
            re.S | re.I,
        )
        if not link_match:
            raise HoldError(f"{division} {current_section}: missing source_url")
        source_url = html.unescape(link_match.group(1)).strip()
        id_match = re.search(r"/m(\d+)/?$", source_url)
        if not id_match:
            raise HoldError(f"{division}: invalid match URL {source_url}")
        if home not in teams or away not in teams:
            raise HoldError(f"{division}: team not in master: {home!r} vs {away!r}")
        if home == away:
            raise HoldError(f"{division}: same home and away team")

        fixtures.append(Fixture(
            division=division,
            section=current_section,
            match_id=f"2026_{DIV_CODES[division]}_m{int(id_match.group(1)):02d}",
            match_date=kickoff_at.date().isoformat(),
            kickoff=kickoff_at.strftime("%H:%M"),
            home_team=home,
            away_team=away,
            venue=venue,
            source_url=source_url,
        ))

    if not fixtures:
        raise HoldError(f"{division}: no future scheduled fixtures from {as_of}")
    earliest = min(fixtures, key=lambda row: (row.match_date, row.kickoff, row.match_id))
    selected = [row for row in fixtures if row.section == earliest.section]
    selected.sort(key=lambda row: (row.match_date, row.kickoff, row.match_id))
    if len(selected) != 4:
        raise HoldError(f"{division} {earliest.section}: fixtures={len(selected)} expected=4")
    appearances = [team for row in selected for team in (row.home_team, row.away_team)]
    if len(set(appearances)) != 8 or set(appearances) != teams:
        raise HoldError(f"{division} {earliest.section}: teams do not form one complete round")
    if len({row.match_id for row in selected}) != 4:
        raise HoldError(f"{division} {earliest.section}: duplicate match_id")
    return selected

def main() -> int:
    try:
        as_of = date.today()
        teams = master_teams()
        all_fixtures: list[Fixture] = []
        for division, url in SOURCES.items():
            selected = parse_page(fetch(url), division, url, as_of, teams[division])
            all_fixtures.extend(selected)
            print(f"{division}: section={selected[0].section} fixtures={len(selected)} first_date={selected[0].match_date}")
        with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(asdict(row) for row in all_fixtures)
        print(f"written={OUTPUT.relative_to(ROOT)}")
        print("VERDICT=PASS")
        return 0
    except (HoldError, OSError, csv.Error) as exc:
        print(f"VERDICT=HOLD\nHOLD_REASON={exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())