# -*- coding: utf-8 -*-
"""
U-15 関東 1部・2部 統合得点ランキング生成 (Final22)
KNGルール対応:
- 旧成果を _old_backup/<timestamp>/ に自動退避
- team_*.html を厳密抽出して集計（OG/オウンゴール除外）
- (name, team) 単位で集計 → 同姓同名は「最大得点のみ採用」
  * 同点で複数チームにまたがる場合は両方残し、表示名に（チーム名）を付記
- 出力:
  index_kngsafe_final22.html     … 統合個人ランキング
  team_players_final22.html      … チーム別（選手）ランキング
  team_totals_final22.html       … チーム合計得点ランキング
  ranking_log_vFinal22.json      … ログ
- 依存: 標準ライブラリのみ（re, os, json, datetime, html）
"""
import os, re, json, shutil
from datetime import datetime
import html as pyhtml

BASE = "/sdcard/Download/sakana-no-osama.github.io"
OUT_MAIN = os.path.join(BASE, "index_kngsafe_final22.html")
OUT_TEAM_PLAYERS = os.path.join(BASE, "team_players_final22.html")
OUT_TEAM_TOTALS = os.path.join(BASE, "team_totals_final22.html")
LOG = os.path.join(BASE, "ranking_log_vFinal22.json")

# ----------------------- 共通ユーティリティ -----------------------
ZEN2HAN = str.maketrans({
    "０":"0","１":"1","２":"2","３":"3","４":"4","５":"5","６":"6","７":"7","８":"8","９":"9",
    "　":" ","（":"(", "）":")", "，":",", "：":":", "．":".", "・":"･"
})
OG_WORDS = {"OG","ＯＧ","オウンゴール","ｵｳﾝｺﾞｰﾙ"}

def norm_txt(s: str) -> str:
    s = s.strip()
    s = pyhtml.unescape(s)
    s = s.translate(ZEN2HAN)
    s = re.sub(r"\s+", " ", s)
    # 括弧内の注記（PK等）は除去
    s = re.sub(r"\((?:PK|pk|ＰＫ|OG|OG\?|own|オウン).*?\)", "", s)
    return s.strip()

def is_og(name: str) -> bool:
    t = norm_txt(name).upper()
    for w in OG_WORDS:
        if w in t:
            return True
    return False

def read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except:
        # 一部エディタ保存の謎エンコードに耐える
        with open(path, "r", encoding="cp932", errors="ignore") as f:
            return f.read()

def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)

# ----------------------- 旧成果の退避 -----------------------
def backup_old_outputs():
    pats = [
        r"index_kngsafe_final\d+\.html",
        r"team_players_final\d+\.html",
        r"team_totals_final\d+\.html",
        r"ranking_log_vFinal\d+\.json",
        r"u15_fullsite_vFinal\d+\.py",
        r"x_kngsafe_final\d+\.html",  # 念のため
    ]
    targets = []
    for f in os.listdir(BASE):
        for p in pats:
            if re.fullmatch(p, f):
                targets.append(f); break
    if not targets: 
        return {"moved": []}
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(BASE, "_old_backup", ts)
    ensure_dir(dest)
    moved = []
    for f in targets:
        src = os.path.join(BASE, f)
        dst = os.path.join(dest, f)
        try:
            shutil.move(src, dst)
            moved.append(f)
        except Exception as e:
            pass
    # ログも残す
    with open(os.path.join(dest, "cleanup_log.json"), "w", encoding="utf-8") as w:
        json.dump({"moved": moved, "time": ts}, w, ensure_ascii=False, indent=2)
    return {"moved": moved, "dest": dest}

# ----------------------- HTML 解析（寛容だが厳密） -----------------------
def guess_team_name(html_text: str, filename: str) -> str:
    # <h1> or <h2> or <title> からチーム名の候補を拾う
    for tag in ("h1","h2","title"):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html_text, re.I|re.S)
        if m:
            t = norm_txt(re.sub("<.*?>","",m.group(1)))
            # 明らかなノイズ除去
            t = re.sub(r"(チーム別.*ランキング|U-?15|女子|ランキング|Final\d+)", "", t, flags=re.I).strip(" -|")
            if t:
                return t
    # ファイル名から推測 (team_xxx.html → xxx をそれっぽく)
    base = os.path.basename(filename)
    m = re.match(r"team_(.+?)\.html$", base, re.I)
    if m:
        t = norm_txt(m.group(1))
        t = t.replace("_"," ").replace("-", " ").strip()
        return t
    return "（チーム名不明）"

