from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 20

TARGET_YEAR = "2025"
IN_CSV = "matches_2025.csv"
OUT_PROBE = "matches_2025_probe.csv"
OUT_DIFF = "matches_2025_diff.csv"

DIVISION_VALUES = {"1部", "2部", "D1", "D2"}


@dataclass(frozen=True)
class BaseRow:
    year: str
    division: str
    match_id: str
    source_url: str
    home_team: str
    away_team: str
    match_date: str
    section: str
    home_score: str
    away_score: str


@dataclass(frozen=True)
class ProbeRow:
    year: str
    division: str
    match_id: str
    source_url: str
    home_team: str
    away_team: str
    match_date: str
    section: str
    home_score: str
    away_score: str
    fetched_at: str
    status: str


class HoldError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read()
    return body.decode(charset, errors="replace")


def strip_noise(html_text: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", text)
    return text


def normalize_space(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def z2h(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def clean_team(s: str) -> str:
    s = normalize_space(s)
    s = re.sub(r"^(ホーム|アウェイ)\s*", "", s)
    s = re.sub(r"\s*(試合速報|試合結果|公式記録).*$", "", s)
    s = s.strip(" |-｜")
    return s


def norm_compare(s: str) -> str:
    s = normalize_space(s or "")
    s = z2h(s)
    return s


def read_base(path: Path) -> List[BaseRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")
    rows: List[BaseRow] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            year = (r.get("year") or "").strip()
            if year != TARGET_YEAR:
                continue
            division = (r.get("division") or "").strip()
            match_id = (r.get("match_id") or "").strip()
            source_url = (r.get("source_url") or "").strip()
            if not match_id:
                raise HoldError("blank match_id found in matches_2025.csv")
            if not source_url:
                raise HoldError(f"blank source_url found for match_id={match_id}")
            if division not in DIVISION_VALUES:
                raise HoldError(f"unknown division value: {division}")
            rows.append(
                BaseRow(
                    year=year,
                    division=division,
                    match_id=match_id,
                    source_url=source_url,
                    home_team=(r.get("home_team") or "").strip(),
                    away_team=(r.get("away_team") or "").strip(),
                    match_date=(r.get("match_date") or "").strip(),
                    section=(r.get("section") or "").strip(),
                    home_score=(r.get("home_score") or "").strip(),
                    away_score=(r.get("away_score") or "").strip(),
                )
            )
    if not rows:
        raise HoldError("no 2025 rows found in matches_2025.csv")
    return rows


def extract_main_block(compact: str) -> str:
    # 2025ページ向けに、まず「第○節」を起点に本文を切る
    section_m = re.search(r"第\s*[0-9０-９]+\s*節", compact)
    if section_m:
        start = section_m.start()
    else:
        # 節が取れない場合は、2025年の日付を起点にする
        date_m = re.search(r"2025年\s*[0-9０-９]{1,2}月\s*[0-9０-９]{1,2}日", compact)
        if not date_m:
            raise HoldError("main block start marker not found")
        start = date_m.start()

    end_candidates = []
    for marker in ["Latest Matches", "前の記事", "次の記事", "Copyright ©", "MENU 検索"]:
        p = compact.find(marker, start)
        if p != -1:
            end_candidates.append(p)
    end = min(end_candidates) if end_candidates else min(len(compact), start + 3000)

    block = compact[start:end].strip()
    if not block:
        raise HoldError("main block empty after slicing")
    return block


def parse_match_date(block: str) -> str:
    for pat in [
        re.compile(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})"),
        re.compile(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日"),
    ]:
        m = pat.search(block)
        if m:
            y, mo, d = m.groups()
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return ""


def parse_section(block: str) -> str:
    m = re.search(r"第\s*([0-9０-９]+)\s*節", block)
    if m:
        return f"第{int(z2h(m.group(1)))}節"
    return ""


def parse_score(block: str) -> Tuple[str, str]:
    patterns = [
        re.compile(r"合計\s*([0-9０-９]+)\s*[-－ー]\s*([0-9０-９]+)"),
        re.compile(r"([^0-9]|^)([0-9０-９]+)\s*[-－ー]\s*([0-9０-９]+)([^0-9]|$)"),
    ]
    for pat in patterns:
        m = pat.search(block)
        if not m:
            continue
        groups = m.groups()
        nums = [g for g in groups if g and re.fullmatch(r"[0-9０-９]+", g)]
        if len(nums) >= 2:
            return z2h(nums[-2]), z2h(nums[-1])
    return "", ""


def parse_teams(block: str, home_score: str, away_score: str) -> Tuple[str, str]:
    if home_score and away_score:
        score_pat = re.compile(
            rf"(.{{1,100}}?)\s+{re.escape(home_score)}\s*[-－ー]\s*{re.escape(away_score)}\s+(.{{1,100}})"
        )
        m = score_pat.search(block)
        if m:
            left = clean_team(m.group(1))
            right = clean_team(m.group(2))

            for junk in [
                r"^JFA U-15女子サッカーリーグ 2025 関東[１２12１一二]?部?\s*\|\s*第[0-9０-９]+節\s*",
                r"^[0-9０-９]{4}年[0-9０-９]{1,2}月[0-9０-９]{1,2}日（日|月|火|水|木|金|土）\s*-\s*[0-9０-９]{1,2}時[0-9０-９]{2}分\s*",
                r"\s+レッズランド.*$",
                r"\s+柳島スポーツ公園.*$",
                r"\s+中井中央公園.*$",
                r"\s+GCCザスパーク.*$",
                r"\s+とちぎフットボールセンター.*$",
                r"\s+十文字学園女子大学.*$",
                r"\s+SFAフットボールセンター.*$",
                r"\s+ちふれ飯能グラウンド.*$",
                r"\s+ノジマフットボールパーク.*$",
                r"\s+コーエィ前橋フットボールセンター.*$",
            ]:
                left = re.sub(junk, "", left).strip()
                right = re.sub(junk, "", right).strip()

            if "第" in left and "節" in left:
                parts = re.split(r"第\s*[0-9０-９]+\s*節", left)
                left = parts[-1].strip()
            if re.search(r"[0-9０-９]{4}年.*時[0-9０-９]{2}分", left):
                parts = re.split(r"[0-9０-９]{4}年.*時[0-9０-９]{2}分", left, maxsplit=1)
                left = parts[-1].strip()

            right = re.split(
                r"\s+(?:レッズランド|柳島スポーツ公園|中井中央公園|GCCザスパーク|とちぎフットボールセンター|十文字学園女子大学|SFAフットボールセンター|ちふれ飯能グラウンド|ノジマフットボールパーク|コーエィ前橋フットボールセンター|Latest Matches)\b",
                right,
                maxsplit=1,
            )[0].strip()

            if left and right and left != right:
                return left, right

    raise HoldError("home_team / away_team could not be parsed")


def parse_match_page(source_url: str) -> Dict[str, str]:
    text = fetch_text(source_url)
    text = strip_noise(text)
    compact = normalize_space(re.sub(r"<[^>]+>", " ", text))
    block = extract_main_block(compact)

    match_date = parse_match_date(block)
    section = parse_section(block)
    home_score, away_score = parse_score(block)
    home_team, away_team = parse_teams(block, home_score, away_score)

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "match_date": match_date,
        "section": section,
    }


def build_probe_rows(base_rows: Sequence[BaseRow]) -> Tuple[List[ProbeRow], List[str]]:
    out: List[ProbeRow] = []
    holds: List[str] = []

    for row in base_rows:
        try:
            parsed = parse_match_page(row.source_url)
            home_score = (parsed.get("home_score") or "").strip()
            away_score = (parsed.get("away_score") or "").strip()
            status = "played" if home_score != "" and away_score != "" else "review"

            out.append(
                ProbeRow(
                    year=row.year,
                    division=row.division,
                    match_id=row.match_id,
                    source_url=row.source_url,
                    home_team=(parsed.get("home_team") or "").strip(),
                    away_team=(parsed.get("away_team") or "").strip(),
                    match_date=(parsed.get("match_date") or "").strip(),
                    section=(parsed.get("section") or "").strip(),
                    home_score=home_score,
                    away_score=away_score,
                    fetched_at=now_iso(),
                    status=status,
                )
            )
        except HoldError as e:
            holds.append(f"{row.match_id}: {e}")
        except (HTTPError, URLError, TimeoutError) as e:
            holds.append(f"{row.match_id}: fetch failed: {e}")

    return out, holds


def write_probe_csv(rows: Sequence[ProbeRow], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "year", "division", "match_id", "source_url",
            "home_team", "away_team", "match_date", "section",
            "home_score", "away_score", "fetched_at", "status"
        ])
        for r in rows:
            writer.writerow([
                r.year, r.division, r.match_id, r.source_url,
                r.home_team, r.away_team, r.match_date, r.section,
                r.home_score, r.away_score, r.fetched_at, r.status
            ])


def build_diff_rows(base_rows: Sequence[BaseRow], probe_rows: Sequence[ProbeRow], holds: Sequence[str]) -> List[Dict[str, str]]:
    base_map = {r.match_id: r for r in base_rows}
    probe_map = {r.match_id: r for r in probe_rows}

    out: List[Dict[str, str]] = []

    all_ids = sorted(set(base_map) | set(probe_map))
    for match_id in all_ids:
        b = base_map.get(match_id)
        p = probe_map.get(match_id)

        if b and not p:
            note = next((h for h in holds if h.startswith(match_id + ":")), "")
            out.append({
                "match_id": match_id,
                "diff_type": "MISSING_IN_PROBE",
                "base_division": b.division,
                "probe_division": "",
                "base_home_team": b.home_team,
                "probe_home_team": "",
                "base_away_team": b.away_team,
                "probe_away_team": "",
                "base_home_score": b.home_score,
                "probe_home_score": "",
                "base_away_score": b.away_score,
                "probe_away_score": "",
                "base_match_date": b.match_date,
                "probe_match_date": "",
                "base_section": b.section,
                "probe_section": "",
                "note": note,
            })
            continue

        if p and not b:
            out.append({
                "match_id": match_id,
                "diff_type": "MISSING_IN_BASE",
                "base_division": "",
                "probe_division": p.division,
                "base_home_team": "",
                "probe_home_team": p.home_team,
                "base_away_team": "",
                "probe_away_team": p.away_team,
                "base_home_score": "",
                "probe_home_score": p.home_score,
                "base_away_score": "",
                "probe_away_score": p.away_score,
                "base_match_date": "",
                "probe_match_date": p.match_date,
                "base_section": "",
                "probe_section": p.section,
                "note": "",
            })
            continue

        assert b is not None and p is not None

        diffs = []
        fields = [
            ("division", b.division, p.division),
            ("home_team", b.home_team, p.home_team),
            ("away_team", b.away_team, p.away_team),
            ("match_date", b.match_date, p.match_date),
            ("section", b.section, p.section),
            ("home_score", b.home_score, p.home_score),
            ("away_score", b.away_score, p.away_score),
            ("source_url", b.source_url, p.source_url),
        ]

        for name, bv, pv in fields:
            if norm_compare(bv) != norm_compare(pv):
                diffs.append(name)

        out.append({
            "match_id": match_id,
            "diff_type": "OK" if not diffs else "DIFF",
            "base_division": b.division,
            "probe_division": p.division,
            "base_home_team": b.home_team,
            "probe_home_team": p.home_team,
            "base_away_team": b.away_team,
            "probe_away_team": p.away_team,
            "base_home_score": b.home_score,
            "probe_home_score": p.home_score,
            "base_away_score": b.away_score,
            "probe_away_score": p.away_score,
            "base_match_date": b.match_date,
            "probe_match_date": p.match_date,
            "base_section": b.section,
            "probe_section": p.section,
            "note": ",".join(diffs),
        })

    return out


def write_diff_csv(rows: Sequence[Dict[str, str]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "match_id", "diff_type",
                "base_division", "probe_division",
                "base_home_team", "probe_home_team",
                "base_away_team", "probe_away_team",
                "base_home_score", "probe_home_score",
                "base_away_score", "probe_away_score",
                "base_match_date", "probe_match_date",
                "base_section", "probe_section",
                "note",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def summarize_probe(rows: Sequence[ProbeRow], holds: Sequence[str]) -> str:
    return (
        f"probe_rows={len(rows)}; "
        f"holds={len(holds)}"
    )


def main(argv: Sequence[str]) -> int:
    in_csv = Path(argv[1]) if len(argv) > 1 else Path(IN_CSV)
    out_probe = Path(argv[2]) if len(argv) > 2 else Path(OUT_PROBE)
    out_diff = Path(argv[3]) if len(argv) > 3 else Path(OUT_DIFF)

    try:
        base_rows = read_base(in_csv)
        probe_rows, holds = build_probe_rows(base_rows)
        write_probe_csv(probe_rows, out_probe)
        diff_rows = build_diff_rows(base_rows, probe_rows, holds)
        write_diff_csv(diff_rows, out_diff)
        print(summarize_probe(probe_rows, holds))
        return 0
    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
