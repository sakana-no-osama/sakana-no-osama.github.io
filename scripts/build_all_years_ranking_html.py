from __future__ import annotations

import csv
import html
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence


OUT_HTML = Path("U15RANK_ALL_YEARS.html")
MATCH_RESULTS_CSV = "matches_2026_played.csv"
GOAL_EVENTS_CSV = "goal_events_2026.csv"
TEAM_ALIASES_CSV = "team_name_alias_2026.csv"

INPUTS = {
    "2026": {
        "player_all": "goal_ranking_2026_all.csv",
        "player_div1": "goal_ranking_2026_div1.csv",
        "player_div2": "goal_ranking_2026_div2.csv",
        "team_all": "team_ranking_2026_all.csv",
        "team_div1": "team_ranking_2026_div1.csv",
        "team_div2": "team_ranking_2026_div2.csv",
        "standings_div1": "league_standings_2026_div1.csv",
        "standings_div2": "league_standings_2026_div2.csv",
        "fixtures_all": "next_fixtures_2026.csv",
    },
    "2025": {
        "player_all": "goal_ranking_2025_all.csv",
        "player_div1": "goal_ranking_2025_div1.csv",
        "player_div2": "goal_ranking_2025_div2.csv",
        "team_all": "team_ranking_2025_all.csv",
        "team_div1": "team_ranking_2025_div1.csv",
        "team_div2": "team_ranking_2025_div2.csv",
    },
}


class HoldError(RuntimeError):
    pass


@dataclass(frozen=True)
class Dataset:
    year: str
    kind: str
    scope: str
    rows: List[dict]
    source: str


def now_local() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def backup_existing(path: Path) -> None:
    if path.exists():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = path.with_name(f"{path.name}.bak_{stamp}")
        backup.write_bytes(path.read_bytes())
        print(f"backup={backup}")


def read_csv_required(path: Path) -> List[dict]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        raise HoldError(f"input csv has no rows: {path}")

    return rows


def safe_int(value: str | None) -> int:
    s = (value or "").strip()
    return int(s) if s.isdigit() else 0


def validate_player_rows(rows: Sequence[dict], source: str) -> None:
    required = ["rank", "player", "team", "division", "goals", "match_count", "note"]
    for col in required:
        if col not in rows[0]:
            raise HoldError(f"{source}: missing column {col}")

    for i, r in enumerate(rows, start=2):
        if not (r.get("rank") or "").strip():
            raise HoldError(f"{source}: blank rank at csv line {i}")
        if not (r.get("player") or "").strip():
            raise HoldError(f"{source}: blank player at csv line {i}")
        if not (r.get("team") or "").strip():
            raise HoldError(f"{source}: blank team at csv line {i}")
        if not (r.get("goals") or "").strip().isdigit():
            raise HoldError(f"{source}: invalid goals at csv line {i}")


def validate_team_rows(rows: Sequence[dict], source: str) -> None:
    required = ["rank", "team", "division", "goals", "scorer_count", "match_count", "top_scorer", "note"]
    for col in required:
        if col not in rows[0]:
            raise HoldError(f"{source}: missing column {col}")

    for i, r in enumerate(rows, start=2):
        if not (r.get("rank") or "").strip():
            raise HoldError(f"{source}: blank rank at csv line {i}")
        if not (r.get("team") or "").strip():
            raise HoldError(f"{source}: blank team at csv line {i}")
        if not (r.get("goals") or "").strip().isdigit():
            raise HoldError(f"{source}: invalid goals at csv line {i}")


def validate_standings_rows(rows: Sequence[dict], source: str) -> None:
    required = [
        "rank", "team", "division", "played", "wins", "draws", "losses",
        "goals_for", "goals_against", "goal_difference", "points", "note",
    ]
    for col in required:
        if col not in rows[0]:
            raise HoldError(f"{source}: missing column {col}")
    for i, r in enumerate(rows, start=2):
        if not (r.get("rank") or "").strip() or not (r.get("team") or "").strip():
            raise HoldError(f"{source}: blank rank or team at csv line {i}")
        for col in ["played", "wins", "draws", "losses", "goals_for", "goals_against", "points"]:
            if not (r.get(col) or "").strip().isdigit():
                raise HoldError(f"{source}: invalid {col} at csv line {i}")
        try:
            int((r.get("goal_difference") or "").strip())
        except ValueError as e:
            raise HoldError(f"{source}: invalid goal_difference at csv line {i}") from e


def validate_fixture_rows(rows: Sequence[dict], source: str) -> None:
    required = [
        "division", "section", "match_id", "match_date", "kickoff",
        "home_team", "away_team", "venue", "source_url", "status", "note",
    ]
    for col in required:
        if col not in rows[0]:
            raise HoldError(f"{source}: missing column {col}")
    for i, r in enumerate(rows, start=2):
        for col in ["division", "section", "match_id", "match_date", "home_team", "away_team", "status"]:
            if not (r.get(col) or "").strip():
                raise HoldError(f"{source}: blank {col} at csv line {i}")


def load_team_aliases() -> Dict[tuple[str, str], str]:
    rows = read_csv_required(Path(TEAM_ALIASES_CSV))
    required = ["raw_team", "canonical_team", "division"]
    for col in required:
        if col not in rows[0]:
            raise HoldError(f"{TEAM_ALIASES_CSV}: missing column {col}")
    aliases: Dict[tuple[str, str], str] = {}
    for i, row in enumerate(rows, start=2):
        raw = (row.get("raw_team") or "").strip()
        canonical = (row.get("canonical_team") or "").strip()
        division = (row.get("division") or "").strip()
        if not raw or not canonical or division not in {"1部", "2部"}:
            raise HoldError(f"{TEAM_ALIASES_CSV}: invalid alias at csv line {i}")
        aliases[(division, raw)] = canonical
    return aliases


