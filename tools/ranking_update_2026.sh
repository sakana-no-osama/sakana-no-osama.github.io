#!/usr/bin/env bash
set -euo pipefail

ROOT="/storage/emulated/0/Documents"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="_backup_ranking_update_${STAMP}"

echo "========================================"
echo "2026 関東U-15女子 得点ランキング更新"
echo "START: ${STAMP}"
echo "ROOT: ${ROOT}"
echo "========================================"

required_files=(
  "discover_match_sources_2026.py"
  "build_matches_2026_from_sources.py"
  "build_goal_events_2026.py"
  "build_goal_ranking_2026.py"
  "build_goal_ranking_html_2026.py"
)

echo "[1/8] 事前チェック: 必須スクリプト確認"
for f in "${required_files[@]}"; do
  if [ ! -f "$f" ]; then
    echo "FAIL: missing required script: $f"
    exit 1
  fi
done

echo "[2/8] 事前チェック: py_compile"
python -m py_compile discover_match_sources_2026.py
python -m py_compile build_matches_2026_from_sources.py
python -m py_compile build_goal_events_2026.py
python -m py_compile build_goal_ranking_2026.py
python -m py_compile build_goal_ranking_html_2026.py

echo "[3/8] バックアップ作成"
mkdir -p "$BACKUP_DIR"

backup_targets=(
  "match_sources_2026.csv"
  "matches_2026.csv"
  "matches_2026_played.csv"
  "goal_events_2026.csv"
  "goal_ranking_2026_all.csv"
  "goal_ranking_2026_div1.csv"
  "goal_ranking_2026_div2.csv"
  "U15RANK_2026_ALL.html"
  "U15RANK_2026_KANTO1.html"
  "U15RANK_2026_KANTO2.html"
)

for f in "${backup_targets[@]}"; do
  if [ -f "$f" ]; then
    cp "$f" "$BACKUP_DIR/"
  fi
done

echo "backup_dir=${BACKUP_DIR}"

echo "[4/8] 最新試合URL取得: match_sources_2026.csv"
python discover_match_sources_2026.py

echo "[5/8] 試合マスター更新: matches_2026.csv"
python build_matches_2026_from_sources.py

echo "[6/8] played試合だけ抽出: matches_2026_played.csv"
python - <<'PY'
import csv
from pathlib import Path

src = Path("matches_2026.csv")
dst = Path("matches_2026_played.csv")

if not src.exists():
    raise SystemExit("FAIL: matches_2026.csv not found")

rows = list(csv.DictReader(src.open(encoding="utf-8-sig")))
if not rows:
    raise SystemExit("FAIL: matches_2026.csv has no rows")

played = [r for r in rows if (r.get("status") or "").strip() == "played"]

if not played:
    raise SystemExit("FAIL: no played rows found")

with dst.open("w", encoding="utf-8-sig", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(played)

print(f"played_rows={len(played)}")
print("written=matches_2026_played.csv")
PY

echo "[7/8] 得点イベント・ランキング・HTML生成"
python build_goal_events_2026.py
python build_goal_ranking_2026.py
python build_goal_ranking_html_2026.py

echo "[8/8] 最低限の検証"
python - <<'PY'
import csv
from collections import Counter
from pathlib import Path

def read_csv(path):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"FAIL: missing file: {path}")
    return list(csv.DictReader(p.open(encoding="utf-8-sig")))

matches = read_csv("matches_2026.csv")
played = read_csv("matches_2026_played.csv")
events = read_csv("goal_events_2026.csv")
rank_all = read_csv("goal_ranking_2026_all.csv")
rank_d1 = read_csv("goal_ranking_2026_div1.csv")
rank_d2 = read_csv("goal_ranking_2026_div2.csv")

html_files = [
    "U15RANK_2026_ALL.html",
    "U15RANK_2026_KANTO1.html",
    "U15RANK_2026_KANTO2.html",
]
for fn in html_files:
    if not Path(fn).exists():
        raise SystemExit(f"FAIL: missing html: {fn}")

status_counts = Counter((r.get("status") or "").strip() for r in matches)
division_counts = Counter((r.get("division") or "").strip() for r in matches)

blank_played_home = sum(1 for r in played if not (r.get("home_team") or "").strip())
blank_played_away = sum(1 for r in played if not (r.get("away_team") or "").strip())
blank_played_score = sum(
    1 for r in played
    if not (r.get("home_score") or "").strip()
    or not (r.get("away_score") or "").strip()
)

expected_goals = sum(
    int(r["home_score"]) + int(r["away_score"])
    for r in played
)

event_goals = sum(
    int(r["goals"])
    for r in events
    if (r.get("goals") or "").isdigit()
)

rank_all_goals = sum(int(r["goals"]) for r in rank_all)
rank_d1_goals = sum(int(r["goals"]) for r in rank_d1)
rank_d2_goals = sum(int(r["goals"]) for r in rank_d2)

blank_event_player = sum(1 for r in events if not (r.get("player") or "").strip())
score_mismatch_rows = sum(1 for r in events if "score_mismatch" in (r.get("note") or ""))

print("---- VERIFY SUMMARY ----")
print("matches_rows=", len(matches))
print("division_counts=", division_counts)
print("status_counts=", status_counts)
print("played_rows=", len(played))
print("blank_played_home=", blank_played_home)
print("blank_played_away=", blank_played_away)
print("blank_played_score=", blank_played_score)
print("expected_goals_from_played=", expected_goals)
print("event_rows=", len(events))
print("event_goals=", event_goals)
print("blank_event_player=", blank_event_player)
print("score_mismatch_rows=", score_mismatch_rows)
print("ranking_all_players=", len(rank_all))
print("ranking_all_goals=", rank_all_goals)
print("ranking_div1_goals=", rank_d1_goals)
print("ranking_div2_goals=", rank_d2_goals)

errors = []

if blank_played_home != 0:
    errors.append("blank_played_home not zero")
if blank_played_away != 0:
    errors.append("blank_played_away not zero")
if blank_played_score != 0:
    errors.append("blank_played_score not zero")
if blank_event_player != 0:
    errors.append("blank_event_player not zero")
if score_mismatch_rows != 0:
    errors.append("score_mismatch_rows not zero")
if expected_goals != event_goals:
    errors.append("expected_goals != event_goals")
if event_goals != rank_all_goals:
    errors.append("event_goals != ranking_all_goals")
if rank_d1_goals + rank_d2_goals != rank_all_goals:
    errors.append("div1 + div2 != all")

if errors:
    print("VERDICT=HOLD")
    for e in errors:
        print("HOLD_REASON=", e)
    raise SystemExit(2)

print("VERDICT=PASS")
PY

echo "========================================"
echo "更新完了"
echo "HTML確認用:"
echo "python -m http.server 8000"
echo "http://127.0.0.1:8000/U15RANK_2026_ALL.html"
echo "http://127.0.0.1:8000/U15RANK_2026_KANTO1.html"
echo "http://127.0.0.1:8000/U15RANK_2026_KANTO2.html"
echo "========================================"
