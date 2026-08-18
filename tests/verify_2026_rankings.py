import csv
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"

def goals(name):
    rows = list(csv.DictReader(open(DATA / name, encoding="utf-8-sig")))
    total = sum(int(r.get("goals") or 0) for r in rows if (r.get("goals") or "").isdigit())
    return len(rows), total

pairs = [
    ("ALL", "goal_ranking_2026_all.csv", "team_ranking_2026_all.csv"),
    ("DIV1", "goal_ranking_2026_div1.csv", "team_ranking_2026_div1.csv"),
    ("DIV2", "goal_ranking_2026_div2.csv", "team_ranking_2026_div2.csv"),
]

for f in [
    "goal_events_2026.csv",
    "goal_ranking_2026_all.csv",
    "goal_ranking_2026_div1.csv",
    "goal_ranking_2026_div2.csv",
    "team_ranking_2026_all.csv",
    "team_ranking_2026_div1.csv",
    "team_ranking_2026_div2.csv",
]:
    r, g = goals(f)
    print(f, "rows=", r, "goals=", g)

ok = True
print()

for label, pf, tf in pairs:
    _, pg = goals(pf)
    _, tg = goals(tf)
    print(label, "player_goals=", pg, "team_goals=", tg)
    if pg != tg:
        ok = False

event_goals = goals("goal_events_2026.csv")[1]
rank_all_goals = goals("goal_ranking_2026_all.csv")[1]
team_all_goals = goals("team_ranking_2026_all.csv")[1]

print()
print("event_goals=", event_goals)
print("rank_all_goals=", rank_all_goals)
print("team_all_goals=", team_all_goals)

print("VERDICT=PASS" if ok and event_goals == rank_all_goals == team_all_goals else "VERDICT=HOLD")
