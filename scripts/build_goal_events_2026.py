from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
)

TIMEOUT = 20
IN_CSV = "matches_2026_played.csv"
OUT_CSV = "goal_events_2026.csv"


@dataclass(frozen=True)
class MatchRow:
    match_id: str
    division: str
    match_date: str
    section: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    source_url: str


@dataclass(frozen=True)
class GoalEvent:
    match_id: str
    division: str
    match_date: str
    section: str
    team: str
    player: str
    goals: int
    goal_minutes: str
    source_url: str
    note: str


class HoldError(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def z2h(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def normalize_space(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_noise(html_text: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", text)
    return text


def html_to_compact(html_text: str) -> str:
    text = strip_noise(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read()
    return body.decode(charset, errors="replace")


def safe_int(value: str, label: str) -> int:
    s = z2h((value or "").strip())
    if not re.fullmatch(r"[0-9]+", s):
        raise HoldError(f"invalid integer for {label}: {value}")
    return int(s)


def read_matches(path: Path) -> List[MatchRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[MatchRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for r in reader:
            status = (r.get("status") or "").strip()
            if status != "played":
                continue

            match_id = (r.get("match_id") or "").strip()
            division = (r.get("division") or "").strip()
            match_date = (r.get("match_date") or "").strip()
            section = (r.get("section") or "").strip()
            home_team = (r.get("home_team") or "").strip()
            away_team = (r.get("away_team") or "").strip()
            home_score_raw = (r.get("home_score") or "").strip()
            away_score_raw = (r.get("away_score") or "").strip()
            source_url = (r.get("source_url") or "").strip()

            missing = []
            if not match_id:
                missing.append("match_id")
            if not division:
                missing.append("division")
            if not match_date:
                missing.append("match_date")
            if not section:
                missing.append("section")
            if not home_team:
                missing.append("home_team")
            if not away_team:
                missing.append("away_team")
            if not home_score_raw:
                missing.append("home_score")
            if not away_score_raw:
                missing.append("away_score")
            if not source_url:
                missing.append("source_url")

            if missing:
                raise HoldError(
                    f"missing fields in matches csv: {match_id or '(blank)'}: {','.join(missing)}"
                )

            rows.append(
                MatchRow(
                    match_id=match_id,
                    division=division,
                    match_date=match_date,
                    section=section,
                    home_team=home_team,
                    away_team=away_team,
                    home_score=safe_int(home_score_raw, "home_score"),
                    away_score=safe_int(away_score_raw, "away_score"),
                    source_url=source_url,
                )
            )

    if not rows:
        raise HoldError("no played rows found in matches_2026_played.csv")

    return rows


def extract_scorers_block(compact: str) -> Tuple[str, str]:
    p = compact.find("【得点者】")
    if p == -1:
        return "", "scorers_block_not_found"

    block = compact[p + len("【得点者】"):].strip()

    end_markers = [
        "PDFファイルはこちらから",
        "Latest Matches",
        "前の記事",
        "次の記事",
        "Copyright ©",
        "MENU 検索",
        "PAGE TOP",
    ]

    end_positions = []
    for marker in end_markers:
        q = block.find(marker)
        if q != -1:
            end_positions.append(q)

    if end_positions:
        block = block[: min(end_positions)].strip()

    if not block:
        return "", "scorers_block_empty"

    return block, ""


def split_team_sections(block: str) -> Tuple[List[Tuple[str, str]], str]:
    matches = list(re.finditer(r"[【［\[]([^】］\]]+)[】］\]]", block))

    if not matches:
        return [], "team_heading_not_found"

    sections: List[Tuple[str, str]] = []

    for i, m in enumerate(matches):
        team = normalize_space(m.group(1))
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(block)
        content = normalize_space(block[start:end])

        if not team:
            continue

        sections.append((team, content))

    if not sections:
        return [], "team_sections_empty"

    return sections, ""

def normalize_minutes(minutes_text: str) -> List[str]:
    text = z2h(minutes_text or "")
    text = text.replace("，", "、")
    text = text.replace(",", "、")
    parts = [p.strip() for p in text.split("、") if p.strip()]
    return parts


def parse_player_line(line: str) -> Tuple[str, int, List[str], str]:
    """
    対応例:
      大隈 亜子２（23分、29分）
      高橋 杏莉（66分）
      選手名2(23分,29分)
      選手名（40+1分）
    """
    raw = normalize_space(line)
    raw = raw.strip("、, ")

    if not raw:
        return "", 0, [], "blank_player_line"

    m = re.match(r"^(?P<name>.+?)（(?P<minutes>[^）]+)）$", raw)
    if not m:
        m = re.match(r"^(?P<name>.+?)\((?P<minutes>[^)]+)\)$", raw)

    if not m:
        return "", 0, [], f"player_line_not_matched:{raw}"

    name_part = normalize_space(m.group("name"))
    minutes_text = normalize_space(m.group("minutes"))
    minutes = normalize_minutes(minutes_text)

    count = 1
    m_count = re.search(r"([0-9０-９]+)$", name_part)
    if m_count:
        count = int(z2h(m_count.group(1)))
        name_part = name_part[: m_count.start()].strip()

    player = normalize_space(name_part)

    if not player:
        return "", 0, minutes, f"player_blank:{raw}"

    if not minutes:
        return player, count, minutes, f"minutes_blank:{raw}"

    note = ""
    if len(minutes) != count:
        note = f"goal_count_minutes_mismatch:goals={count}:minutes={len(minutes)}"

    return player, count, minutes, note


def parse_section_content(match: MatchRow, team: str, content: str) -> List[GoalEvent]:
    events: List[GoalEvent] = []

    if not content:
        events.append(
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team=team,
                player="",
                goals=0,
                goal_minutes="",
                source_url=match.source_url,
                note="team_content_empty",
            )
        )
        return events

    chunks = []
    buf = ""
    for ch in content:
        buf += ch
        if ch in "）)":
            chunks.append(buf.strip())
            buf = ""

    if buf.strip():
        chunks.append(buf.strip())

    for chunk in chunks:
        chunk = normalize_space(chunk)
        if not chunk:
            continue

        player, goals, minutes, note = parse_player_line(chunk)

        if not player or goals <= 0:
            events.append(
                GoalEvent(
                    match_id=match.match_id,
                    division=match.division,
                    match_date=match.match_date,
                    section=match.section,
                    team=team,
                    player=player,
                    goals=0,
                    goal_minutes="|".join(minutes),
                    source_url=match.source_url,
                    note=note or "player_parse_failed",
                )
            )
            continue

        events.append(
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team=team,
                player=player,
                goals=goals,
                goal_minutes="|".join(minutes),
                source_url=match.source_url,
                note=note,
            )
        )

    if not events:
        events.append(
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team=team,
                player="",
                goals=0,
                goal_minutes="",
                source_url=match.source_url,
                note="no_player_events_in_team_section",
            )
        )

    return events


def parse_goal_events_for_match(match: MatchRow) -> List[GoalEvent]:
    try:
        html_text = fetch_text(match.source_url)
        compact = html_to_compact(html_text)
    except (HTTPError, URLError, TimeoutError) as e:
        return [
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team="",
                player="",
                goals=0,
                goal_minutes="",
                source_url=match.source_url,
                note=f"fetch_failed:{e}",
            )
        ]

    block, block_note = extract_scorers_block(compact)
    if block_note:
        return [
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team="",
                player="",
                goals=0,
                goal_minutes="",
                source_url=match.source_url,
                note=block_note,
            )
        ]

    sections, section_note = split_team_sections(block)
    if section_note:
        return [
            GoalEvent(
                match_id=match.match_id,
                division=match.division,
                match_date=match.match_date,
                section=match.section,
                team="",
                player="",
                goals=0,
                goal_minutes="",
                source_url=match.source_url,
                note=section_note,
            )
        ]

    events: List[GoalEvent] = []
    valid_teams = {match.home_team, match.away_team}

    for team, content in sections:
        team_note = ""
        if team not in valid_teams:
            team_note = f"team_heading_not_in_match:{team}"

        team_events = parse_section_content(match, team, content)

        for ev in team_events:
            note_parts = []
            if ev.note:
                note_parts.append(ev.note)
            if team_note:
                note_parts.append(team_note)

            events.append(
                GoalEvent(
                    match_id=ev.match_id,
                    division=ev.division,
                    match_date=ev.match_date,
                    section=ev.section,
                    team=ev.team,
                    player=ev.player,
                    goals=ev.goals,
                    goal_minutes=ev.goal_minutes,
                    source_url=ev.source_url,
                    note="; ".join(note_parts),
                )
            )

    expected_total = match.home_score + match.away_score
    actual_total = sum(ev.goals for ev in events if ev.goals > 0)

    if actual_total != expected_total:
        marked: List[GoalEvent] = []
        for ev in events:
            note = ev.note
            add = f"score_mismatch:expected={expected_total}:actual={actual_total}"
            note = f"{note}; {add}".strip("; ")
            marked.append(
                GoalEvent(
                    match_id=ev.match_id,
                    division=ev.division,
                    match_date=ev.match_date,
                    section=ev.section,
                    team=ev.team,
                    player=ev.player,
                    goals=ev.goals,
                    goal_minutes=ev.goal_minutes,
                    source_url=ev.source_url,
                    note=note,
                )
            )
        events = marked

    return events


def backup_existing(path: Path) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{now_stamp()}")
        path.replace(backup)
        print(f"backup={backup}")


def write_goal_events(rows: Sequence[GoalEvent], path: Path) -> None:
    backup_existing(path)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
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
        ])

        for r in rows:
            writer.writerow([
                r.match_id,
                r.division,
                r.match_date,
                r.section,
                r.team,
                r.player,
                r.goals,
                r.goal_minutes,
                r.source_url,
                r.note,
            ])


