# -*- coding: utf-8 -*-
"""
KNG SAFE フル対応パイプライン v1
- 不要HTMLの安全退避（削除はしない）
- チーム別HTMLを走査して重複名を正規化、最大得点で集計
- index_kngsafe_final.html を新規生成（既存 index.html は触らない）
- ログを表示（検出数 / 代表的な重複 / 退避件数）

対象ディレクトリ:
  BASE = /sdcard/Download/sakana-no-osama.github.io
  ついでに Download 直下の *.html も回収（SWEEP_DOWNLOAD_ROOT=True）

上書き禁止 / バックアップ必須 / 1コマンド完結
"""

import os, re, shutil, json
from datetime import datetime
from collections import defaultdict, Counter

# ====== 設定 ======
BASE = "/sdcard/Download/sakana-no-osama.github.io"
DOWNLOAD_ROOT = "/sdcard/Download"

# Download 直下の *.html も「不要物」として退避するか
SWEEP_DOWNLOAD_ROOT = True

# 退避（削除はしない）
TS = datetime.now().strftime("%Y%m%d_%H%M%S")
BACKUP_ROOT = f"/sdcard/Download/backup_kng_{TS}"
UNNEC_BASE = os.path.join(BACKUP_ROOT, "unnecessary_html_in_base")
UNNEC_ROOT = os.path.join(BACKUP_ROOT, "unnecessary_html_in_download")

# 出力ファイル（常に新規作成）
OUTPUT_INDEX = os.path.join(BASE, "index_kngsafe_final.html")
OUTPUT_JSON  = os.path.join(BASE, f"kng_result_{TS}.json")

# 残す（＝退避しない）ファイル名のパターン
KEEP_PATTERNS = [
    r"^index.*\.html$",              # index 系
    r"^U15RANK.*\.html$",            # RANK インデックスなど
    r"^team_.*\.html$",              # チーム別
]

# ====== ユーティリティ ======
def ensure_dir(d):
    os.makedirs(d, exist_ok=True)

def match_any(name, patterns):
    return any(re.search(p, name, flags=re.I) for p in patterns)

def list_html(dirpath):
    try:
        return [f for f in os.listdir(dirpath) if f.lower().endswith(".html")]
    except Exception:
        return []

def strip_tags(x):
    return re.sub(r"<[^>]*>", "", x, flags=re.S).strip()

def normalize_name(name):
    n = name
    # 全角→半角（簡便版）
    table = str.maketrans({
        "　":" ", "–":"-", "－":"-", "―":"-", "‐":"-",
    })
    n = n.translate(table)
    # よくある表記ゆれ
    n = n.replace("　", " ").replace(" ", " ")  # NBSP
    n = re.sub(r"\s+", " ", n).strip()
    n = n.replace("（", "(").replace("）", ")")
    # オウンゴール統一
    if re.fullmatch(r"(オウンゴール|ＯＧ|OG|og)", n, flags=re.I):
        return "OG"
    # 記号・空白除去（人名の重複対策）
    n2 = re.sub(r"[^\w\u3040-\u30FF\u4E00-\u9FFF]+", "", n)
    return n2

def parse_team_rows(html):
    """
    期待テーブル: 4列（順位/選手名/チーム/得点） or 3列（順位なし）
    """
    rows = []
    # tr を抜く
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", html, flags=re.S|re.I):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S|re.I)
        if not tds:
            continue
        cols = [strip_tags(x) for x in tds]
        # ヘッダー行スキップ
        head = "".join(cols)
        if "選手" in head and "得点" in head:
            continue
        # 列当て
        name, team, goals = None, None, None
        if len(cols) >= 4:
            # [順位, 選手, チーム, 得点]
            name, team, goals = cols[1], cols[2], cols[3]
        elif len(cols) == 3:
            # [選手, チーム, 得点] の想定
            name, team, goals = cols[0], cols[1], cols[2]
        else:
            continue
        # 得点は数字のみ抽出
        m = re.search(r"\d+", goals)
        if not m:
            continue
        g = int(m.group())
        rows.append((name.strip(), team.strip(), g))
    return rows

def extract_table(path):
    try:
        html = open(path, encoding="utf-8").read()
    except Exception:
        return []
    return parse_team_rows(html)

def is_team_file(fname):
    return fname.lower().startswith("team_") and fname.lower().endswith(".html")

# ====== 1) 不要HTMLの安全退避 ======
def sweep_unnecessary():
    moved = 0
    ensure_dir(UNNEC_BASE)
    files = list_html(BASE)
    for f in files:
        if match_any(f, KEEP_PATTERNS):
            continue
        src = os.path.join(BASE, f)
        dst = os.path.join(UNNEC_BASE, f)
        try:
            shutil.move(src, dst)
            moved += 1
        except Exception:
            pass

    moved_root = 0
    if SWEEP_DOWNLOAD_ROOT:
        ensure_dir(UNNEC_ROOT)
        for f in list_html(DOWNLOAD_ROOT):
            # BASE 配下の index / team に関係ない「直下 *.html」は退避
            # （誤爆防止のため、sakana-no-osama.github.io の外にある *.html を拾う）
            src = os.path.join(DOWNLOAD_ROOT, f)
            if os.path.isdir(src):
                continue
            # BASE 直下に同名があるなら触らない
            if os.path.exists(os.path.join(BASE, f)):
                continue
            try:
                shutil.move(src, os.path.join(UNNEC_ROOT, f))
                moved_root += 1
            except Exception:
                pass

    return moved, moved_root

