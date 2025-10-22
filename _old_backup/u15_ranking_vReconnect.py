# ✅ KNG SAFE reconnect版
# 過去成功実績（vFinal3）の環境を復元し、
# unnecessary_html_all / all2 / team_～ も自動スキャン
import os, re
from collections import defaultdict, Counter

BASE = "/sdcard/Download/sakana-no-osama.github.io"
SCAN_DIRS = []
for root, dirs, files in os.walk(BASE):
    for d in dirs:
        if "html" in d.lower() or "team" in d.lower():
            SCAN_DIRS.append(os.path.join(root, d))
SCAN_DIRS.append(BASE)

OUTPUT_FILE = os.path.join(BASE, "index_kngsafe_reconnect.html")

def normalize_name(s):
    s = re.sub(r"\s+", " ", s.replace("\u3000"," ")).strip()
    return re.sub(r"[、。．・･,.;:：]+$", "", s)

def read_text(path):
    for enc in ("utf-8","utf-8-sig","cp932","shift_jis","euc-jp"):
        try:
            with open(path,"r",encoding=enc,errors="ignore") as f:
                return f.read()
        except: pass
    return ""

def extract_table(path):
    t = read_text(path)
    t = re.sub(r"\s+"," ",t)
    # HTMLの表構造から選手名と得点を直接取得
    pattern = r"<tr><td>\d+</td><td>([^<]+)</td><td>[^<]*</td><td>(\d+)</td>"
    results = re.findall(pattern, t)
    return {normalize_name(n): int(g) for n, g in results}

def main():
    totals = defaultdict(int)
    files = []
    for d in SCAN_DIRS:
        if not os.path.isdir(d): continue
        for f in os.listdir(d):
            if f.endswith(".html") and not f.startswith("index"):
                path = os.path.join(d, f)
                found = extract_table(path)
                if found:
                    for n, g in found.items():
                        totals[n] = max(totals[n], g)
                    files.append(f)
    print(f"📂 スキャン対象フォルダ数: {len(SCAN_DIRS)} / HTML検出: {len(files)} / 得点者: {len(totals)}名")
    if not totals:
        print("⚠️ 得点表形式HTMLが読み取れません。テーブル構造を確認してください。")
        return

    ranking = sorted(totals.items(), key=lambda x: (-x[1], x[0]))
    html = [
        "<html><head><meta charset='utf-8'><title>U-15得点ランキング再接続版</title>",
        "<style>body{font-family:sans-serif} table{border-collapse:collapse} th,td{border:1px solid #ccc;padding:6px 10px} th{background:#f6f6f6}</style>",
        "</head><body>",
        "<h2>U-15 得点ランキング（自動再接続版）</h2>",
        f"<p>スキャン対象: {len(files)}ファイル / 検出選手: {len(totals)}名</p>",
        "<table><tr><th>順位</th><th>選手名</th><th>得点</th></tr>"
    ]
    for i, (n, g) in enumerate(ranking, 1):
        html.append(f"<tr><td>{i}</td><td>{n}</td><td>{g}</td></tr>")
    html.append("</table></body></html>")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fw:
        fw.write("\n".join(html))
    print(f"✅ 出力: {OUTPUT_FILE}（{len(ranking)}名）")

if __name__ == "__main__":
    main()
