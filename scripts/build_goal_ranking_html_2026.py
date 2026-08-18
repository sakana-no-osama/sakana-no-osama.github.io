from __future__ import annotations

import csv
import html
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Sequence


INPUTS = [
    {
        "csv": "goal_ranking_2026_all.csv",
        "html": "U15RANK_2026_ALL.html",
        "page_label": "総合",
        "division_label": "ALL",
    },
    {
        "csv": "goal_ranking_2026_div1.csv",
        "html": "U15RANK_2026_KANTO1.html",
        "page_label": "関東1部",
        "division_label": "1部",
    },
    {
        "csv": "goal_ranking_2026_div2.csv",
        "html": "U15RANK_2026_KANTO2.html",
        "page_label": "関東2部",
        "division_label": "2部",
    },
]


@dataclass(frozen=True)
class RankingRow:
    rank: str
    player: str
    team: str
    division: str
    goals: str
    match_count: str
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


def require_int_text(value: str, label: str, row_no: int) -> str:
    s = normalize_text(value)
    if not s.isdigit():
        raise HoldError(f"invalid integer at row {row_no}: {label}={value}")
    return s


def read_ranking_csv(path: Path) -> List[RankingRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[RankingRow] = []

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
            rank = require_int_text(r.get("rank", ""), "rank", row_no)
            player = normalize_text(r.get("player", ""))
            team = normalize_text(r.get("team", ""))
            division = normalize_text(r.get("division", ""))
            goals = require_int_text(r.get("goals", ""), "goals", row_no)
            match_count = require_int_text(r.get("match_count", ""), "match_count", row_no)
            note = normalize_text(r.get("note", ""))

            missing = []
            if not player:
                missing.append("player")
            if not team:
                missing.append("team")
            if not division:
                missing.append("division")

            if missing:
                raise HoldError(f"blank fields at row {row_no} in {path}: {','.join(missing)}")

            rows.append(
                RankingRow(
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
        raise HoldError(f"no ranking rows found: {path}")

    return rows


def build_note_comment(rows: Sequence[RankingRow]) -> str:
    notes = []
    for r in rows:
        if r.note:
            notes.append(
                f"rank={r.rank}; player={r.player}; team={r.team}; division={r.division}; note={r.note}"
            )

    if not notes:
        return "<!-- notes: none -->"

    lines = ["<!--", "notes from source CSV:"]
    for note in notes:
        lines.append(note)
    lines.append("-->")
    return "\n".join(lines)


def build_html(rows: Sequence[RankingRow], page_label: str, division_label: str) -> str:
    updated_at = display_now()
    title = f"2026 関東U-15女子 得点ランキング - {page_label}"

    note_comment = build_note_comment(rows)

    total_players = len(rows)
    total_goals = sum(int(r.goals) for r in rows)
    top_goals = max(int(r.goals) for r in rows) if rows else 0

    body_rows = []

    for r in rows:
        body_rows.append(
            "\n".join(
                [
                    "        <tr>",
                    f"          <td class=\"rank\">{esc(r.rank)}</td>",
                    f"          <td class=\"player\">{esc(r.player)}</td>",
                    f"          <td class=\"team\">{esc(r.team)}</td>",
                    f"          <td class=\"goals\">{esc(r.goals)}</td>",
                    f"          <td class=\"matches\">{esc(r.match_count)}</td>",
                    "        </tr>",
                ]
            )
        )

    rows_html = "\n".join(body_rows)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f6f7f9;
      --card: #ffffff;
      --text: #111827;
      --muted: #6b7280;
      --line: #e5e7eb;
      --head: #0f172a;
      --accent: #2563eb;
      --rank-bg: #eff6ff;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      padding: 16px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Sans", "Yu Gothic", Meiryo, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }}

    .wrap {{
      max-width: 920px;
      margin: 0 auto;
    }}

    header {{
      margin-bottom: 14px;
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

    .summary {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 8px;
      margin: 14px 0;
    }}

    .summary-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: 10px;
      text-align: center;
    }}

    .summary-card .label {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}

    .summary-card .value {{
      display: block;
      color: var(--head);
      font-size: 18px;
      font-weight: 700;
      margin-top: 2px;
    }}

    .table-card {{
      background: var(--card);
      border: 1px solid var(--line);
      border-radius: 14px;
      overflow: hidden;
      box-shadow: 0 1px 4px rgba(15, 23, 42, 0.06);
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}

    thead {{
      background: #111827;
      color: #ffffff;
    }}

    th, td {{
      padding: 10px 8px;
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
    td.matches {{
      text-align: center;
      white-space: nowrap;
      font-weight: 700;
    }}

    td.rank {{
      color: var(--accent);
      background: var(--rank-bg);
      width: 48px;
    }}

    td.player {{
      font-weight: 700;
      min-width: 112px;
    }}

    td.team {{
      color: #374151;
      font-size: 13px;
    }}

    td.goals {{
      width: 54px;
      font-size: 16px;
    }}

    td.matches {{
      width: 62px;
      color: #374151;
    }}

    tbody tr:last-child td {{
      border-bottom: none;
    }}

    footer {{
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 12px;
    }}

    @media (max-width: 640px) {{
      body {{
        padding: 10px;
      }}

      h1 {{
        font-size: 19px;
      }}

      .summary {{
        grid-template-columns: repeat(3, 1fr);
        gap: 6px;
      }}

      .summary-card {{
        padding: 8px 4px;
      }}

      .summary-card .label {{
        font-size: 11px;
      }}

      .summary-card .value {{
        font-size: 16px;
      }}

      table {{
        font-size: 13px;
      }}

      th, td {{
        padding: 8px 6px;
      }}

      th:nth-child(5),
      td.matches {{
        display: none;
      }}

      td.team {{
        font-size: 12px;
      }}

      td.player {{
        min-width: 96px;
      }}
    }}
  </style>
</head>
<body>
  {note_comment}
  <div class="wrap">
    <header>
      <h1>{esc(title)}</h1>
      <p class="sub">更新日時: {esc(updated_at)} / 区分: {esc(division_label)}</p>
    </header>

    <section class="summary" aria-label="summary">
      <div class="summary-card">
        <span class="label">選手数</span>
        <span class="value">{total_players}</span>
      </div>
      <div class="summary-card">
        <span class="label">総得点</span>
        <span class="value">{total_goals}</span>
      </div>
      <div class="summary-card">
        <span class="label">首位得点</span>
        <span class="value">{top_goals}</span>
      </div>
    </section>

    <section class="table-card">
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
{rows_html}
        </tbody>
      </table>
    </section>

    <footer>
      <p>出典: goal_ranking_2026 CSV。note列は画面表示せずHTMLコメントに保持。</p>
    </footer>
  </div>
</body>
</html>
"""


def write_html(content: str, path: Path) -> None:
    backup_existing(path)
    path.write_text(content, encoding="utf-8")


def process_one(item: dict) -> str:
    csv_path = Path(item["csv"])
    html_path = Path(item["html"])

    rows = read_ranking_csv(csv_path)
    content = build_html(
        rows=rows,
        page_label=item["page_label"],
        division_label=item["division_label"],
    )
    write_html(content, html_path)

    goals = sum(int(r.goals) for r in rows)
    notes = sum(1 for r in rows if r.note.strip())

    return (
        f"{html_path.name}: rows={len(rows)}; goals={goals}; "
        f"note_rows={notes}; source={csv_path.name}"
    )


def main(argv: Sequence[str]) -> int:
    try:
        for item in INPUTS:
            print(process_one(item))
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
