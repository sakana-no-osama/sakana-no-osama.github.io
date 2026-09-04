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


def dataset_json(datasets: Dict[str, Dataset]) -> str:
    payload = {}
    for key, ds in datasets.items():
        payload[key] = ds.rows
    return json.dumps(payload, ensure_ascii=False)


def build_section(ds: Dataset) -> str:
    label_scope = {"all": "総合", "div1": "1部", "div2": "2部"}[ds.scope]
    label_kind = {"player": "個人", "team": "チーム得点", "standings": "チーム順位", "fixtures": "次節カード"}[ds.kind]
    section_id = f"sec_{ds.year}_{ds.kind}_{ds.scope}"

    goals = sum(safe_int(r.get("goals")) for r in ds.rows) if ds.kind in {"player", "team"} else None
    note_rows = sum(1 for r in ds.rows if (r.get("note") or "").strip())

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
  search: ""
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
  if (state.year === "2025" && (state.kind === "standings" || state.kind === "fixtures")) {{
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
    showSection();
  }});
}});

document.getElementById("searchBox").addEventListener("input", e => {{
  state.search = e.target.value || "";
  applySearch();
}});

document.addEventListener("click", e => {{
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
