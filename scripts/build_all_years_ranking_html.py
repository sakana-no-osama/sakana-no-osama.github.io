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


def build_fixture_table_rows(rows: Sequence[dict]) -> str:
    out = []
    for r in rows:
        out.append(
            "<tr>"
            f"<td>{esc(r.get('division'))}</td>"
            f"<td>{esc(r.get('section'))}</td>"
            f"<td>{esc(r.get('match_date'))}</td>"
            f"<td>{esc(r.get('kickoff'))}</td>"
            f"<td class=\"team\">{esc(r.get('home_team'))}</td>"
            f"<td class=\"team\">{esc(r.get('away_team'))}</td>"
            f"<td>{esc(r.get('venue'))}</td>"
            "</tr>"
        )
    return "\n".join(out)


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
    else:
        header = """
<thead>
<tr>
<th>部</th><th>節</th><th>日付</th><th>開始</th>
<th>ホーム</th><th>アウェイ</th><th>会場</th>
</tr>
</thead>
"""
        body = build_fixture_table_rows(ds.rows)
        helper = "CSVで確認済みの次節カードです。"

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
  --bg: #f5f7fb;
  --card: #ffffff;
  --text: #172033;
  --muted: #64748b;
  --line: #dbe3ef;
  --strong: #0f172a;
  --accent: #2563eb;
  --accent-soft: #dbeafe;
  --shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
}}

* {{
  box-sizing: border-box;
}}

body {{
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  line-height: 1.5;
}}

.page {{
  max-width: 1120px;
  margin: 0 auto;
  padding: 16px;
}}

.hero {{
  background: linear-gradient(135deg, #0f172a, #1d4ed8);
  color: #fff;
  border-radius: 22px;
  padding: 20px;
  box-shadow: var(--shadow);
}}

.hero h1 {{
  margin: 0 0 8px;
  font-size: 22px;
  line-height: 1.25;
}}

.hero p {{
  margin: 4px 0;
  color: #e5eefc;
  font-size: 13px;
}}

.controls {{
  position: sticky;
  top: 0;
  z-index: 20;
  margin: 14px 0;
  background: rgba(245, 247, 251, 0.92);
  backdrop-filter: blur(10px);
  padding: 10px 0;
}}

.control-card {{
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 18px;
  padding: 12px;
  box-shadow: var(--shadow);
}}

.control-group {{
  margin-bottom: 10px;
}}

.control-label {{
  display: block;
  font-size: 12px;
  color: var(--muted);
  margin-bottom: 6px;
  font-weight: 700;
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
  padding: 8px 11px;
  border-radius: 999px;
  font-weight: 700;
  font-size: 13px;
}}

button.active {{
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}}

.search-row {{
  display: flex;
  gap: 8px;
}}

input[type="search"] {{
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 10px 12px;
  font-size: 15px;
}}

.ranking-section {{
  display: none;
  background: var(--card);
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: var(--shadow);
  overflow: hidden;
  margin-bottom: 16px;
}}

.ranking-section.active {{
  display: block;
}}

.section-head {{
  padding: 16px;
  border-bottom: 1px solid var(--line);
}}

.section-head h2 {{
  margin: 0 0 6px;
  font-size: 19px;
}}

.section-head p {{
  margin: 0;
  color: var(--muted);
  font-size: 13px;
}}

.stats {{
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 10px;
}}

.stats span {{
  background: #f1f5f9;
  border-radius: 999px;
  padding: 5px 8px;
  font-size: 12px;
  color: #334155;
}}

.table-wrap {{
  overflow-x: auto;
}}

table {{
  width: 100%;
  border-collapse: collapse;
  min-width: 620px;
}}

th {{
  background: #f8fafc;
  color: #334155;
  font-size: 12px;
  text-align: left;
  padding: 10px 8px;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}}

td {{
  padding: 10px 8px;
  border-bottom: 1px solid #edf2f7;
  font-size: 14px;
  vertical-align: top;
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
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
}}

.match-results {{
  display: grid;
  gap: 12px;
  padding: 16px;
}}

.match-result-card {{
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px;
  background: #fff;
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
  background: #f1f5f9;
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
  font-size: 20px;
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
  background: #f8fafc;
  border-radius: 12px;
  padding: 10px;
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
  color: var(--accent);
  border-color: var(--accent);
}}

.drawer {{
  display: none;
  position: fixed;
  left: 10px;
  right: 10px;
  bottom: 10px;
  max-height: 72vh;
  overflow: auto;
  background: #fff;
  border: 1px solid var(--line);
  border-radius: 22px;
  box-shadow: 0 18px 50px rgba(15, 23, 42, 0.24);
  z-index: 50;
}}

.drawer.active {{
  display: block;
}}

.drawer-head {{
  position: sticky;
  top: 0;
  background: #fff;
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
  padding: 18px 0 26px;
}}

@media (max-width: 640px) {{
  .page {{
    padding: 10px;
  }}

  .hero {{
    border-radius: 18px;
    padding: 16px;
  }}

  .hero h1 {{
    font-size: 19px;
  }}

  button {{
    padding: 8px 10px;
    font-size: 12px;
  }}

  table {{
    min-width: 560px;
  }}

  td {{
    font-size: 13px;
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
    <h1>2025-2026 関東U-15女子 得点ランキング</h1>
    <p>年度・区分・表示種別を切り替えて閲覧できます。</p>
    <p>更新日時: {esc(now_local())}</p>
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
    出典CSVの note は画面非表示、HTMLコメント内に保持。自動補完なし。
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
