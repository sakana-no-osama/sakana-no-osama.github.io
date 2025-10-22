# u15_ranking_vFinal5.py  (KNG SAFE自動解析版)
# HTML内の得点表記を柔軟に解析。KNGルール①②統合済。
import os, re
from collections import defaultdict, Counter

BASE = "/sdcard/Download/sakana-no-osama.github.io"
SCAN_DIRS = [
    BASE,
    "/sdcard/Download",
    "/sdcard/Download/u15_html",
    "/sdcard/Download/unnecessary_html",
    "/sdcard/Download/unnecessary_html_all",
    "/sdcard/Download/unnecessary_html_all2",
]
OUTPUT_FILE = os.path.join(BASE, "index_kngsafe.html")

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

def list_html(d: str):
    if not os.path.isdir(d):
        return []
    files = []
    for f in os.listdir(d):
        if f.lower().endswith(".html") and not f.lower().startswith("index"):
            files.append(os.path.join(d, f))
    return files

def extract_goals(path: str) -> dict:
    txt = read_text(path)
    txt = re.sub(r"<[^>]+>", " ", txt)
    txt = re.sub(r"\s+", " ", txt)

    # === 改良パターン ===
    patterns = [
        # （3得点）形式
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s*[（(]\s*(\d+)\s*(?:得点|点)\s*[)）]",
        # ：3得点形式
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s*[:：]\s*(\d+)\s*(?:得点|点)",
        # スペース区切り形式（例: 山田太郎 3得点）
        r"([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s+(\d+)\s*(?:得点|点)",
        # 「得点：山田太郎（3）」形式（逆順）
        r"(?:得点|点)[：:]\s*([一-龥ぁ-んァ-ンA-Za-z0-9・ー'\- ]{2,20})\s*[（(]?\s*(\d+)\s*[)）]?",
    ]

    found = {}
    for p in patterns:
        for n, g in re.findall(p, txt):
            n = normalize_name(n)
            if len(n) < 2:
                continue
            try:
                g = int(g)
            except:
                continue
            found[n] = max(found.get(n, 0), g)
    return found

def main():
    totals = defaultdict(int)
    per_file = {}
    scanned = 0

    for d in SCAN_DIRS:
        for f in list_html(d):
            scanned += 1
            per = extract_goals(f)
            per_file[os.path.basename(f)] = len(per)
            for name, g in per.items():
                totals[name] = max(totals[name], g)

    print(f"📂 走査ファイル: {scanned} / スコア検出: {len(per_file)}")
    if not totals:
        print("⚠️ 得点データが見当たりません。HTML内表記を確認（例: 3得点, (3点), 得点:3）。")
        return

    print("👀 プレビュー:", Counter(totals).most_common(5))
    ranking = sorted(totals.items(), key=lambda x: (-x[1], x[0]))

    html = [
        "<html><head><meta charset='utf-8'><title>U-15得点ランキング KNG SAFE</title>",
        "<style>body{font-family:sans-serif} table{border-collapse:collapse} th,td{border:1px solid #ccc;padding:6px 10px} th{background:#f6f6f6}</style>",
        "</head><body>",
        "<h2>U-15 得点ランキング（KNG自動解析）</h2>",
        "<p>解析元: ルート + u15_html + unnecessary_html系全て。名前は正規化、同名は最大得点を採用。</p>",
        "<table><tr><th>順位</th><th>選手名</th><th>得点</th></tr>"
    ]

    for i, (n, g) in enumerate(ranking, 1):
        html.append(f"<tr><td>{i}</td><td>{n}</td><td>{g}</td></tr>")

    html.append("</table><h3>診断ログ</h3><ul>")
    for f, c in sorted(per_file.items()):
        html.append(f"<li>{f}: {c}名</li>")
    html.append("</ul></body></html>")

    with open(OUTPUT_FILE, "w", encoding="utf-8") as fw:
        fw.write("\n".join(html))

    print(f"✅ 出力: {OUTPUT_FILE}（{len(ranking)}名）")

if __name__ == "__main__":
    main()
