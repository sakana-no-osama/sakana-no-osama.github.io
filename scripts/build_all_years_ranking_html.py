from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from workflow_io import ROOT, DATA, atomic_write_text
from ranking_checks import check_matches, check_rankings
from typing import Dict, List, Sequence


OUT_HTML = ROOT / ".preview" / "index.html"
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
    return datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M:%S %Z")


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


def load_team_aliases(data_dir: Path = DATA) -> Dict[tuple[str, str], str]:
    rows = read_csv_required(data_dir / TEAM_ALIASES_CSV)
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


def load_match_result_datasets(data_dir: Path = DATA) -> Dict[str, Dataset]:
    check_matches(data_dir)
    matches = read_csv_required(data_dir / MATCH_RESULTS_CSV)
    events = read_csv_required(data_dir / GOAL_EVENTS_CSV)
    aliases = load_team_aliases(data_dir)
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
            "source_url": match.get("source_url", ""),
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


def load_datasets(data_dir: Path = DATA) -> Dict[str, Dataset]:
    check_rankings(data_dir)
    datasets: Dict[str, Dataset] = {}

    for year, files in INPUTS.items():
        for key, filename in files.items():
            path = data_dir / filename
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

    datasets.update(load_match_result_datasets(data_dir))
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
            f"<td class=\"team team-name\" role=\"button\" tabindex=\"0\" aria-haspopup=\"dialog\" data-team=\"{esc(r.get('team'))}\">{esc(r.get('team'))}</td>"
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
            f"<td class=\"team team-name\" role=\"button\" tabindex=\"0\" aria-haspopup=\"dialog\" data-team=\"{esc(r.get('team'))}\">{esc(r.get('team'))}</td>"
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
            f'<article class="fixture-card" data-date="{esc(r.get("match_date"))}">'
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
            f'<a class="source-link" href="{esc(r.get("source_url"))}" target="_blank" rel="noopener noreferrer">公式の試合情報 ↗</a>'
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
    fields = ("rank", "player", "team", "goals", "match_count")
    payload = {key: [{field: row[field] for field in fields} for row in ds.rows]
               for key, ds in datasets.items() if ds.kind == "player"}
    # Script raw-text elements do not decode HTML entities. Escape '<' as JSON.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")


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

    </div>
  </div>
  <div class="match-results">
    {build_result_cards(ds.rows)}
  </div>
  <div class="results-actions">{toggle}</div>
</section>
"""

    if ds.kind == "fixtures":
        stats = [f"<span>試合数: {len(ds.rows)}</span>"]
        return f"""
<section id="{section_id}" class="ranking-section fixture-section" data-year="{ds.year}" data-kind="{ds.kind}" data-scope="{ds.scope}">
  {note_comment(f"{ds.year}_{ds.kind}_{ds.scope}", ds.rows)}
  <div class="section-head">
    <h2>{esc(ds.year)} {esc(label_kind)}{esc(label_scope)}</h2>
    <p>保存済みの予定です。日程の変更は各試合の公式情報をご確認ください。</p>
    <div class="stats">
      {''.join(stats)}
    </div>
  </div>
  <p class="freshness-notice" data-fixture-warning hidden></p>
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
<th title="1点以上得点した試合の数">得点試合</th>
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
<th title="1点以上得点した試合の数">得点試合</th>
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
    stats = [f"<span>{'選手数' if ds.kind == 'player' else 'チーム数'}: {len(ds.rows)}</span>"]
    if goals is not None:
        stats.append(f"<span>得点: {goals}</span>")

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
    latest_record = max(row["match_date"] for row in datasets["2026_results_all"].rows)
    style_css = (ROOT / "web" / "ranking.css").read_text(encoding="utf-8")
    script_js = (ROOT / "web" / "ranking.js").read_text(encoding="utf-8")

    return f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>2025-2026 関東U-15女子 得点ランキング</title>
<style>
{style_css}
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
      <span>2026年 収録試合の最終日</span>
      <p>{esc(latest_record)}</p>
      <small>ページ生成: {esc(now_local())}</small>
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
        <div class="search-input-row"><input id="searchBox" type="search" placeholder="選手名・チーム名で検索" aria-describedby="searchStatus">
        <button id="searchClear" type="button">クリア</button></div>
        <p id="searchStatus" role="status" aria-live="polite"></p>
      </div>
    </div>
  </div>

  <main>
    <p id="emptyState" class="empty-state" hidden>該当する記録がありません。検索する名前や区分を変えてみてください。</p>
    {''.join(sections)}
  </main>

  <dialog id="teamDrawer" class="drawer" aria-labelledby="drawerTitle">
    <div class="drawer-head">
      <button id="drawerClose" class="drawer-close" type="button">閉じる</button>
      <h3 id="drawerTitle">チーム内ランキング</h3>
      <p id="drawerSub">チーム名をタップすると表示します。</p>
    </div>
    <div id="drawerBody" class="drawer-body"></div>
  </dialog>

  <footer class="footer">
    <p class="footer-unofficial">このサイトは公開情報をもとにした非公式集計サイトです。</p>
    <p>大会主催者・各リーグ・各チームとは関係ありません。</p>
    <p>得点を確認できた記録のみ集計しています。2025年の一部試合には未確認の1点があり、個人得点には含めていません。</p>
    <p>「得点試合」は1点以上得点した試合数です。</p>
  </footer>
</div>

<script id="rankingData" type="application/json">{data_json}</script>
<script>
{script_js}
</script>
</body>
</html>
"""


def summarize(ds: Dataset) -> str:
    goals = sum(safe_int(r.get("goals")) for r in ds.rows)
    notes = sum(1 for r in ds.rows if (r.get("note") or "").strip())
    return f"{ds.year} {ds.kind} {ds.scope}: rows={len(ds.rows)} goals={goals} note_rows={notes} source={ds.source}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a local preview from verified saved CSVs.")
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--output", type=Path, default=OUT_HTML)
    args = parser.parse_args()
    try:
        if args.output.resolve() == (ROOT / "index.html").resolve():
            raise HoldError("Build a preview first; public index.html requires a reviewed promotion.")
        datasets = load_datasets(args.data_dir)
        page = build_html(datasets)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(args.output, page)
        for key in sorted(datasets):
            print(summarize(datasets[key]))
        print(f"written={args.output}")
        return 0
    except (HoldError, OSError, ValueError, KeyError, csv.Error) as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
