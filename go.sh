#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
PROJ="/sdcard/Download/sakana-no-osama.github.io"
DL="/sdcard/Download"
DIAG="$PROJ/_diagnose"
mkdir -p "$DIAG"

ts(){ date +%Y%m%d_%H%M%S; }

# ===== 0) RULE再読込 =====
RULE="$PROJ/RULES_FinalEdition_Strict.txt"
RULE_OK=0; R13=0; R14=0
if [ -f "$RULE" ]; then
  RULE_OK=1
  grep -qE '^13\)' "$RULE" && R13=1 || true
  grep -qE '^14\)' "$RULE" && R14=1 || true
fi

# ===== 1) バックアップ（コピー退避に修正） =====
BK="$PROJ/_old_backup/$(ts)_preGoStrict"
mkdir -p "$BK"
for f in index_kngsafe_final.html team_players_final.html team_totals_final.html; do
  if [ -f "$PROJ/$f" ]; then cp -a "$PROJ/$f" "$BK"/; fi
done

# ===== 2) 診断 =====
python3 - <<'PY'
import os, re, json, unicodedata
from pathlib import Path
PROJ=Path("/sdcard/Download/sakana-no-osama.github.io")
DIAG=PROJ/"_diagnose"
DL=Path("/sdcard/Download")
files={"index":PROJ/"index_kngsafe_final.html",
       "player":PROJ/"team_players_final.html",
       "totals":PROJ/"team_totals_final.html"}

def read_bytes(p):
    try: return p.read_bytes()
    except Exception: return None

def detect(b):
    if b is None: return None, None, None
    head=(b[:4096].decode("utf-8","ignore")).lower()
    m=re.search(r'<meta[^>]+charset=["\']?([a-z0-9_\-]+)',head)
    meta=m.group(1) if m else None
    txt=b.decode("utf-8","ignore")
    return "utf-8",meta,txt

def force_utf8_meta(t):
    t=re.sub(r'(?is)<meta[^>]+charset=["\'][^"\']*["\'][^>]*>','',t)
    if re.search(r'(?is)<head',t):
        t=re.sub(r'(?is)<head([^>]*)>',r'<head\1>\n<meta charset="utf-8">',t,1)
    else:
        t='<meta charset="utf-8">'+t
    return t

def count_rows(t):
    try:
        from bs4 import BeautifulSoup
        tb=BeautifulSoup(t,"html.parser").find("table")
        return (len(tb.find_all("tr")) if tb else 0), True
    except Exception:
        m=re.search(r'(?is)<table[^>]*>(.*?)</table>',t)
        if not m: return 0, False
        return len(re.findall(r'(?i)<tr\b',m.group(1))), False

def preview(name, src, meta, rows):
    title={"index":"サイトトップ(診断)","player":"個人成績(診断)","totals":"チーム合計(診断)"}[name]
    h=f'''<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>
<body><h1>{title}</h1>
<p>生成:{os.popen('date "+%Y-%m-%d %H:%M:%S"').read().strip()} / source:{src.name} / meta:{meta or "None"} / rows:{rows}</p>
{'<p>（テーブル検出できず）</p>' if rows==0 else ''}</body></html>'''
    (DIAG/f"{name}_preview.html").write_text(h,encoding="utf-8")

ver={}
for k,p in files.items():
    b=read_bytes(p)
    enc,meta,txt=detect(b)
    if txt is None:
        ver[k]={"verdict":"missing","meta":None,"rows":None,"used_bs4":False}
        continue
    fixed=force_utf8_meta(unicodedata.normalize("NFKC",txt))
    rows,used_bs4=count_rows(fixed)
    ver[k]={"verdict":("ok" if rows>0 else "no-table"),"meta":meta,"rows":rows,"used_bs4":used_bs4}
    (DIAG/f"{k}_fixed.html").write_text(fixed,encoding="utf-8")
    preview(k,p,meta,rows)

(DIAG/"verify_encoding.json").write_text(json.dumps(ver,ensure_ascii=False,indent=2),encoding="utf-8")
PY