def load_match_result_datasets() -> Dict[str, Dataset]:
    matches = read_csv_required(Path(MATCH_RESULTS_CSV))
    events = read_csv_required(Path(GOAL_EVENTS_CSV))
    aliases = load_team_aliases()
    match_required = [
        "match_id", "division", "match_date", "kickoff", "section",
        "home_team", "away_team", "home_score", "away_score", "status",
    ]
    event_required = ["match_id", "division", "team", "player", "goals", "goal_minutes"]
    for col in match_required:
        if col not in matches[0]:
            raise HoldError(f"{MATCH_RESULTS_CSV}: missing column {col}")
    for col in event_required:
        if col not in events[0]:
            raise HoldError(f"{GOAL_EVENTS_CSV}: missing column {col}")

    events_by_match: Dict[str, List[dict]] = {}
    for i, event in enumerate(events, start=2):
        goals_text = (event.get("goals") or "").strip()
        if not goals_text.isdigit():
            raise HoldError(f"{GOAL_EVENTS_CSV}: invalid goals at csv line {i}")
        goals = int(goals_text)
        if goals == 0:
            continue
        team = (event.get("team") or "").strip()
        player = (event.get("player") or "").strip()
        division = (event.get("division") or "").strip()
        if not team or not player:
            raise HoldError(f"{GOAL_EVENTS_CSV}: positive goal with blank team/player at csv line {i}")
        normalized = dict(event)
        normalized["team"] = aliases.get((division, team), team)
        normalized["goals"] = goals_text
        events_by_match.setdefault((event.get("match_id") or "").strip(), []).append(normalized)

    result_rows: List[dict] = []
    seen_match_ids = set()
    for i, match in enumerate(matches, start=2):
        match_id = (match.get("match_id") or "").strip()
        division = (match.get("division") or "").strip()
        if not match_id or match_id in seen_match_ids:
            raise HoldError(f"{MATCH_RESULTS_CSV}: blank or duplicate match_id at csv line {i}")
        seen_match_ids.add(match_id)
        if (match.get("status") or "").strip() != "played":
            raise HoldError(f"{MATCH_RESULTS_CSV}: non-played row at csv line {i}")
        if division not in {"1部", "2部"}:
            raise HoldError(f"{MATCH_RESULTS_CSV}: invalid division at csv line {i}")
        home_score_text = (match.get("home_score") or "").strip()
        away_score_text = (match.get("away_score") or "").strip()
        if not home_score_text.isdigit() or not away_score_text.isdigit():
            raise HoldError(f"{MATCH_RESULTS_CSV}: invalid score at csv line {i}")
        home = aliases.get((division, (match.get("home_team") or "").strip()), (match.get("home_team") or "").strip())
        away = aliases.get((division, (match.get("away_team") or "").strip()), (match.get("away_team") or "").strip())
        if not home or not away or home == away:
            raise HoldError(f"{MATCH_RESULTS_CSV}: invalid teams at csv line {i}")

        match_events = events_by_match.get(match_id, [])
        unknown_teams = {event["team"] for event in match_events} - {home, away}
        if unknown_teams:
            raise HoldError(f"{match_id}: scorer team not in match: {sorted(unknown_teams)}")
        expected = int(home_score_text) + int(away_score_text)
        actual = sum(int(event["goals"]) for event in match_events)
        if actual != expected:
            raise HoldError(f"{match_id}: score/scorer mismatch expected={expected} actual={actual}")

        result_rows.append({
            "match_id": match_id,
            "division": division,
            "match_date": (match.get("match_date") or "").strip(),
            "kickoff": (match.get("kickoff") or "").strip(),
            "section": (match.get("section") or "").strip(),
            "home_team": home,
            "away_team": away,
            "home_score": home_score_text,
            "away_score": away_score_text,
            "home_scorers": [event for event in match_events if event["team"] == home],
            "away_scorers": [event for event in match_events if event["team"] == away],
        })

    orphan_events = set(events_by_match) - seen_match_ids
    if orphan_events:
        raise HoldError(f"{GOAL_EVENTS_CSV}: events for unknown matches: {sorted(orphan_events)}")
    result_rows.sort(
        key=lambda row: (row["match_date"], row["kickoff"], row["match_id"]),
        reverse=True,
    )
    source = f"{MATCH_RESULTS_CSV} + {GOAL_EVENTS_CSV}"
    return {
        "2026_results_all": Dataset("2026", "results", "all", result_rows, source),
        "2026_results_div1": Dataset(
            "2026", "results", "div1",
            [row for row in result_rows if row["division"] == "1部"], source,
        ),
        "2026_results_div2": Dataset(
            "2026", "results", "div2",
            [row for row in result_rows if row["division"] == "2部"], source,
        ),
    }


def load_datasets() -> Dict[str, Dataset]:
    datasets: Dict[str, Dataset] = {}

    for year, files in INPUTS.items():
        for key, filename in files.items():
            path = Path(filename)
            rows = read_csv_required(path)

            if key.startswith("player_"):
                validate_player_rows(rows, filename)
                kind = "player"
            elif key.startswith("team_"):
                validate_team_rows(rows, filename)
                kind = "team"
            elif key.startswith("standings_"):
                validate_standings_rows(rows, filename)
                kind = "standings"
            elif key.startswith("fixtures_"):
                validate_fixture_rows(rows, filename)
                kind = "fixtures"
            else:
                raise HoldError(f"unknown input key: {key}")

            if key.endswith("_all"):
                scope = "all"
            elif key.endswith("_div1"):
                scope = "div1"
            elif key.endswith("_div2"):
                scope = "div2"
            else:
                raise HoldError(f"unknown scope key: {key}")

            datasets[f"{year}_{key}"] = Dataset(
                year=year,
                kind=kind,
                scope=scope,
                rows=rows,
                source=filename,
            )

    datasets.update(load_match_result_datasets())
    return datasets


