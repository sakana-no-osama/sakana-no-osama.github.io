"""Read explicit teams, dates and scores from official division listings."""
from datetime import datetime
import html
import re

from build_next_fixtures_2026 import capture, text_content


def parse_matches(page: str, division: str, fetched_at: str, teams: set[str]) -> list[dict]:
    code = "1" if division == "1部" else "2"
    source_page = f"https://u15.kantolsl.com/2026/div{code}/"
    tokens = list(re.finditer(
        r'(?P<section><div\s+class="sec"[^>]*>.*?</div>)|'
        r'(?P<game><div\s+class="anwp-fl-game\s+match-list__item[^>]*>)', page, re.S | re.I))
    section = ""
    rows = []
    ids = set()
    for index, token in enumerate(tokens):
        if token.group("section"):
            section = text_content(token.group())
            continue
        opening = token.group()
        end = tokens[index + 1].start() if index + 1 < len(tokens) else len(page)
        segment = page[token.start():end]
        status = re.search(r'\bgame-status-(\d+)\b', opening)
        stamp = re.search(r'data-fl-game-datetime="([^"]+)"', opening)
        link = re.search(r'<a\s+class="anwp-link-cover[^"]*"\s+href="([^"]+)"', segment)
        if not section or not status or not stamp or not link:
            raise ValueError(f"{division}: incomplete official match block")
        url = html.unescape(link.group(1))
        number = re.fullmatch(rf"https://u15\.kantolsl\.com/2026/div{code}/m(\d+)/?", url)
        if not number or status.group(1) not in {"0", "1"}:
            raise ValueError(f"{division}: unsupported URL/status: {url}")
        mid = f"2026_D{code}_m{int(number.group(1)):02d}"
        if mid in ids:
            raise ValueError(f"duplicate official match: {mid}")
        ids.add(mid)
        when = datetime.fromisoformat(stamp.group(1))
        if when.year != 2026:
            raise ValueError(f"{mid}: unexpected year")
        home = capture(segment, r'match-slim__team-home-title[^>]*>(.*?)</div>', "home")
        away = capture(segment, r'match-slim__team-away-title[^>]*>(.*?)</div>', "away")
        venue_match = re.search(r'match-slim__stadium[^>]*>(.*?)</div>', segment, re.S)
        venue = text_content(venue_match.group(1)) if venue_match else ""
        if home not in teams or away not in teams or home == away:
            raise ValueError(f"{mid}: teams not in official master")
        scores = [text_content(value) for value in re.findall(
            r'match-slim__scores-(?:home|away)[^>]*>(.*?)</span>', segment, re.S)]
        played = status.group(1) == "1"
        if len(scores) != 2 or (played and not all(re.fullmatch(r"\d+", s) for s in scores)):
            raise ValueError(f"{mid}: invalid played scores: {scores}")
        if not played and scores != ["-", "-"]:
            raise ValueError(f"{mid}: scheduled match with scores: {scores}")
        visible_time = capture(segment, r'<span class="match-slim__time\s[^>]*>(.*?)</span>', "kickoff")
        expected_time = f"{when.hour}時{when.minute:02d}分"
        if visible_time != expected_time:
            raise ValueError(f"{mid}: visible and structured kickoff differ")
        rows.append(dict(year="2026", division=division, match_id=mid,
                         url_key=f"m{int(number.group(1)):02d}", source_url=url.rstrip("/"),
                         match_date=when.date().isoformat(), kickoff=when.strftime("%H:%M"),
                         section=section, home_team=home, away_team=away,
                         home_score=scores[0] if played else "", away_score=scores[1] if played else "",
                         venue=venue, status="played" if played else "scheduled", fetched_at=fetched_at,
                         source_type="primary_match_page", discovered_from=source_page.rstrip("/"),
                         note="" if venue else "venue_not_published"))
    if not rows:
        raise ValueError(f"{division}: no official match blocks")
    return rows