def parse_players_from_team(html_text: str):
    """
    代表的パターンを全て拾う:
      A) <tr> [順位] <td>名前</td> [<td>チーム</td>] <td>得点</td>
      B) <tr><td>名前</td><td>得点</td>
      C) <li>名前 - 3</li> / <li>名前(3)</li>
    """
    players = []

    # 表の各行（タグ除去しながら拾う）
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html_text, re.I|re.S)
    for row in rows:
        # セルを抜く
        tds = re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", row, re.I|re.S)
        cells = [norm_txt(re.sub("<.*?>","",c)) for c in tds if norm_txt(re.sub("<.*?>","",c))]
        if not cells:
            continue

        # A/B：セルの中に整数が1つだけあり、他が名前等
        nums = [c for c in cells if re.fullmatch(r"\d{1,3}", c)]
        if nums:
            goal = None
            name = None
            team = None

            # 末尾が得点になりがち
            if re.fullmatch(r"\d{1,3}", cells[-1]):
                goal = int(cells[-1])
                # 名前は最初に「文字列だけのセル」を優先
                cand = [c for c in cells[:-1] if not re.fullmatch(r"\d{1,3}", c)]
                if cand:
                    name = cand[0]
                    # チーム名が入っていそうなら2番目以降に
                    if len(cand) >= 2:
                        team = cand[1]
                else:
                    continue
            # Aのバリエーション： [順位, 名前, チーム, 得点]
            elif len(cells) >= 4 and re.fullmatch(r"\d{1,3}", cells[0]) and re.fullmatch(r"\d{1,3}", cells[-1]):
                goal = int(cells[-1])
                name = cells[1]
                team = cells[2] if len(cells) >= 4 else None

            # フィルタ
            if name and goal is not None and not is_og(name):
                players.append( (name, team, goal) )
            continue

    # C) <li>系
    lis = re.findall(r"<li[^>]*>(.*?)</li>", html_text, re.I|re.S)
    for li in lis:
        s = norm_txt(re.sub("<.*?>","",li))
        # "名前 (3)" or "名前 - 3"
        m = re.match(r"(.+?)[\s\-]*\(?(\d{1,3})\)?$", s)
        if m:
            name = norm_txt(m.group(1))
            goal = int(m.group(2))
            if not is_og(name):
                players.append( (name, None, goal) )

    return players

# ----------------------- 集計ロジック -----------------------
def build_data():
    used_files = []
    per_name_team = {}  # key: (name, team) -> goals
    issues = {"file_errors": [], "parse_empty": [], "files": 0}

    for f in sorted(os.listdir(BASE)):
        if not re.fullmatch(r"team_.*?\.html", f, re.I):
            continue
        path = os.path.join(BASE, f)
        try:
            txt = read_file(path)
        except Exception as e:
            issues["file_errors"].append(f)
            continue

        team_guess = guess_team_name(txt, f)
        players = parse_players_from_team(txt)
        if not players:
            issues["parse_empty"].append(f)
            continue

        for name, team_in_row, g in players:
            team = norm_txt(team_in_row or team_guess or "")
            key = (name, team)
            per_name_team[key] = max(per_name_team.get(key, 0), int(g))

        used_files.append(f)
        issues["files"] += 1

    # name単位で最大得点採用（同点複数チームはすべて残す）
    by_name = {}
    for (name, team), g in per_name_team.items():
        by_name.setdefault(name, []).append((team, g))
    final_entries = []  # (name, team, g, display_name)
    for name, items in by_name.items():
        max_g = max(g for _, g in items)
        top = [(team, g) for team, g in items if g == max_g]
        if len(top) == 1:
            team, g = top[0]
            display = name
            final_entries.append( (name, team, g, display) )
        else:
            # 複数チーム同点 → 表示名に（チーム名）
            for team, g in top:
                display = f"{name}（{team}）" if team else name
                final_entries.append( (name, team, g, display) )

    # 並べ替え（得点 desc, 表示名）
    final_entries.sort(key=lambda x: (-x[2], x[3]))

    # チーム別（選手）
    by_team = {}
    for name, team, g, disp in final_entries:
        t = team or "（チーム不明）"
        by_team.setdefault(t, []).append((disp, g))
    for t in by_team:
        by_team[t].sort(key=lambda x: (-x[1], x[0]))

    # チーム合計
    team_tot = {}
    for name, team, g, disp in final_entries:
        t = team or "（チーム不明）"
        team_tot[t] = team_tot.get(t, 0) + g
    team_rank = sorted(team_tot.items(), key=lambda x: (-x[1], x[0]))

    return {
        "entries": final_entries,
        "by_team": by_team,
        "team_rank": team_rank,
        "issues": issues,
        "used_files": used_files,
        "count_players": len(final_entries)
    }