def esc(value: str | None) -> str:
    return html.escape((value or "").strip(), quote=True)


def note_comment(label: str, rows: Sequence[dict]) -> str:
    lines = [f"<!-- NOTES {label}"]
    for r in rows:
        note = (r.get("note") or "").strip()
        if note:
            if "player" in r:
                subject = f"player={r.get('player','')} team={r.get('team','')} division={r.get('division','')} rank={r.get('rank','')}"
            else:
                subject = f"team={r.get('team','')} division={r.get('division','')} rank={r.get('rank','')}"
            lines.append(f"{subject} note={note}")
    lines.append("-->")
    return "\n".join(lines)


def build_player_table_rows(rows: Sequence[dict]) -> str:
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f"<td class=\"rank\">{esc(r.get('rank'))}</td>"
            f"<td class=\"player\">{esc(r.get('player'))}</td>"
            f"<td class=\"team team-name\" data-team=\"{esc(r.get('team'))}\">{esc(r.get('team'))}</td>"
            f"<td class=\"num\">{esc(r.get('goals'))}</td>"
            f"<td class=\"num\">{esc(r.get('match_count'))}</td>"
            "</tr>"
        )
    return "\n".join(out)


def build_team_table_rows(rows: Sequence[dict]) -> str:
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f"<td class=\"rank\">{esc(r.get('rank'))}</td>"
            f"<td class=\"team team-name\" data-team=\"{esc(r.get('team'))}\">{esc(r.get('team'))}</td>"
            f"<td class=\"num\">{esc(r.get('goals'))}</td>"
            f"<td class=\"num\">{esc(r.get('scorer_count'))}</td>"
            f"<td class=\"num\">{esc(r.get('match_count'))}</td>"
            f"<td class=\"top-scorer\">{esc(r.get('top_scorer'))}</td>"
            "</tr>"
        )
    return "\n".join(out)


def build_standings_table_rows(rows: Sequence[dict]) -> str:
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f"<td class=\"rank\">{esc(r.get('rank'))}</td>"
            f"<td class=\"team\">{esc(r.get('team'))}</td>"
            f"<td class=\"num\">{esc(r.get('played'))}</td>"
            f"<td class=\"num\">{esc(r.get('wins'))}</td>"
            f"<td class=\"num\">{esc(r.get('draws'))}</td>"
            f"<td class=\"num\">{esc(r.get('losses'))}</td>"
            f"<td class=\"num\">{esc(r.get('goals_for'))}</td>"
            f"<td class=\"num\">{esc(r.get('goals_against'))}</td>"
            f"<td class=\"num\">{esc(r.get('goal_difference'))}</td>"
            f"<td class=\"num\">{esc(r.get('points'))}</td>"
            "</tr>"
        )
    return "\n".join(out)


def build_fixture_cards(rows: Sequence[dict]) -> str:
    cards = []
    for r in rows:
        cards.append(
            '<article class="fixture-card">'
            '<div class="fixture-top">'
            f'<span class="fixture-division">{esc(r.get("division"))}</span>'
            f'<span class="fixture-round">{esc(r.get("section"))}</span>'
            '</div>'
            '<div class="fixture-datetime">'
            f'<span>{esc(r.get("match_date"))}</span>'
            f'<strong>{esc(r.get("kickoff"))}</strong>'
            '</div>'
            '<div class="fixture-matchup">'
            f'<span class="fixture-team home">{esc(r.get("home_team"))}</span>'
            '<span class="fixture-vs">VS</span>'
            f'<span class="fixture-team away">{esc(r.get("away_team"))}</span>'
            '</div>'
            f'<p class="fixture-venue"><span>会場</span>{esc(r.get("venue"))}</p>'
            '</article>'
        )
    return "\n".join(cards)


def build_scorer_group(team: str, scorers: Sequence[dict]) -> str:
    if not scorers:
        body = '<p class="no-scorers">得点者なし</p>'
    else:
        items = []
        for scorer in scorers:
            goals = safe_int(scorer.get("goals"))
            goals_label = f" ×{goals}" if goals > 1 else ""
            minutes = esc(scorer.get("goal_minutes"))
            minute_label = f'<span class="scorer-minutes">{minutes}</span>' if minutes else ""
            items.append(
                f'<li><span class="scorer-name">{esc(scorer.get("player"))}{goals_label}</span>'
                f'{minute_label}</li>'
            )
        body = f'<ul class="scorer-list">{"".join(items)}</ul>'
    return f'<div class="scorer-team"><h4>{esc(team)}</h4>{body}</div>'


def build_result_cards(rows: Sequence[dict]) -> str:
    cards = []
    for index, row in enumerate(rows):
        cards.append(
            f'<article class="match-result-card" data-result-index="{index}">'
            f'<div class="match-meta"><span>{esc(row.get("match_date"))}</span>'
            f'<span>{esc(row.get("division"))}</span><span>{esc(row.get("section"))}</span>'
            f'<span>{esc(row.get("kickoff"))}</span></div>'
            '<div class="match-score">'
            f'<span class="match-team home">{esc(row.get("home_team"))}</span>'
            f'<strong>{esc(row.get("home_score"))}–{esc(row.get("away_score"))}</strong>'
            f'<span class="match-team away">{esc(row.get("away_team"))}</span>'
            '</div>'
            '<div class="scorer-groups">'
            f'{build_scorer_group(row["home_team"], row["home_scorers"])}'
            f'{build_scorer_group(row["away_team"], row["away_scorers"])}'
            '</div>'
            '</article>'
        )
    return "\n".join(cards)