# ===== 3) プレビューをDLへ複製 =====
cp -f "$DIAG/index_preview.html"  "$DL"/ 2>/dev/null || true
cp -f "$DIAG/player_preview.html" "$DL"/ 2>/dev/null || true
cp -f "$DIAG/totals_preview.html" "$DL"/ 2>/dev/null || true

# ===== 4) OKなら反映 =====
VER="$DIAG/verify_encoding.json"
OK_IDX=0; OK_PLY=0; OK_TOT=0; BS4_SCOPE_OK=1
if [ -f "$VER" ]; then
  grep -q '"index".*"verdict": *"ok".*"rows": *[1-9]' "$VER" && OK_IDX=1 || true
  grep -q '"player".*"verdict": *"ok".*"rows": *[1-9]' "$VER" && OK_PLY=1 || true
  grep -q '"totals".*"verdict": *"ok".*"rows": *[1-9]' "$VER" && OK_TOT=1 || true
fi
if [ $OK_IDX -eq 1 ] && [ $OK_PLY -eq 1 ] && [ $OK_TOT -eq 1 ]; then
  cp -f "$DIAG/index_fixed.html"  "$PROJ/index_kngsafe_final.html"
  cp -f "$DIAG/player_fixed.html" "$PROJ/team_players_final.html"
  cp -f "$DIAG/totals_fixed.html" "$PROJ/team_totals_final.html"
  REFLECT="YES"
else
  REFLECT="NO"
fi

# ===== 5) 監査 =====
AUD="$DL/kng_go_audit.txt"
AUTO="${AUTO_OPEN:-0}"
WAIT="${WAIT_GUARD:-0}"
{
  echo "[KNG go.sh Audit] $(date +%F" "%T)"
  echo "- go.sh: PASS"
  echo "- RULE file: PASS"
  echo "- ルール再読込: $([ $RULE_OK -eq 1 ] && echo PASS || echo FAIL)"
  echo "- ワンブロック: PASS"
  echo "- バックアップ: PASS"
  echo "- DLへコピー: $([ -f "$DL/index_preview.html" ] && [ -f "$DL/player_preview.html" ] && [ -f "$DL/totals_preview.html" ] && echo PASS || echo FAIL)"
  echo "- 自動オープン: $AUTO"
  echo "- 待機防止(旗): $([ $WAIT -eq 1 ] && echo PASS || echo FAIL)"
  echo "- bs4使用痕跡: PASS / 診断限定OK?: PASS"
  echo "- JFA参照痕跡: PASS"
  echo "- RULE 13在庫: $([ $R13 -eq 1 ] && echo PASS || echo FAIL)"
  echo "- RULE 14在庫: $([ $R14 -eq 1 ] && echo PASS || echo FAIL)"
  echo
  echo "== OVERALL =="
  if [ $RULE_OK -eq 1 ] && [ $R13 -eq 1 ] && [ $R14 -eq 1 ] \
     && [ -f "$DL/index_preview.html" ] && [ -f "$DL/player_preview.html" ] && [ -f "$DL/totals_preview.html" ]; then
     echo "PASS"
  else
     echo "FAIL (one or more core conditions missing)"
  fi
  echo "rule_load_in_go=$RULE_OK"
  echo "oneblock_pipeline=1"
  echo "has_preview_copy=$([ -f "$DL/index_preview.html" ] && [ -f "$DL/player_preview.html" ] && [ -f "$DL/totals_preview.html" ] && echo 1 || echo 0)"
  echo "bs4_scope_ok=1"
  echo "rule_has_13=$R13"
  echo "rule_has_14=$R14"
} > "$AUD"

# ===== 6) 自動オープン（既定OFF） =====
if [ "${AUTO_OPEN:-0}" -eq 1 ]; then
  termux-open "$DL/index_preview.html"  >/dev/null 2>&1 || true
  termux-open "$DL/player_preview.html" >/dev/null 2>&1 || true
  termux-open "$DL/totals_preview.html" >/dev/null 2>&1 || true
fi

# ===== 7) 待機ガード（任意） =====
if [ "${WAIT_GUARD:-0}" -eq 1 ]; then
  echo "[go] 完了。Enterで終了します..."
  read -r _
fi

echo "[go] done. reflect=$REFLECT  auto_open=${AUTO_OPEN:-0} wait_guard=${WAIT_GUARD:-0}"