def summarize(events: Sequence[GoalEvent], matches: Sequence[MatchRow]) -> str:
    event_rows = len(events)
    goal_sum = sum(ev.goals for ev in events if ev.goals > 0)
    expected = sum(m.home_score + m.away_score for m in matches)
    note_rows = sum(1 for ev in events if ev.note.strip())
    mismatch_rows = sum(1 for ev in events if "score_mismatch" in ev.note)
    blank_player_rows = sum(1 for ev in events if not ev.player.strip())

    return (
        f"matches={len(matches)}; "
        f"event_rows={event_rows}; "
        f"goals={goal_sum}; "
        f"expected_goals={expected}; "
        f"note_rows={note_rows}; "
        f"score_mismatch_rows={mismatch_rows}; "
        f"blank_player_rows={blank_player_rows}"
    )


def main(argv: Sequence[str]) -> int:
    in_csv = Path(argv[1]) if len(argv) > 1 else Path(IN_CSV)
    out_csv = Path(argv[2]) if len(argv) > 2 else Path(OUT_CSV)

    try:
        matches = read_matches(in_csv)
        all_events: List[GoalEvent] = []

        for match in matches:
            events = parse_goal_events_for_match(match)
            all_events.extend(events)

        write_goal_events(all_events, out_csv)
        print(summarize(all_events, matches))
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