# ----------------------- HTML 出力 -----------------------
STYLE = """
<style>
body{font-family:sans-serif;margin:20px;}
h1,h2{margin:6px 0;}
table{border-collapse:collapse;width:100%;max-width:1200px;}
th,td{border:1px solid #ccc;padding:6px 8px;text-align:left;vertical-align:top;}
th{background:#f6f6f6;}
small{color:#666;}
section{margin:18px 0;}
.ranknum{width:54px;text-align:right;}
.goal{width:60px;text-align:right;}
.team{min-width:200px;}
</style>
"""

def render_main(entries):
    rows = []
    last_g = None
    rank = 0
    place = 0
    for name, team, g, disp in entries:
        place += 1
        if g != last_g:
            rank = place
            last_g = g
        rows.append(
            f"<tr><td class='ranknum'>{rank}</td><td>{pyhtml.escape(disp)}</td>"
            f"<td class='team'>{pyhtml.escape(team or '')}</td>"
            f"<td class='goal'>{g}</td></tr>"
        )
    html = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>U-15 関東統合得点ランキング（Final22）</title>",
        STYLE,
        "</head><body>",
        "<h1>U-15 関東1部・2部 統合得点ランキング（Final22）</h1>",
        "<p><small>同一選手名は最大得点採用。異チーム同名は（チーム名）表記。OGは除外。</small></p>",
        "<table><thead><tr><th class='ranknum'>順位</th><th>選手名</th><th class='team'>チーム</th><th class='goal'>得点</th></tr></thead><tbody>",
        "\n".join(rows),
        "</tbody></table>",
        "<p><small>自動生成: KNG SAFE Final22</small></p>",
        "</body></html>"
    ]
    return "\n".join(html)

def render_team_players(by_team):
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>チーム別（選手）ランキング（Final22）</title>",
        STYLE, "</head><body>",
        "<h1>チーム別（選手）ランキング（Final22）</h1>",
        "<p><small>各チームの所属選手（同姓同名は最大得点・同点は併記）。</small></p>"
    ]
    for team in sorted(by_team.keys()):
        parts.append(f"<section><h2>{pyhtml.escape(team)}</h2>")
        parts.append("<table><thead><tr><th>#</th><th>選手</th><th class='goal'>得点</th></tr></thead><tbody>")
        for i,(disp,g) in enumerate(by_team[team],1):
            parts.append(f"<tr><td class='ranknum'>{i}</td><td>{pyhtml.escape(disp)}</td><td class='goal'>{g}</td></tr>")
        parts.append("</tbody></table></section>")
    parts.append("</body></html>")
    return "\n".join(parts)

def render_team_totals(team_rank):
    rows = []
    for i,(team,total) in enumerate(team_rank,1):
        rows.append(f"<tr><td class='ranknum'>{i}</td><td class='team'>{pyhtml.escape(team)}</td><td class='goal'>{total}</td></tr>")
    html = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        "<title>チーム合計得点ランキング（Final22）</title>",
        STYLE, "</head><body>",
        "<h1>チーム合計得点ランキング（Final22）</h1>",
        "<table><thead><tr><th class='ranknum'>順位</th><th class='team'>チーム</th><th class='goal'>合計</th></tr></thead><tbody>",
        "\n".join(rows),
        "</tbody></table></body></html>"
    ]
    return "\n".join(html)

# ----------------------- main -----------------------
def main():
    ensure_dir(BASE)
    backup_info = backup_old_outputs()

    data = build_data()

    with open(OUT_MAIN, "w", encoding="utf-8") as w:
        w.write(render_main(data["entries"]))
    with open(OUT_TEAM_PLAYERS, "w", encoding="utf-8") as w:
        w.write(render_team_players(data["by_team"]))
    with open(OUT_TEAM_TOTALS, "w", encoding="utf-8") as w:
        w.write(render_team_totals(data["team_rank"]))

    out = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "players": data["count_players"],
        "used_files": data["used_files"],
        "issues": data["issues"],
        "backup": backup_info,
        "outputs": [OUT_MAIN, OUT_TEAM_PLAYERS, OUT_TEAM_TOTALS]
    }
    with open(LOG, "w", encoding="utf-8") as w:
        json.dump(out, w, ensure_ascii=False, indent=2)

    print("✅ 出力:", OUT_MAIN)
    print("✅ 出力:", OUT_TEAM_PLAYERS)
    print("✅ 出力:", OUT_TEAM_TOTALS)
    print("🗂️ ログ:", LOG)
    if backup_info.get("moved"):
        print("📦 旧成果物を退避:", backup_info["moved"])
        print("🗃️ 保存先:", backup_info.get("dest",""))

if __name__ == "__main__":
    main()