def dataset_json(datasets: Dict[str, Dataset]) -> str:
    payload = {}
    for key, ds in datasets.items():
        payload[key] = ds.rows
    return json.dumps(payload, ensure_ascii=False)


def build_section(ds: Dataset) -> str:
    label_scope = {"all": "総合", "div1": "1部", "div2": "2部"}[ds.scope]
    label_kind = {
        "player": "個人",
        "team": "チーム得点",
        "standings": "チーム順位",
        "fixtures": "次節カード",
        "results": "試合別得点者",
    }[ds.kind]
    section_id = f"sec_{ds.year}_{ds.kind}_{ds.scope}"

    goals = sum(safe_int(r.get("goals")) for r in ds.rows) if ds.kind in {"player", "team"} else None
    note_rows = sum(1 for r in ds.rows if (r.get("note") or "").strip())

    if ds.kind == "results":
        past_count = max(len(ds.rows) - 1, 0)
        toggle = (
            f'<button type="button" class="results-toggle" data-results-toggle>'
            f'過去の試合を見る（{past_count}試合）</button>'
            if past_count else ""
        )
        return f"""
<section id="{section_id}" class="ranking-section result-section" data-year="{ds.year}" data-kind="{ds.kind}" data-scope="{ds.scope}">
  <div class="section-head">
    <h2>{esc(ds.year)} {esc(label_kind)} {esc(label_scope)}</h2>
    <p>通常は直近1試合を表示します。得点者はチーム別です。</p>
    <div class="stats">
      <span>試合数: {len(ds.rows)}</span>
      <span>出典: {esc(ds.source)}</span>
    </div>
  </div>
  <div class="match-results">
    {build_result_cards(ds.rows)}
  </div>
  <div class="results-actions">{toggle}</div>
</section>
"""

    if ds.kind == "fixtures":
        stats = [
            f"<span>試合数: {len(ds.rows)}</span>",
            f"<span>note保持: {note_rows}</span>",
            f"<span>出典: {esc(ds.source)}</span>",
        ]
        return f"""
<section id="{section_id}" class="ranking-section fixture-section" data-year="{ds.year}" data-kind="{ds.kind}" data-scope="{ds.scope}">
  {note_comment(f"{ds.year}_{ds.kind}_{ds.scope}", ds.rows)}
  <div class="section-head">
    <h2>{esc(ds.year)} {esc(label_kind)}{esc(label_scope)}</h2>
    <p>CSVで確認済みの次節カードです。</p>
    <div class="stats">
      {''.join(stats)}
    </div>
  </div>
  <div class="fixture-grid">
    {build_fixture_cards(ds.rows)}
  </div>
</section>
"""

    if ds.kind == "player":
        header = """
<thead>
<tr>
<th>順位</th>
<th>選手</th>
<th>チーム</th>
<th>得点</th>
<th>試合数</th>
</tr>
</thead>
"""
        body = build_player_table_rows(ds.rows)
        helper = "チーム名をタップすると、そのチーム内の個人ランキングを表示します。"
    elif ds.kind == "team":
        header = """
<thead>
<tr>
<th>順位</th>
<th>チーム</th>
<th>得点</th>
<th>得点者数</th>
<th>試合数</th>
<th>最多得点者</th>
</tr>
</thead>
"""
        body = build_team_table_rows(ds.rows)
        helper = "チーム名をタップすると、そのチーム内の個人ランキングを表示します。"
    elif ds.kind == "standings":
        header = """
<thead>
<tr>
<th>順位</th><th>チーム</th><th>試合</th><th>勝</th><th>分</th><th>負</th>
<th>得点</th><th>失点</th><th>得失点差</th><th>勝点</th>
</tr>
</thead>
"""
        body = build_standings_table_rows(ds.rows)
        helper = "勝点、得失点差、総得点の順で集計した順位表です。"
    stats = [f"<span>行数: {len(ds.rows)}</span>"]
    if goals is not None:
        stats.append(f"<span>得点: {goals}</span>")
    stats.extend([
        f"<span>note保持: {note_rows}</span>",
        f"<span>出典: {esc(ds.source)}</span>",
    ])

    return f"""
<section id="{section_id}" class="ranking-section" data-year="{ds.year}" data-kind="{ds.kind}" data-scope="{ds.scope}">
  {note_comment(f"{ds.year}_{ds.kind}_{ds.scope}", ds.rows)}
  <div class="section-head">
    <h2>{esc(ds.year)} {esc(label_kind)}{esc(label_scope)}</h2>
    <p>{esc(helper)}</p>
    <div class="stats">
      {''.join(stats)}
    </div>
  </div>
  <div class="table-wrap">
    <table>
      {header}
      <tbody>
      {body}
      </tbody>
    </table>
  </div>
</section>
"""


