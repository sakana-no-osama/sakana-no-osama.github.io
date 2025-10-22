# u15_ranking_vFinal4.py  (KNG SAFE版)
# ①②統合：このファイルはheredocで毎回作り直す。既存データは上書きしない。
import os, re
from collections import defaultdict, Counter

# ===== 参照ディレクトリ =====
BASE = "/sdcard/Download/sakana-no-osama.github.io"
SCAN_DIRS = [
    BASE,
    "/sdcard/Download",                        # 直下に置いた html も拾う
    "/sdcard/Download/u15_html",
    "/sdcard/Download/unnecessary_html",
    "/sdcard/Download/unnecessary_html_all",
    "/sdcard/Download/unnecessary_html_all2",
]

# 出力（既存 index を上書きしない）
OUTPUT_FILE = os.path.join(BASE, "index_kngsafe.html")

# ===== ユーティリティ =====
def normalize_name(s: str) -> str:
    s = s.replace("\u3000", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"[、。．・･,.;:：]+$", "", s)
    return s

def read_text(path: str) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932", "shift_jis", "euc-jp"):
        try:
            with open(path, "r", encoding=enc, errors="ignore") as f:
                return f.read()
        except Exception:
            pass
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="ignore")

def list_html(dirpath: str):
    if not os.path.isdir(dirpath):
        return []
    out = []
    for f in os.listdir(dirpath):
        if not f.lower().endswith(".html"):
            continue
        lf = f.lower()
        if lf.startswith("index"):   # 出力物/トップは除外
            continue
        out.append(os.path.join(dirpath, f))
    return sorted(out)

def extract_goals(path: str) -> dict:
    """
    HTML→ {選手名: 得点}
    例）山田太郎(3得点) / 山田(1点) / 山田：3得点 / 山田 3点 などを拾う
    同一ファイルで同名複数なら最大値採用
    """
    txt = read_text(path)
    txt = re.sub(r"<[^>]+>", " ", txt)         # タグ除去
    txt = re.sub(r"\s+", " ", txt)

    pats = [
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s*[（(]\s*(\d+)\s*(?:得点|点)\s*[)）]",
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s*[:：]\s*(\d+)\s*(?:得点|点)",
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s+(\d+)\s*(?:得点|点)"
    ]
    got = {}
    for p in pats:
        for name, num in re.findall(p, txt):
            name = normalize_name(name)
            if not name: 
                continue
            try:
                g = int(num)
            except:
                continue
            if g <= 0: 
                continue
            if name in got:
                got[name] = max(got[name], g)
            else:
                got[name] = g
    return got

def main():
    totals = defaultdict(int)   # {名前: 最大得点}
    per_file = {}               # {ファイル: 検出人数}
    scanned = 0

    for d in SCAN_DIRS:
        files = list_html(d)
        if not files:
            continue
        for p in files:
            scanned += 1
            try:
                per = extract_goals(p)
            except Exception as e:
                print(f"⚠️ 解析失敗: {os.path.basename(p)} -> {e}")
                continue
            per_file[os.path.basename(p)] = len(per)
            for name, g in per.items():
                if g > totals[name]:
                    totals[name] = g

    print(f"📂 走査ファイル: {scanned} / スコア検出: {len(per_file)}")
    if not totals:
        print("⚠️ 得点データが見当たりません。退避フォルダ(unnecessary_html*_ , u15_html 等)に片寄っていないか確認してください。")
        return

    print("👀 プレビュー:", Counter(totals).most_common(5))

    ranking = sorted(totals.items(), key=lambda x: (-x[1], x[0]))

    html = []
    html.append("<html><head><meta charset='utf-8'><title>U-15 得点ランキング(KNG SAFE)</title>")
    html.append("<style>body{font-family:sans-serif} table{border-collapse:collapse} th,td{border:1px solid #ccc;padding:6px 10px} th{background:#f6f6f6}</style>")
    html.append("</head><body>")
    html.append("<h2>U-15 得点ランキング（自動集計・KNG SAFE）</h2>")
    html.append("<p>解析元: ルート + u15_html + unnecessary_html系すべて。名前は正規化し、同名は最大得点を採用。</p>")
    html.append("<table><tr><th>順位</th><th>選手名</th><th>得点</th></tr>")
    for i, (name, g) in enumerate(ranking, 1):
        html.append(f"<tr><td>{i}</td><td>{name}</td><td>{g}</td></tr>")
    html.append("</table>")

    html.append("<h3>診断ログ（ファイル別検出人数）</h3><ul>")
    for f, c in sorted(per_file.items()):
        html.append(f"<li>{f}: {c}名</li>")
    html.append("</ul></body></html>")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fw:
        fw.write("\n".join(html))
    print(f"✅ 出力: {OUTPUT_FILE}（{len(ranking)}名）")

if __name__ == "__main__":
    main()
