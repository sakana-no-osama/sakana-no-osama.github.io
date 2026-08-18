from __future__ import annotations

import csv
import html
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence


OUT_HTML = "U15RANK_2025.html"

PERSONAL_INPUTS = [
    {
        "tab_id": "personal-all",
        "label": "個人総合",
        "csv": "goal_ranking_2025_all.csv",
        "kind": "personal",
    },
    {
        "tab_id": "personal-div1",
        "label": "個人1部",
        "csv": "goal_ranking_2025_div1.csv",
        "kind": "personal",
    },
    {
        "tab_id": "personal-div2",
        "label": "個人2部",
        "csv": "goal_ranking_2025_div2.csv",
        "kind": "personal",
    },
]

TEAM_INPUTS = [
    {
        "tab_id": "team-all",
        "label": "チーム総合",
        "csv": "team_ranking_2025_all.csv",
        "kind": "team",
    },
    {
        "tab_id": "team-div1",
        "label": "チーム1部",
        "csv": "team_ranking_2025_div1.csv",
        "kind": "team",
    },
    {
        "tab_id": "team-div2",
        "label": "チーム2部",
        "csv": "team_ranking_2025_div2.csv",
        "kind": "team",
    },
]

ALL_INPUTS = PERSONAL_INPUTS + TEAM_INPUTS


@dataclass(frozen=True)
class PersonalRow:
    rank: str
    player: str
    team: str
    division: str
    goals: str
    match_count: str
    note: str


@dataclass(frozen=True)
class TeamRow:
    rank: str
    team: str
    division: str
    goals: str
    scorer_count: str
    match_count: str
    top_scorer: str
    note: str


