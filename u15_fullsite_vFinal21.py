# -*- coding: utf-8 -*-
"""
Final21 (accuracy-first):
 - Use only current team_*.html as sources (fresh-only).
 - Strict row parsing, full/half width digits, OG exclusion, name-cell detection.
 - Dedup by (name, team) taking MAX goals.
 - Prefer team name from H1/H2/Title if present; fallback to filename.
 - Archive all previous Final outputs safely into _old_backup/<timestamp>.
Outputs:
  index_kngsafe_final21.html, team_totals_final21.html, team_players_final21.html, ranking_log_vFinal21.json
"""

import os, re, json, shutil, datetime, html

BASE = "/sdcard/Download/sakana-no-osama.github.io"
OUT_ALL   = os.path.join(BASE, "index_kngsafe_final21.html")
OUT_TTOT  = os.path.join(BASE, "team_totals_final21.html")
OUT_TPLAY = os.path.join(BASE, "team_players_final21.html")
LOGFILE   = os.path.join(BASE, "ranking_log_vFinal21.json")

# ---------- utils ----------
def now_tag():
    return datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

def esc(s: str) -> str:
    return html.escape(s.strip())

def read_text(p):
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def archive_old():
    pats = [
        r"index_kngsafe_final\d+\.html",
        r"team_totals_final\d+\.html",
        r"team_players_final\d+\.html",
        r"ranking_log_vFinal\d+\.json",
    ]
    moved = []
    dest = None
    for f in os.listdir(BASE):
        if any(re.fullmatch(p, f) for p in pats):
            if dest is None:
                dest = os.path.join(BASE, "_old_backup", now_tag())
                os.makedirs(dest, exist_ok=True)
            shutil.move(os.path.join(BASE, f), os.path.join(dest, f))
            moved.append(f)
    return {"moved": moved, "dest": dest}

def guess_team_from_filename(fname):
    core = re.sub(r"^team_", "", os.path.basename(fname))
    core = re.sub(r"\.html?$", "", core, flags=re.I)
    core = core.replace("_", " ")
    return core.strip()

# 全角→半角数字
ZEN2HAN = str.maketrans("０１２３４５６７８９", "0123456789")
def han_digits(s):
    return s.translate(ZEN2HAN)

# ---------- tolerant parser (rule-based strict) ----------
KANJI = r"一-龥々〆"
KATA  = r"ァ-ヴーｦ-ﾟ"
HIRA  = r"ぁ-ゖ"
ALPH  = r"A-Za-z"
NAME_RE = re.compile(rf"[{KANJI}{KATA}{HIRA}{ALPH}0-9･・\.\-　 \(\)]+")
DIGITS_TAIL = re.compile(r"(\d+)\s*$")
OG_RE = re.compile(r"(?:\bOG\b|オウン|自殺点)", re.I)
PK_PARENS = re.compile(r"（\s*PK\s*）|\(.*?PK.*?\)", re.I)
HEADER_LIKE = {"選手", "選手名", "氏名", "name"}

TD_RE = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.I|re.S)
TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.I|re.S)

def strip_html(s):
    s = re.sub(r"<[^>]+>", "", s)
    s = s.replace("&nbsp;", " ")
    s = s.replace("\u3000", " ")
    s = s.strip()
    s = han_digits(s)
    return s

def team_name_from_head(html_text, fallback):
    # Prefer H1/H2, then <title>
    m = re.search(r"<h[12][^>]*>(.*?)</h[12]>", html_text, re.I|re.S)
    if m:
        t = strip_html(m.group(1))
        if 2 <= len(t) <= 60:
            return t
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I|re.S)
    if m:
        t = strip_html(m.group(1))
        # タイトルに「チーム」「U-15」等が混ざる場合は短い名にトリム
        t = re.sub(r"(?i)u-?15.*", "", t).strip()
        if 2 <= len(t) <= 60:
            return t
    return fallback

def parse_team_file(path, drops_log):
    raw = read_text(path)
    team = team_name_from_head(raw, guess_team_from_filename(path))

    rows = TR_RE.findall(raw)
    players = []
    for tr in rows:
        cells = [strip_html(x) for x in TD_RE.findall(tr)]
        if len(cells) < 2:
            continue

        # 末尾整数（得点）
        goals = None
        for c in reversed(cells):
            m = DIGITS_TAIL.search(c)
            if m:
                try:
                    goals = int(m.group(1))
                    break
                except:
                    pass
        if goals is None:
            continue

        joined = " ".join(cells)
        if OG_RE.search(joined):
            # 完全除外
            continue

        # 名前セルを探す（数字セル以外で最初のNAME_REヒット）
        name = None
        for c in cells:
            if DIGITS_TAIL.search(c):
                continue
            if c in HEADER_LIKE:
                continue
            m = NAME_RE.search(c)
            if m:
                name = m.group(0).strip()
                break
        if not name:
            drops_log.append({"team": team, "row": cells, "reason": "no-name-cell"})
            continue

        # 注記除去
        name = PK_PARENS.sub("", name)
        name = re.sub(r"\s+", " ", name).strip()
        if not name or name in HEADER_LIKE:
            drops_log.append({"team": team, "row": cells, "reason": "header-like"})
            continue

        # 妥当性チェック（極端な得点は疑義扱いで採用、ログに記録）
        if goals > 50:
            drops_log.append({"team": team, "row": cells, "reason": f"suspect-high-goals({goals})"})

        players.append((name, goals))

    return team, players

def collect_sources():
    srcs = []
    for fn in sorted(os.listdir(BASE)):
        if fn.startswith("team_") and fn.lower().endswith(".html"):
            srcs.append(os.path.join(BASE, fn))
    return srcs