def build_html(datasets: Dict[str, Dataset]) -> str:
    sections = []

    order = [
        "2026_player_all", "2026_player_div1", "2026_player_div2",
        "2026_team_all", "2026_team_div1", "2026_team_div2",
        "2026_standings_div1", "2026_standings_div2",
        "2026_fixtures_all",
        "2026_results_all", "2026_results_div1", "2026_results_div2",
        "2025_player_all", "2025_player_div1", "2025_player_div2",
        "2025_team_all", "2025_team_div1", "2025_team_div2",
    ]

    for key in order:
        sections.append(build_section(datasets[key]))

    data_json = dataset_json(datasets)

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>2025-2026 関東U-15女子 得点ランキング</title>
<style>
:root {{
  --bg: #f8fbff;
  --card: #ffffff;
  --text: #26324b;
  --muted: #70809e;
  --line: #e3e9f4;
  --strong: #14213d;
  --navy: #172554;
  --accent: #6d28d9;
  --accent-2: #ec4899;
  --sky: #38bdf8;
  --accent-soft: #f3e8ff;
  --pink-soft: #fdf2f8;
  --sky-soft: #effaff;
  --shadow: 0 16px 40px rgba(37, 43, 78, 0.09);
  --shadow-soft: 0 8px 24px rgba(72, 60, 130, 0.07);
}}

* {{
  box-sizing: border-box;
}}

html,
body {{
  overflow-x: hidden;
}}