class HoldError(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def display_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def esc(value: str) -> str:
    return html.escape(value or "", quote=True)


def normalize_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def backup_existing(path: Path) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{now_stamp()}")
        path.replace(backup)
        print(f"backup={backup}")


def require_int_text(value: str, label: str, row_no: int, path: Path) -> str:
    s = normalize_text(value)
    if not s.isdigit():
        raise HoldError(f"invalid integer in {path} row {row_no}: {label}={value}")
    return s


def read_personal_csv(path: Path) -> List[PersonalRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[PersonalRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {
            "rank",
            "player",
            "team",
            "division",
            "goals",
            "match_count",
            "note",
        }

        missing_cols = required - set(reader.fieldnames or [])
        if missing_cols:
            raise HoldError(f"missing columns in {path}: {sorted(missing_cols)}")

        for row_no, r in enumerate(reader, start=2):
            rank = require_int_text(r.get("rank", ""), "rank", row_no, path)
            player = normalize_text(r.get("player", ""))
            team = normalize_text(r.get("team", ""))
            division = normalize_text(r.get("division", ""))
            goals = require_int_text(r.get("goals", ""), "goals", row_no, path)
            match_count = require_int_text(r.get("match_count", ""), "match_count", row_no, path)
            note = normalize_text(r.get("note", ""))

            missing = []
            if not player:
                missing.append("player")
            if not team:
                missing.append("team")
            if not division:
                missing.append("division")

            if missing:
                raise HoldError(f"blank fields in {path} row {row_no}: {','.join(missing)}")

            rows.append(
                PersonalRow(
                    rank=rank,
                    player=player,
                    team=team,
                    division=division,
                    goals=goals,
                    match_count=match_count,
                    note=note,
                )
            )

    if not rows:
        raise HoldError(f"no rows found: {path}")

    return rows


def read_team_csv(path: Path) -> List[TeamRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[TeamRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required = {
            "rank",
            "team",
            "division",
            "goals",
            "scorer_count",
            "match_count",
            "top_scorer",
            "note",
        }

        missing_cols = required - set(reader.fieldnames or [])
        if missing_cols:
            raise HoldError(f"missing columns in {path}: {sorted(missing_cols)}")

        for row_no, r in enumerate(reader, start=2):
            rank = require_int_text(r.get("rank", ""), "rank", row_no, path)
            team = normalize_text(r.get("team", ""))
            division = normalize_text(r.get("division", ""))
            goals = require_int_text(r.get("goals", ""), "goals", row_no, path)
            scorer_count = require_int_text(r.get("scorer_count", ""), "scorer_count", row_no, path)
            match_count = require_int_text(r.get("match_count", ""), "match_count", row_no, path)
            top_scorer = normalize_text(r.get("top_scorer", ""))
            note = normalize_text(r.get("note", ""))

            missing = []
            if not team:
                missing.append("team")
            if not division:
                missing.append("division")
            if not top_scorer:
                missing.append("top_scorer")

            if missing:
                raise HoldError(f"blank fields in {path} row {row_no}: {','.join(missing)}")

            rows.append(
                TeamRow(
                    rank=rank,
                    team=team,
                    division=division,
                    goals=goals,
                    scorer_count=scorer_count,
                    match_count=match_count,
                    top_scorer=top_scorer,
                    note=note,
                )
            )

    if not rows:
        raise HoldError(f"no rows found: {path}")

    return rows


def build_notes_comment(personal_data: Dict[str, List[PersonalRow]], team_data: Dict[str, List[TeamRow]]) -> str:
    lines = ["<!--", "notes from source CSV:"]

    count = 0

    for label, rows in personal_data.items():
        for r in rows:
            if r.note:
                count += 1
                lines.append(
                    f"[{label}] rank={r.rank}; player={r.player}; team={r.team}; division={r.division}; note={r.note}"
                )

    for label, rows in team_data.items():
        for r in rows:
            if r.note:
                count += 1
                lines.append(
                    f"[{label}] rank={r.rank}; team={r.team}; division={r.division}; note={r.note}"
                )

    if count == 0:
        lines.append("none")

    lines.append("-->")
    return "\n".join(lines)


def personal_table_html(rows: Sequence[PersonalRow]) -> str:
    body_rows = []

    for r in rows:
        body_rows.append(
            "\n".join(
                [
                    "          <tr>",
                    f"            <td class=\"rank\">{esc(r.rank)}</td>",
                    f"            <td class=\"main-name\">{esc(r.player)}</td>",
                    f"            <td class=\"team\">{esc(r.team)}</td>",
                    f"            <td class=\"goals\">{esc(r.goals)}</td>",
                    f"            <td class=\"matches\">{esc(r.match_count)}</td>",
                    "          </tr>",
                ]
            )
        )

    return "\n".join(body_rows)


def team_table_html(rows: Sequence[TeamRow]) -> str:
    body_rows = []

    for r in rows:
        body_rows.append(
            "\n".join(
                [
                    "          <tr>",
                    f"            <td class=\"rank\">{esc(r.rank)}</td>",
                    f"            <td class=\"main-name team-name\">{esc(r.team)}</td>",
                    f"            <td class=\"goals\">{esc(r.goals)}</td>",
                    f"            <td class=\"matches\">{esc(r.match_count)}</td>",
                    f"            <td class=\"scorers\">{esc(r.scorer_count)}</td>",
                    f"            <td class=\"top-scorer\">{esc(r.top_scorer)}</td>",
                    "          </tr>",
                ]
            )
        )

    return "\n".join(body_rows)


def personal_section_html(tab_id: str, label: str, rows: Sequence[PersonalRow], active: bool) -> str:
    players = len(rows)
    goals = sum(int(r.goals) for r in rows)
    top_goals = max(int(r.goals) for r in rows) if rows else 0
    active_class = " active" if active else ""

    return f"""
    <section id="{esc(tab_id)}" class="panel{active_class}">
      <div class="summary">
        <div class="summary-card">
          <span class="summary-label">選手数</span>
          <span class="summary-value">{players}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">総得点</span>
          <span class="summary-value">{goals}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">首位得点</span>
          <span class="summary-value">{top_goals}</span>
        </div>
      </div>

      <div class="table-card">
        <div class="table-title">{esc(label)}</div>
        <table>
          <thead>
            <tr>
              <th>順位</th>
              <th>選手</th>
              <th>チーム</th>
              <th>得点</th>
              <th>試合数</th>
            </tr>
          </thead>
          <tbody>
{personal_table_html(rows)}
          </tbody>
        </table>
      </div>
    </section>
"""


def team_section_html(tab_id: str, label: str, rows: Sequence[TeamRow], active: bool) -> str:
    teams = len(rows)
    goals = sum(int(r.goals) for r in rows)
    top_goals = max(int(r.goals) for r in rows) if rows else 0
    active_class = " active" if active else ""

    return f"""
    <section id="{esc(tab_id)}" class="panel{active_class}">
      <div class="summary">
        <div class="summary-card">
          <span class="summary-label">チーム数</span>
          <span class="summary-value">{teams}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">総得点</span>
          <span class="summary-value">{goals}</span>
        </div>
        <div class="summary-card">
          <span class="summary-label">首位得点</span>
          <span class="summary-value">{top_goals}</span>
        </div>
      </div>

      <div class="table-card">
        <div class="table-title">{esc(label)}</div>
        <table>
          <thead>
            <tr>
              <th>順位</th>
              <th>チーム</th>
              <th>得点</th>
              <th>試合数</th>
              <th>得点者数</th>
              <th>最多得点者</th>
            </tr>
          </thead>
          <tbody>
{team_table_html(rows)}
          </tbody>
        </table>
      </div>
    </section>
"""


def build_buttons() -> str:
    buttons = []
    for idx, item in enumerate(ALL_INPUTS):
        active = " active" if idx == 0 else ""
        buttons.append(
            f"      <button class=\"tab-button{active}\" type=\"button\" data-target=\"{esc(item['tab_id'])}\">{esc(item['label'])}</button>"
        )
    return "\n".join(buttons)


def build_html(personal_data: Dict[str, List[PersonalRow]], team_data: Dict[str, List[TeamRow]]) -> str:
    updated_at = display_now()
    note_comment = build_notes_comment(personal_data, team_data)

    sections = []

    first = True

    for item in PERSONAL_INPUTS:
        label = item["label"]
        sections.append(
            personal_section_html(
                tab_id=item["tab_id"],
                label=label,
                rows=personal_data[label],
                active=first,
            )
        )
        first = False

    for item in TEAM_INPUTS:
        label = item["label"]
        sections.append(
            team_section_html(
                tab_id=item["tab_id"],
                label=label,
                rows=team_data[label],
                active=first,
            )
        )
        first = False

    sections_html = "\n".join(sections)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>2025 関東U-15女子 得点ランキング</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --card: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #e5e7eb;
      --head: #0f172a;
      --accent: #2563eb;
      --accent-light: #eff6ff;
      --tab-bg: #e5e7eb;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 12px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}

    .wrap {{
      max-width: 1040px;
      margin: 0 auto;
    }}

    header {{
      margin-bottom: 12px;
    }}

    h1 {{
      margin: 0 0 6px;
      font-size: 22px;
      line-height: 1.25;
      color: var(--head);
    }}

    .sub {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}

    .tabs {{
      position: sticky;
      top: 0;
      z-index: 10;
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 6px;
      padding: 8px 0;
      background: var(--bg);
      margin-bottom: 8px;
    }}

    .tab-button {{
      border: 1px solid var(--line);
      background: var(--tab-bg);
      color: var(--head);
      border-radius: 999px;
      padding: 9px 8px;
      font-size: 13px;
      font-weight: 700;
      cursor: pointer;
      white-space: nowrap;
    }}

    .tab-button.active {{
      background: var(--accent);
      color: #ffffff;
      border-color: var(--accent);
    }}

    .panel {{
      display: none;
    }}

    .panel.active {{
      display: block;
    }}

    .summary {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 10px 0;
    }}

    .summary-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px 6px;
      text-align: center;
    }}

    .summary-label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}

    .summary-value {{
      display: block;
      color: var(--head);
      font-size: 18px;
      font-weight: 800;
      margin-top: 2px;
    }}

    .table-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
    }}

    .table-title {{
      padding: 10px 12px;
      background: #111827;
      color: #ffffff;
      font-size: 14px;
      font-weight: 800;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}

    thead {{
      background: #f9fafb;
      color: var(--head);
    }}

    th, td {{
      padding: 9px 7px;
      border-bottom: 1px solid var(--line);
      vertical-align: middle;
    }}

    th {{
      text-align: left;
      font-size: 12px;
      white-space: nowrap;
    }}

    td.rank,
    td.goals,
    td.matches,
    td.scorers {{
      text-align: center;
      white-space: nowrap;
      font-weight: 800;
    }}

    td.rank {{
      color: var(--accent);
      background: var(--accent-light);
      width: 46px;
    }}

    td.main-name {{
      font-weight: 800;
      min-width: 100px;
    }}

    td.team {{
      color: #374151;
      font-size: 13px;
    }}

    td.team-name {{
      color: #111827;
    }}

    td.goals {{
      width: 48px;
      font-size: 16px;
    }}

    td.matches,
    td.scorers {{
      width: 58px;
      color: #374151;
    }}

    td.top-scorer {{
      color: #374151;
      font-size: 13px;
      min-width: 120px;
    }}

    tbody tr:last-child td {{
      border-bottom: none;
    }}

    footer {{
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 12px;
    }}

    @media (max-width: 720px) {{
      body {{
        padding: 10px;
      }}

      h1 {{
        font-size: 19px;
      }}

      .tabs {{
        grid-template-columns: repeat(2, 1fr);
      }}

      .tab-button {{
        font-size: 13px;
        padding: 9px 6px;
      }}

      .summary {{
        gap: 6px;
      }}

      .summary-card {{
        padding: 8px 4px;
      }}

      .summary-label {{
        font-size: 11px;
      }}

      .summary-value {{
        font-size: 16px;
      }}

      table {{
        font-size: 13px;
      }}

      th, td {{
        padding: 8px 6px;
      }}

      td.team,
      td.top-scorer {{
        font-size: 12px;
      }}

      td.main-name {{
        min-width: 92px;
      }}

      .panel[id^="personal"] th:nth-child(5),
      .panel[id^="personal"] td.matches {{
        display: none;
      }}

      .panel[id^="team"] th:nth-child(5),
      .panel[id^="team"] td.scorers {{
        display: none;
      }}
    }}

    @media (max-width: 420px) {{
      .tabs {{
        grid-template-columns: repeat(2, 1fr);
      }}

      .panel[id^="team"] th:nth-child(6),
      .panel[id^="team"] td.top-scorer {{
        display: none;
      }}
    }}
  </style>
</head>
<body>
  {note_comment}
  <div class="wrap">
    <header>
      <h1>2025 関東U-15女子 得点ランキング</h1>
      <p class="sub">更新日時: {esc(updated_at)} / 個人・チーム別をタブ切替</p>
    </header>

    <nav class="tabs" aria-label="ranking tabs">
{build_buttons()}
    </nav>

{sections_html}

    <footer>
      <p>出典: goal_ranking_2025 / team_ranking_2025 CSV。note列は画面表示せずHTMLコメントに保持。</p>
    </footer>
  </div>

  <script>
    const buttons = document.querySelectorAll(".tab-button");
    const panels = document.querySelectorAll(".panel");

    buttons.forEach((button) => {{
      button.addEventListener("click", () => {{
        const target = button.dataset.target;

        buttons.forEach((b) => b.classList.remove("active"));
        panels.forEach((p) => p.classList.remove("active"));

        button.classList.add("active");
        const panel = document.getElementById(target);
        if (panel) {{
          panel.classList.add("active");
        }}
      }});
    }});
  </script>
</body>
</html>
"""


def write_html(content: str, path: Path) -> None:
    backup_existing(path)
    path.write_text(content, encoding="utf-8")


def summarize_personal(label: str, rows: Sequence[PersonalRow]) -> str:
    return f"{label}: rows={len(rows)}; goals={sum(int(r.goals) for r in rows)}; note_rows={sum(1 for r in rows if r.note)}"


def summarize_team(label: str, rows: Sequence[TeamRow]) -> str:
    return f"{label}: rows={len(rows)}; goals={sum(int(r.goals) for r in rows)}; note_rows={sum(1 for r in rows if r.note)}"


def main(argv: Sequence[str]) -> int:
    try:
        personal_data: Dict[str, List[PersonalRow]] = {}
        team_data: Dict[str, List[TeamRow]] = {}

        for item in PERSONAL_INPUTS:
            label = item["label"]
            personal_data[label] = read_personal_csv(Path(item["csv"]))

        for item in TEAM_INPUTS:
            label = item["label"]
            team_data[label] = read_team_csv(Path(item["csv"]))

        content = build_html(personal_data, team_data)
        write_html(content, Path(OUT_HTML))

        for item in PERSONAL_INPUTS:
            label = item["label"]
            print(summarize_personal(label, personal_data[label]))

        for item in TEAM_INPUTS:
            label = item["label"]
            print(summarize_team(label, team_data[label]))

        print(f"written={OUT_HTML}")
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