# ====== 2) 集計（重複名は正規化し最大得点採用） ======
def aggregate():
    per_file_counts = {}
    totals = defaultdict(int)
    shown_name = {}   # 正規化名 -> 表示名
    name_team  = {}   # 正規化名 -> 採用チーム
    conflicts  = []   # チームが異なる重複の記録

    team_files = [f for f in list_html(BASE) if is_team_file(f)]
    scanned = 0
    for f in team_files:
        scanned += 1
        rows = extract_table(os.path.join(BASE, f))
        per_file_counts[f] = len(rows)
        for name, team, g in rows:
            key = normalize_name(name)
            # 表示名はより長い方を採用（漢字優先想定）
            if key not in shown_name or len(name) > len(shown_name[key]):
                shown_name[key] = name
            # チームが違う場合の記録（採点は最大値）
            if key in name_team and name_team[key] != team:
                conflicts.append((shown_name[key], name_team[key], team))
            name_team[key] = team if (key not in name_team or g >= totals[key]) else name_team[key]
            if g > totals[key]:
                totals[key] = g

    return {
        "scanned": scanned,
        "team_files": team_files,
        "per_file_counts": per_file_counts,
        "totals": dict(totals),
        "shown_name": shown_name,
        "name_team": name_team,
        "conflicts": conflicts,
    }

# ====== 3) index（完成版）生成 ======
def build_index(result):
    totals = result["totals"]
    shown  = result["shown_name"]
    name_team = result["name_team"]
    per_file = result["per_file_counts"]

    ranking = sorted(totals.items(), key=lambda x: (-x[1], x[0]))
    files = result["team_files"]
    # チームリンク（ファイル名昇順）
    links = "\n".join(
        f'<li><a href="{f}">{strip_tags(f.replace("team_","").replace(".html",""))}</a></li>'
        for f in sorted(files)
    )

    # 診断ログ
    per_log = "\n".join(
        f"<li>{f}: {c}名</li>" for f, c in sorted(per_file.items())
    )

    # ランキング表
    rows = []
    for i, (key, g) in enumerate(ranking, 1):
        name = shown.get(key, key)
        team = name_team.get(key, "")
        rows.append(f"<tr><td>{i}</td><td>{name}</td><td>{team}</td><td>{g}</td></tr>")
    table = "\n".join(rows)

    html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>U-15 得点ランキング（KNG 最終版）</title>
<style>
body{{font-family:sans-serif}}
table{{border-collapse:collapse}}
th,td{{border:1px solid #ccc;padding:6px 10px}}
th{{background:#f6f6f6}}
small{{color:#666}}
</style></head><body>
<h2>U-15 得点ランキング（自動集計・KNG）</h2>
<p>最終更新: {datetime.now().strftime("%Y/%m/%d %H:%M:%S")} / スキャン: {result["scanned"]}ファイル</p>

<h3>得点ランキング</h3>
<table>
<tr><th>順位</th><th>選手名</th><th>チーム</th><th>得点</th></tr>
{table}
</table>

<h3>チーム別ランキング（リンク）</h3>
<ul>
{links}
</ul>

<h3>診断ログ（ファイル別検出人数）</h3>
<ul>
{per_log}
</ul>

<p><small>※ 重複名は正規化し「最大得点」を採用。異チーム重複は name_team の最新チームで表示。</small></p>
</body></html>"""
    open(OUTPUT_INDEX, "w", encoding="utf-8").write(html)
    return OUTPUT_INDEX

# ====== メイン ======
def main():
    if not os.path.isdir(BASE):
        print(f"❌ BASE が見つかりません: {BASE}")
        return

    ensure_dir(BACKUP_ROOT)
    m1, m2 = sweep_unnecessary()
    print(f"📦 退避: BASE内 {m1} 件 / Download直下 {m2} 件 → {BACKUP_ROOT}")

    result = aggregate()

    # ざっくりプレビュー
    totals = result["totals"]
    if not totals:
        print("⚠️ 得点データが検出できません。team_*.html の表構造をご確認ください。")
        return
    print("👀 上位プレビュー:", Counter(totals).most_common(5))

    out = build_index(result)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"✅ 出力: {out}（{len(totals)}名）")
    print(f"📝 ログ: {OUTPUT_JSON}")
    print("👉 ブラウザで直接開く: file://" + out)

if __name__ == "__main__":
    main()