body {{
  margin: 0;
  min-height: 100vh;
  background:
    radial-gradient(circle at 0% 0%, rgba(236, 72, 153, 0.13), transparent 34%),
    radial-gradient(circle at 100% 8%, rgba(56, 189, 248, 0.16), transparent 32%),
    linear-gradient(180deg, #ffffff 0%, var(--bg) 42%, #f8f5ff 100%);
  color: var(--text);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}}

.page {{
  width: 100%;
  max-width: 1160px;
  margin: 0 auto;
  padding: 18px;
}}

.hero {{
  position: relative;
  overflow: hidden;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 20px;
  align-items: end;
  background: rgba(255, 255, 255, 0.92);
  color: var(--text);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 28px;
  padding: 28px;
  box-shadow: var(--shadow);
}}

.hero::before {{
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 6px;
  background: linear-gradient(90deg, var(--accent-2), #a855f7 48%, var(--sky));
}}

.hero::after {{
  content: "";
  position: absolute;
  width: 180px;
  height: 180px;
  right: -72px;
  top: -92px;
  border-radius: 50%;
  background: linear-gradient(145deg, rgba(236, 72, 153, 0.13), rgba(56, 189, 248, 0.12));
  pointer-events: none;
}}

.hero-copy,
.hero-meta {{
  position: relative;
  z-index: 1;
  min-width: 0;
}}

.hero-kicker {{
  margin: 0 0 8px !important;
  color: var(--accent) !important;
  font-size: 11px !important;
  font-weight: 900;
  letter-spacing: 0.14em;
}}

.hero h1 {{
  margin: 0 0 8px;
  color: var(--navy);
  font-size: clamp(22px, 4vw, 32px);
  line-height: 1.2;
  letter-spacing: -0.03em;
}}

.hero-title-break {{
  white-space: nowrap;
}}

.hero p {{
  margin: 4px 0;
  color: var(--muted);
  font-size: 13px;
}}

.hero-lead {{
  max-width: 620px;
  font-weight: 600;
}}

.hero-meta {{
  min-width: 190px;
  padding: 14px 16px;
  border: 1px solid #e8e5fb;
  border-radius: 18px;
  background: linear-gradient(145deg, #fdf2f8, #effaff);
}}

.hero-meta span {{
  display: block;
  margin-bottom: 3px;
  color: var(--accent);
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.12em;
}}

.controls {{
  position: sticky;
  top: 6px;
  z-index: 20;
  margin: 12px 0 16px;
  padding: 6px 0;
}}

.control-card {{
  min-width: 0;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(224, 229, 241, 0.9);
  border-radius: 22px;
  padding: 14px;
  box-shadow: var(--shadow-soft);
  backdrop-filter: blur(14px);
}}

.control-group {{
  margin-bottom: 10px;
}}

.control-label {{
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  font-weight: 800;
  letter-spacing: 0.04em;
}}

.buttons {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}}

button {{
  border: 1px solid var(--line);
  background: #fff;
  color: var(--strong);
  padding: 9px 13px;
  border-radius: 999px;
  font-weight: 800;
  font-size: 13px;
  cursor: pointer;
  transition: transform 0.16s ease, box-shadow 0.16s ease, border-color 0.16s ease;
}}

button:hover {{
  border-color: #c4b5fd;
  transform: translateY(-1px);
}}

button:focus-visible,
input:focus-visible {{
  outline: 3px solid rgba(56, 189, 248, 0.3);
  outline-offset: 2px;
}}

button.active {{
  background: linear-gradient(135deg, var(--accent-2), var(--accent));
  border-color: transparent;
  color: #fff;
  box-shadow: 0 7px 18px rgba(109, 40, 217, 0.22);
}}

.search-row {{
  display: flex;
  gap: 8px;
  min-width: 0;
}}

input[type="search"] {{
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 12px 14px;
  background: #fbfcff;
  color: var(--strong);
  font-size: 16px;
}}

.search-label {{
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}}

.ranking-section {{
  display: none;
  min-width: 0;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid rgba(225, 231, 243, 0.94);
  border-radius: 26px;
  box-shadow: var(--shadow);
  overflow: hidden;
  margin-bottom: 20px;
}}

.ranking-section.active {{
  display: block;
}}

.section-head {{
  position: relative;
  padding: 20px;
  border-bottom: 1px solid var(--line);
  background: linear-gradient(110deg, rgba(253, 242, 248, 0.8), rgba(239, 250, 255, 0.82));
}}

.section-head h2 {{
  margin: 0 0 6px;
  color: var(--navy);
  font-size: 21px;
  letter-spacing: -0.02em;
}}

.section-head p {{
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}}

.stats {{
  display: flex;
  min-width: 0;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}}

.stats span {{
  background: rgba(255, 255, 255, 0.86);
  border: 1px solid rgba(226, 232, 240, 0.86);
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 12px;
  color: #52617d;
  overflow-wrap: anywhere;
  max-width: 100%;
  min-width: 0;
}}

.table-wrap {{
  overflow-x: auto;
  scrollbar-color: #c4b5fd transparent;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 620px;
}}

th {{
  position: sticky;
  top: 0;
  z-index: 1;
  background: #fafaff;
  color: #4b5874;
  font-size: 12px;
  text-align: left;
  padding: 12px 10px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}}

td {{
  padding: 12px 10px;
  border-bottom: 1px solid #eef1f7;
  font-size: 14px;
  vertical-align: top;
}}

tbody tr:nth-child(even) {{
  background: #fcfbff;
}}

tbody tr:hover {{
  background: var(--sky-soft);
}}

td.rank,
td.num {{
  text-align: right;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}}

td.player,
td.team,
td.top-scorer {{
  font-weight: 700;
}}

.team-name {{
  color: var(--accent);
  text-decoration: underline dotted;
  text-decoration-color: #c4b5fd;
  text-underline-offset: 4px;
  cursor: pointer;
}}

.fixture-grid {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
  padding: 18px;
}}

.fixture-card {{
  position: relative;
  overflow: hidden;
  border: 1px solid #e4e8f3;
  border-radius: 22px;
  padding: 16px;
  background: linear-gradient(145deg, #ffffff 0%, #fefaff 54%, #f2fbff 100%);
  box-shadow: var(--shadow-soft);
}}

.fixture-card::before {{
  content: "";
  position: absolute;
  inset: 0 auto 0 0;
  width: 4px;
  background: linear-gradient(180deg, var(--accent-2), var(--accent), var(--sky));
}}

.fixture-top,
.fixture-datetime {{
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}}

.fixture-top {{
  margin-bottom: 12px;
}}

.fixture-division,
.fixture-round {{
  border-radius: 999px;
  padding: 4px 8px;
  font-size: 11px;
  font-weight: 800;
}}

.fixture-division {{
  color: #9d174d;
  background: #fce7f3;
}}

.fixture-round {{
  color: #5b21b6;
  background: #f3e8ff;
}}

.fixture-datetime {{
  justify-content: center;
  margin-bottom: 14px;
  color: var(--muted);
  font-size: 13px;
}}

.fixture-datetime strong {{
  color: var(--navy);
  font-size: 18px;
}}

.fixture-matchup {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  min-height: 64px;
}}

.fixture-team {{
  color: var(--strong);
  font-weight: 850;
  line-height: 1.35;
}}

.fixture-team.home {{
  text-align: right;
}}

.fixture-vs {{
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  color: #fff;
  background: linear-gradient(145deg, var(--navy), var(--accent));
  font-size: 10px;
  font-weight: 900;
  letter-spacing: 0.04em;
}}

.fixture-venue {{
  margin: 14px 0 0;
  padding-top: 10px;
  border-top: 1px dashed #dfe4ef;
  color: var(--muted);
  font-size: 12px;
  text-align: center;
}}

.fixture-venue span {{
  margin-right: 7px;
  color: var(--accent);
  font-weight: 800;
}}

.match-results {{
  display: grid;
  gap: 14px;
  padding: 18px;
}}

.match-result-card {{
  position: relative;
  overflow: hidden;
  border: 1px solid #e4e8f3;
  border-radius: 22px;
  padding: 17px;
  background: linear-gradient(145deg, #fff, #fdfaff);
  box-shadow: var(--shadow-soft);
}}

.match-result-card::before {{
  content: "";
  position: absolute;
  inset: 0 0 auto 0;
  height: 4px;
  background: linear-gradient(90deg, var(--accent-2), var(--accent), var(--sky));
}}

.match-result-card.result-hidden {{
  display: none;
}}

.match-meta {{
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 10px;
}}

.match-meta span {{
  background: #f4f2fb;
  border-radius: 999px;
  padding: 4px 8px;
}}

.match-score {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  margin-bottom: 14px;
}}

.match-score strong {{
  color: var(--navy);
  font-size: 23px;
  white-space: nowrap;
}}

.match-team {{
  font-weight: 800;
}}

.match-team.away {{
  text-align: right;
}}

.scorer-groups {{
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}}

.scorer-team {{
  border: 1px solid #edf0f6;
  background: rgba(248, 250, 255, 0.9);
  border-radius: 15px;
  padding: 12px;
}}

.scorer-team h4 {{
  margin: 0 0 7px;
  font-size: 13px;
}}

.scorer-list {{
  margin: 0;
  padding-left: 18px;
}}

.scorer-list li {{
  margin: 4px 0;
  font-size: 13px;
}}

.scorer-name {{
  font-weight: 700;
}}

.scorer-minutes {{
  color: var(--muted);
  margin-left: 8px;
}}

.no-scorers {{
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}}

.results-actions {{
  padding: 0 16px 16px;
  text-align: center;
}}

.results-toggle {{
  color: #fff;
  border-color: transparent;
  background: linear-gradient(135deg, var(--accent), #4f46e5);
  box-shadow: 0 8px 20px rgba(79, 70, 229, 0.2);
}}

.drawer {{
  display: none;
  position: fixed;
  left: 10px;
  right: 10px;
  bottom: 10px;
  max-height: 72vh;
  overflow: auto;
  background: rgba(255, 255, 255, 0.98);
  border: 1px solid #e1e5f0;
  border-radius: 26px;
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.24);
  z-index: 50;
}}

.drawer.active {{
  display: block;
}}

.drawer-head {{
  position: sticky;
  top: 0;
  background: linear-gradient(110deg, #fdf2f8, #effaff);
  padding: 14px;
  border-bottom: 1px solid var(--line);
}}

.drawer-head h3 {{
  margin: 0 0 4px;
  font-size: 17px;
}}

.drawer-head p {{
  margin: 0;
  color: var(--muted);
  font-size: 12px;
}}

.drawer-close {{
  position: absolute;
  right: 12px;
  top: 12px;
}}

.drawer-body {{
  padding: 0 14px 14px;
}}

.drawer table {{
  min-width: 0;
}}

.drawer th,
.drawer td {{
  font-size: 13px;
}}

.hidden-row {{
  display: none;
}}

.footer {{
  color: var(--muted);
  font-size: 12px;
  text-align: center;
  padding: 24px 12px 32px;
}}

.footer p {{
  margin: 4px 0;
}}

.footer-unofficial {{
  color: var(--navy);
  font-weight: 800;
}}

@media (max-width: 640px) {{
  .page {{
    padding: 9px;
  }}

  .hero {{
    grid-template-columns: 1fr;
    gap: 14px;
    border-radius: 22px;
    padding: 22px 18px 18px;
  }}

  .hero h1 {{
    font-size: 23px;
  }}

  .hero-title-break {{
    display: block;
    margin-top: 2px;
  }}

  .hero-meta {{
    min-width: 0;
    padding: 11px 13px;
  }}

  .controls {{
    top: 3px;
    margin: 8px 0 12px;
  }}

  .control-card {{
    border-radius: 18px;
    padding: 11px;
  }}

  .buttons {{
    flex-wrap: nowrap;
    overflow-x: auto;
    padding: 1px 1px 4px;
    scrollbar-width: none;
  }}

  .buttons::-webkit-scrollbar {{
    display: none;
  }}

  button {{
    flex: 0 0 auto;
    padding: 8px 11px;
    font-size: 12px;
  }}

  .section-head {{
    padding: 17px 15px;
  }}

  .section-head h2 {{
    font-size: 19px;
  }}

  table {{
    min-width: 560px;
  }}

  td {{
    font-size: 13px;
  }}

  .fixture-grid {{
    grid-template-columns: 1fr;
    gap: 11px;
    padding: 13px;
  }}

  .fixture-card {{
    border-radius: 18px;
    padding: 14px;
  }}

  .fixture-matchup {{
    gap: 8px;
  }}

  .match-results {{
    padding: 13px;
  }}

  .match-result-card {{
    border-radius: 18px;
    padding: 15px;
  }}

  .match-score {{
    grid-template-columns: 1fr;
    text-align: center;
  }}

  .match-team.away {{
    text-align: center;
  }}

  .scorer-groups {{
    grid-template-columns: 1fr;
  }}
}}
</style>
</head>
<body>
<div class="page">
  <header class="hero">
    <div class="hero-copy">
      <p class="hero-kicker">KANTO U-15 WOMEN'S FOOTBALL</p>
      <h1>2025-2026 関東U-15女子<span class="hero-title-break"> 得点ランキング</span></h1>
      <p class="hero-lead">選手の得点記録、チーム順位、次の試合をひとつの画面で見やすく。</p>
    </div>
    <div class="hero-meta">
      <span>DATA UPDATE</span>
      <p>{esc(now_local())}</p>
    </div>
  </header>

  <div class="controls">
    <div class="control-card">
      <div class="control-group">
        <span class="control-label">年度</span>
        <div class="buttons" data-control="year">
          <button type="button" data-value="2026" class="active">2026</button>
          <button type="button" data-value="2025">2025</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">区分</span>
        <div class="buttons" data-control="scope">
          <button type="button" data-value="all" class="active">総合</button>
          <button type="button" data-value="div1">1部</button>
          <button type="button" data-value="div2">2部</button>
        </div>
      </div>

      <div class="control-group">
        <span class="control-label">表示</span>
        <div class="buttons" data-control="kind">
          <button type="button" data-value="player" class="active">個人</button>
          <button type="button" data-value="team">チーム得点</button>
          <button type="button" data-value="standings" data-year-only="2026">チーム順位</button>
          <button type="button" data-value="fixtures" data-year-only="2026">次節カード</button>
          <button type="button" data-value="results" data-year-only="2026">試合別得点者</button>
        </div>
      </div>

      <div class="search-row">
        <label class="search-label" for="searchBox">選手名・チーム名で検索</label>
        <input id="searchBox" type="search" placeholder="選手名・チーム名で検索">
      </div>
    </div>
  </div>

  <main>
    {''.join(sections)}
  </main>

  <aside id="teamDrawer" class="drawer" aria-live="polite">
    <div class="drawer-head">
      <button id="drawerClose" class="drawer-close" type="button">閉じる</button>
      <h3 id="drawerTitle">チーム内ランキング</h3>
      <p id="drawerSub">チーム名をタップすると表示します。</p>
    </div>
    <div id="drawerBody" class="drawer-body"></div>
  </aside>

  <footer class="footer">
    <p class="footer-unofficial">このサイトは公開情報をもとにした非公式集計サイトです。</p>
    <p>大会主催者・各リーグ・各チームとは関係ありません。</p>
    <p>出典CSVの note は画面非表示、HTMLコメント内に保持。自動補完なし。</p>
  </footer>
</div>

<script id="rankingData" type="application/json">{html.escape(data_json, quote=False)}</script>
<script>
const DATA = JSON.parse(document.getElementById("rankingData").textContent);

const state = {{
  year: "2026",
  scope: "all",
  kind: "player",
  search: "",
  resultsExpanded: false
}};

function setActiveButtons(control, value) {{
  document.querySelectorAll(`[data-control="${{control}}"] button`).forEach(btn => {{
    btn.classList.toggle("active", btn.dataset.value === value);
  }});
}}

function currentSectionId() {{
  return `sec_${{state.year}}_${{state.kind}}_${{state.scope}}`;
}}

function normalizeSelection() {{
  if (state.year === "2025" && (state.kind === "standings" || state.kind === "fixtures" || state.kind === "results")) {{
    state.kind = "player";
  }}
  if (state.kind === "standings" && state.scope === "all") {{
    state.scope = "div1";
  }}
  if (state.kind === "fixtures") {{
    state.scope = "all";
  }}

  document.querySelectorAll('[data-year-only="2026"]').forEach(btn => {{
    btn.hidden = state.year !== "2026";
  }});
  document.querySelectorAll('[data-control="scope"] button').forEach(btn => {{
    btn.hidden =
      (state.kind === "standings" && btn.dataset.value === "all") ||
      (state.kind === "fixtures" && btn.dataset.value !== "all");
  }});
  setActiveButtons("year", state.year);
  setActiveButtons("kind", state.kind);
  setActiveButtons("scope", state.scope);
}}

function showSection() {{
  normalizeSelection();
  document.querySelectorAll(".ranking-section").forEach(sec => {{
    sec.classList.toggle("active", sec.id === currentSectionId());
  }});
  applySearch();
}}

function applySearch() {{
  const q = state.search.trim().toLowerCase();
  const active = document.getElementById(currentSectionId());
  if (!active) return;

  if (state.kind === "results") {{
    const cards = active.querySelectorAll(".match-result-card");
    cards.forEach((card, index) => {{
      const matchesSearch = !q || card.textContent.toLowerCase().includes(q);
      const withinLimit = state.resultsExpanded || index === 0 || Boolean(q);
      card.classList.toggle("result-hidden", !matchesSearch || !withinLimit);
    }});
    const toggle = active.querySelector("[data-results-toggle]");
    if (toggle) {{
      toggle.hidden = Boolean(q);
      toggle.textContent = state.resultsExpanded
        ? "直近1試合だけ表示"
        : `過去の試合を見る（${{Math.max(cards.length - 1, 0)}}試合）`;
    }}
    return;
  }}

  active.querySelectorAll("tbody tr").forEach(tr => {{
    const text = tr.textContent.toLowerCase();
    tr.classList.toggle("hidden-row", q && !text.includes(q));
  }});
}}

function scopeLabel(scope) {{
  if (scope === "div1") return "1部";
  if (scope === "div2") return "2部";
  return "総合";
}}

function playerDatasetKey(year, scope) {{
  if (scope === "div1") return `${{year}}_player_div1`;
  if (scope === "div2") return `${{year}}_player_div2`;
  return `${{year}}_player_all`;
}}

function openTeamDrawer(team) {{
  const key = playerDatasetKey(state.year, state.scope);
  const rows = DATA[key] || [];
  const filtered = rows.filter(r => (r.team || "").trim() === team);

  const drawer = document.getElementById("teamDrawer");
  const title = document.getElementById("drawerTitle");
  const sub = document.getElementById("drawerSub");
  const body = document.getElementById("drawerBody");

  title.textContent = team;
  sub.textContent = `${{state.year}} / ${{scopeLabel(state.scope)}} / チーム内個人ランキング`;

  if (!filtered.length) {{
    body.innerHTML = "<p>該当選手がありません。</p>";
  }} else {{
    const trs = filtered.map(r => `
      <tr>
        <td class="rank">${{escapeHtml(r.rank || "")}}</td>
        <td class="player">${{escapeHtml(r.player || "")}}</td>
        <td class="num">${{escapeHtml(r.goals || "")}}</td>
        <td class="num">${{escapeHtml(r.match_count || "")}}</td>
      </tr>
    `).join("");

    body.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>順位</th>
              <th>選手</th>
              <th>得点</th>
              <th>試合数</th>
            </tr>
          </thead>
          <tbody>${{trs}}</tbody>
        </table>
      </div>
    `;
  }}

  drawer.classList.add("active");
}}

function escapeHtml(s) {{
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}}

document.querySelectorAll("[data-control] button").forEach(btn => {{
  btn.addEventListener("click", () => {{
    const group = btn.parentElement.dataset.control;
    state[group] = btn.dataset.value;
    state.resultsExpanded = false;
    showSection();
  }});
}});

document.getElementById("searchBox").addEventListener("input", e => {{
  state.search = e.target.value || "";
  applySearch();
}});

document.addEventListener("click", e => {{
  const resultsToggle = e.target.closest("[data-results-toggle]");
  if (resultsToggle) {{
    state.resultsExpanded = !state.resultsExpanded;
    applySearch();
    return;
  }}
  const target = e.target.closest(".team-name");
  if (!target) return;
  const team = target.dataset.team || target.textContent.trim();
  if (team) openTeamDrawer(team);
}});

document.getElementById("drawerClose").addEventListener("click", () => {{
  document.getElementById("teamDrawer").classList.remove("active");
}});

showSection();
</script>
</body>
</html>
"""


def summarize(ds: Dataset) -> str:
    goals = sum(safe_int(r.get("goals")) for r in ds.rows)
    notes = sum(1 for r in ds.rows if (r.get("note") or "").strip())
    return f"{ds.year} {ds.kind} {ds.scope}: rows={len(ds.rows)} goals={goals} note_rows={notes} source={ds.source}"


def main() -> int:
    try:
        datasets = load_datasets()

        backup_existing(OUT_HTML)
        OUT_HTML.write_text(build_html(datasets), encoding="utf-8")

        for key in sorted(datasets):
            print(summarize(datasets[key]))

        print(f"written={OUT_HTML}")
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