def build_rankings(src_paths):
    per_pair = {}  # (name, team) -> max goals
    drops = []
    teams_seen = set()

    for p in src_paths:
        team, plist = parse_team_file(p, drops)
        teams_seen.add(team)
        for name, g in plist:
            key = (name, team)
            if g > per_pair.get(key, 0):
                per_pair[key] = g

    # people list
    people = [(n, t, g) for (n, t), g in per_pair.items()]
    people.sort(key=lambda x: (-x[2], x[0], x[1]))

    # team totals & team players
    team_tot = {}
    team_players = {}
    for n, t, g in people:
        team_tot[t] = team_tot.get(t, 0) + g
        team_players.setdefault(t, []).append((n, g))
    for t in team_players:
        team_players[t].sort(key=lambda x: (-x[1], x[0]))

    team_rank = sorted(team_tot.items(), key=lambda x: (-x[1], x[0]))
    return people, team_rank, team_players, sorted(teams_seen), drops

# ---------- HTML ----------
CSS = """
<style>
body{font-family:sans-serif;margin:18px}
h1{font-size:20px;margin:0 0 8px}
h2{font-size:16px;margin:18px 0 6px}
small{color:#555}
table{border-collapse:collapse;width:100%;max-width:980px}
th,td{border:1px solid #ccc;padding:6px 8px;font-size:13px}
th{background:#f6f6f6}
.rank{width:56px;text-align:right}
.name{width:36%}
.team{width:42%}
.goals{width:70px;text-align:right}
.section{margin:22px 0 12px}
</style>
"""

def write_overall(people):
    lines = []
    lines.append("<html><head><meta charset='utf-8'><title>U-15 統合得点ランキング (Final21)</title>"+CSS+"</head><body>")
    lines.append("<h1>U-15 関東1部・2部 統合得点ランキング（Final21）</h1>")
    lines.append("<small>現存 team_*.html のみを入力。OG/オウン/自殺点は除外。同姓同名は別人扱い。重複行は(名前,チーム)の最大得点を採用。</small>")
    lines.append("<div class='section'></div>")
    lines.append("<table><tr><th class='rank'>順位</th><th class='name'>選手名</th><th class='team'>チーム</th><th class='goals'>得点</th></tr>")
    prev, rank = None, 0
    for i,(n,t,g) in enumerate(people,1):
        if g != prev:
            rank = i
            prev = g
        lines.append(f"<tr><td class='rank'>{rank}</td><td class='name'>{esc(n)}</td><td class='team'>{esc(t)}</td><td class='goals'>{g}</td></tr>")
    lines.append("</table>")
    lines.append(f"<p><small>出力件数：{len(people)} 名</small></p>")
    lines.append("</body></html>")
    open(OUT_ALL,"w",encoding="utf-8").write("\n".join(lines))

def write_team_totals(team_rank):
    lines = []
    lines.append("<html><head><meta charset='utf-8'><title>チーム別 合計得点 (Final21)</title>"+CSS+"</head><body>")
    lines.append("<h1>チーム別 合計得点ランキング（Final21）</h1>")
    lines.append("<table><tr><th class='rank'>順位</th><th class='team'>チーム</th><th class='goals'>合計</th></tr>")
    prev, rank = None, 0
    for i,(t,s) in enumerate(team_rank,1):
        if s != prev:
            rank = i
            prev = s
        lines.append(f"<tr><td class='rank'>{rank}</td><td class='team'>{esc(t)}</td><td class='goals'>{s}</td></tr>")
    lines.append("</table></body></html>")
    open(OUT_TTOT,"w",encoding="utf-8").write("\n".join(lines))

def write_team_players(team_players):
    lines = []
    lines.append("<html><head><meta charset='utf-8'><title>チーム別 選手ランキング (Final21)</title>"+CSS+"</head><body>")
    lines.append("<h1>チーム別 選手得点ランキング（Final21）</h1>")
    for t in sorted(team_players.keys()):
        lines.append(f"<h2>{esc(t)}</h2>")
        lines.append("<table><tr><th class='rank'>順位</th><th class='name'>選手名</th><th class='goals'>得点</th></tr>")
        prev, rank = None, 0
        for i,(n,g) in enumerate(team_players[t],1):
            if g != prev:
                rank = i
                prev = g
            lines.append(f"<tr><td class='rank'>{rank}</td><td class='name'>{esc(n)}</td><td class='goals'>{g}</td></tr>")
        lines.append("</table><div class='section'></div>")
    lines.append("</body></html>")
    open(OUT_TPLAY,"w",encoding="utf-8").write("\n".join(lines))

# ---------- main ----------
def main():
    archived = archive_old()
    srcs = collect_sources()
    if not srcs:
        print("⚠️ team_*.html が見つかりません。処理を中止しました。")
        return

    people, team_rank, team_players, teams_seen, drops = build_rankings(srcs)

    write_overall(people)
    write_team_totals(team_rank)
    write_team_players(team_players)

    log = {
        "timestamp": now_tag(),
        "sources": [os.path.basename(p) for p in srcs],
        "teams_detected": teams_seen,
        "people_count": len(people),
        "team_count": len(team_rank),
        "drops": drops[:200],        # ログ肥大防止で先頭200件
        "archived": archived
    }
    open(LOGFILE,"w",encoding="utf-8").write(json.dumps(log, ensure_ascii=False, indent=2))

    print("✅ 出力完了：")
    print("  -", OUT_ALL)
    print("  -", OUT_TTOT)
    print("  -", OUT_TPLAY)
    print("🗂️ ログ：", LOGFILE)
    if archived.get("moved"):
        print("🗄️ 旧成果物を退避：", archived["dest"])

if __name__ == "__main__":
    main()

