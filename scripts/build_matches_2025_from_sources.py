from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
)

TIMEOUT = 20
TARGET_YEAR = "2025"
IN_CSV = "match_sources_2025.csv"
OUT_CSV = "matches_2025.csv"

MATCH_PAGE_TYPES = {"primary_match_page", "fallback_match_page"}

DIVISION_MAP = {
    "D1": "1部",
    "D2": "2部",
    "1部": "1部",
    "2部": "2部",
}

DIV_CODE_MAP = {
    "1部": "D1",
    "2部": "D2",
    "D1": "D1",
    "D2": "D2",
}


@dataclass(frozen=True)
class SourceRow:
    year: str
    division: str
    source_type: str
    source_url: str
    discovered_from: str


@dataclass(frozen=True)
class MatchRow:
    year: str
    division: str
    match_id: str
    url_key: str
    source_url: str
    match_date: str
    kickoff: str
    section: str
    home_team: str
    away_team: str
    home_score: str
    away_score: str
    venue: str
    status: str
    fetched_at: str
    source_type: str
    discovered_from: str
    note: str


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


def normalize_space(text: str) -> str:
    text = html.unescape(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_noise(html_text: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", html_text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?is)<!--.*?-->", " ", text)
    text = re.sub(r"(?is)<noscript\b.*?</noscript>", " ", text)
    return text


def z2h(s: str) -> str:
    return s.translate(str.maketrans("０１２３４５６７８９", "0123456789"))


def read_sources(path: Path) -> List[SourceRow]:
    if not path.exists():
        raise HoldError(f"input csv not found: {path}")

    rows: List[SourceRow] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for r in reader:
            year = (r.get("year") or "").strip()
            division_raw = (r.get("division") or "").strip()
            source_type = (r.get("source_type") or "").strip()
            source_url = (r.get("source_url") or "").strip()
            discovered_from = (r.get("discovered_from") or "").strip()

            if year != TARGET_YEAR:
                continue

            if source_type not in MATCH_PAGE_TYPES:
                continue

            division = DIVISION_MAP.get(division_raw, "")
            if not division:
                raise HoldError(f"unknown division: {division_raw}")

            if not source_url:
                raise HoldError("blank source_url found")

            rows.append(
                SourceRow(
                    year=year,
                    division=division,
                    source_type=source_type,
                    source_url=source_url,
                    discovered_from=discovered_from,
                )
            )

    if not rows:
        raise HoldError("no 2025 match page rows found")

    return rows


def url_key_from_source(source_url: str) -> str:
    m = re.search(r"/m(\d+)/?$", urlparse(source_url).path)
    if not m:
        raise HoldError(f"cannot extract match key from url: {source_url}")
    return f"m{m.group(1)}"


def make_match_id(year: str, division: str, source_url: str) -> Tuple[str, str]:
    url_key = url_key_from_source(source_url)
    div_code = DIV_CODE_MAP[division]
    return f"{year}_{div_code}_{url_key}", url_key


def html_to_compact(html_text: str) -> str:
    text = strip_noise(html_text)
    text = re.sub(r"<[^>]+>", " ", text)
    return normalize_space(text)


def find_match_start(compact: str) -> int:
    """
    ページ更新日ではなく、試合本文の日付を拾う。
    正:
      2025年4月5日（日） - 12時00分
    NG:
      2025年3月20日 最終更新日時
    """
    date_time_pat = re.compile(
        r"2025年\s*[0-9０-９]{1,2}月\s*[0-9０-９]{1,2}日"
        r"（[月火水木金土日]）\s*-\s*[0-9０-９]{1,2}時\s*[0-9０-９]{2}分"
    )

    candidates = []
    for m in date_time_pat.finditer(compact):
        window = compact[m.start(): m.start() + 500]
        if "JFA U-15女子サッカーリーグ 2025" in window:
            candidates.append(m.start())

    if candidates:
        return candidates[0]

    m = date_time_pat.search(compact)
    if m:
        return m.start()

    raise HoldError("match date-time start not found")


def extract_main_block(compact: str) -> str:
    start = find_match_start(compact)

    end_candidates = []
    for marker in ["Latest Matches", "前の記事", "次の記事", "Copyright ©", "MENU 検索"]:
        p = compact.find(marker, start)
        if p != -1:
            end_candidates.append(p)

    end = min(end_candidates) if end_candidates else min(len(compact), start + 3500)

    block = compact[start:end].strip()
    if not block:
        raise HoldError("main block empty")

    return block


def parse_date(block: str) -> str:
    m = re.search(r"(2026)年\s*([0-9０-９]{1,2})月\s*([0-9０-９]{1,2})日（[月火水木金土日]）", block)
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{int(z2h(y)):04d}-{int(z2h(mo)):02d}-{int(z2h(d)):02d}"


def parse_kickoff(block: str) -> str:
    m = re.search(r"([0-9０-９]{1,2})時\s*([0-9０-９]{2})分", block)
    if not m:
        return ""
    hh, mm = m.groups()
    return f"{int(z2h(hh)):02d}:{int(z2h(mm)):02d}"


def parse_section(block: str) -> str:
    m = re.search(r"JFA U-15女子サッカーリーグ 2025\s+関東[１２12１二一]+部\s*\|\s*第\s*([0-9０-９]+)\s*節", block)
    if not m:
        m = re.search(r"第\s*([0-9０-９]+)\s*節", block)
    if not m:
        return ""
    return f"第{int(z2h(m.group(1)))}節"


def after_section_text(block: str) -> str:
    m = re.search(r"JFA U-15女子サッカーリーグ 2025\s+関東[１２12１二一]+部\s*\|\s*第\s*[0-9０-９]+\s*節", block)
    if m:
        return block[m.end():].strip()

    m = re.search(r"第\s*[0-9０-９]+\s*節", block)
    if m:
        return block[m.end():].strip()

    return block.strip()


def clean_team_name(s: str) -> str:
    s = normalize_space(s)
    s = re.sub(r"^前半\s*:\s*[0-9０-９]+\s*[-－ー:：]\s*[0-9０-９]+\s*", "", s)
    s = re.sub(r"^後半\s*:\s*[0-9０-９]+\s*[-－ー:：]\s*[0-9０-９]+\s*", "", s)
    s = s.strip(" -－ー|｜")
    return s


def split_venue(raw: str) -> str:
    venue = normalize_space(raw)
    venue = re.split(r"\s+Match Summary\b", venue, maxsplit=1)[0]
    venue = re.split(r"\s+【得点者】", venue, maxsplit=1)[0]
    venue = re.split(r"\s+Latest Matches\b", venue, maxsplit=1)[0]
    venue = re.split(r"\s+前の記事\b", venue, maxsplit=1)[0]
    venue = re.split(r"\s+次の記事\b", venue, maxsplit=1)[0]
    venue = venue.strip(" -－ー|｜")
    return venue


def parse_played_from_direct_body(after_sec: str) -> Tuple[str, str, str, str, str, str]:
    """
    played 試合の直接構造を読む。

    例:
      前半: 2-0
      三菱重工浦和レッズレディースジュニアユース 2
      2 - 1
      湘南ベルマーレU-15ガールズ 1
      試合終了
      レッズランド
      Match Summary
    """
    text = normalize_space(after_sec)

    if "試合終了" not in text:
        return "", "", "", "", "", "no fulltime marker"

    before_end, after_end = text.split("試合終了", 1)

    # 先頭の前半/後半情報は対戦カード抽出の邪魔なので除外
    before_end = re.sub(
        r"^前半\s*:\s*[0-9０-９]+\s*[-－ー:：]\s*[0-9０-９]+\s*",
        "",
        before_end,
    ).strip()
    before_end = re.sub(
        r"^後半\s*:\s*[0-9０-９]+\s*[-－ー:：]\s*[0-9０-９]+\s*",
        "",
        before_end,
    ).strip()

    # home team + 表示得点 + 合計スコア + away team + 表示得点
    pat = re.compile(
        r"(?P<home>.+?)\s+"
        r"(?P<home_display>[0-9０-９]+)\s+"
        r"(?P<home_score>[0-9０-９]+)\s*[-－ー:：]\s*(?P<away_score>[0-9０-９]+)\s+"
        r"(?P<away>.+?)\s+"
        r"(?P<away_display>[0-9０-９]+)\s*$"
    )

    m = pat.search(before_end)
    if not m:
        return "", "", "", "", "", "played pattern not matched"

    home_team = clean_team_name(m.group("home"))
    away_team = clean_team_name(m.group("away"))
    home_score = z2h(m.group("home_score"))
    away_score = z2h(m.group("away_score"))
    venue = split_venue(after_end)

    note_parts = []
    if z2h(m.group("home_display")) != home_score:
        note_parts.append("home display score mismatch")
    if z2h(m.group("away_display")) != away_score:
        note_parts.append("away display score mismatch")
    if not venue:
        note_parts.append("venue blank")

    return home_team, away_team, home_score, away_score, venue, "; ".join(note_parts)


def parse_scheduled_from_direct_body(after_sec: str) -> Tuple[str, str, str, str, str, str]:
    """
    未更新/未開催ページ用。
    スコアが無いので、取れない場合は review に回す。
    """
    text = normalize_space(after_sec)

    # 余計な後続を切る
    text = re.split(r"\s+Match Summary\b", text, maxsplit=1)[0]
    text = re.split(r"\s+Latest Matches\b", text, maxsplit=1)[0]
    text = re.split(r"\s+前の記事\b", text, maxsplit=1)[0]
    text = re.split(r"\s+次の記事\b", text, maxsplit=1)[0].strip()

    if not text:
        return "", "", "", "", "", "scheduled body empty"

    # スコアが無いページは構造が薄いことがあるため、
    # ここでは明確に2チームを分離できる場合のみ scheduled とする。
    known_venue_markers = [
        "レッズランド",
        "柳島スポーツ公園",
        "中井中央公園",
        "GCCザスパーク",
        "とちぎフットボールセンター",
        "十文字学園女子大学",
        "SFAフットボールセンター",
        "ちふれ飯能グラウンド",
        "ノジマフットボールパーク",
        "コーエィ前橋フットボールセンター",
        "フクダ電子フィールド",
        "馬入ふれあい公園",
        "熊谷スポーツ文化公園",
        "横須賀リーフスタジアム",
    ]

    venue = ""
    body = text
    for marker in known_venue_markers:
        p = text.find(marker)
        if p != -1:
            body = text[:p].strip()
            venue = text[p:].strip()
            break

    # チーム分割は安全優先。候補キーワードを持つチーム名が2つ取れる場合のみ採用。
    team_key = r"(?:U-15|U15|FC|SC|レディース|ガールズ|ユース|CRAVO|WOMEN|中学校|アカデミー|MEG|GUNNERS)"
    team_pat = re.compile(rf"(.+?{team_key})\s+(.+?{team_key})$")

    m = team_pat.search(body)
    if not m:
        return "", "", "", "", venue, "scheduled teams not parsed"

    home_team = clean_team_name(m.group(1))
    away_team = clean_team_name(m.group(2))

    if not home_team or not away_team or home_team == away_team:
        return "", "", "", "", venue, "scheduled team cleanup failed"

    return home_team, away_team, "", "", venue, ""


def parse_match_date_from_compact(compact: str) -> str:
    """
    2025ページ用。
    最終更新日時ではなく、試合本文の
    2025年○月○日（曜） - ○時○分
    を優先して拾う。
    """
    pat = re.compile(
        r"(2025)年\\s*([0-9０-９]{1,2})月\\s*([0-9０-９]{1,2})日"
        r"（[月火水木金土日]）\\s*-\\s*[0-9０-９]{1,2}時[0-9０-９]{2}分"
    )

    candidates = []
    for m in pat.finditer(compact):
        window = compact[m.start():m.start() + 700]
        if "JFA U-15女子サッカーリーグ" in window or "関東" in window:
            candidates.append(m)

    if not candidates:
        m = pat.search(compact)
        if not m:
            return ""
    else:
        m = candidates[0]

    y, mo, d = m.groups()
    return f"{int(z2h(y)):04d}-{int(z2h(mo)):02d}-{int(z2h(d)):02d}"


def parse_kickoff_from_compact(compact: str) -> str:
    pat = re.compile(
        r"2025年\\s*[0-9０-９]{1,2}月\\s*[0-9０-９]{1,2}日"
        r"（[月火水木金土日]）\\s*-\\s*([0-9０-９]{1,2})時([0-9０-９]{2})分"
    )

    candidates = []
    for m in pat.finditer(compact):
        window = compact[m.start():m.start() + 700]
        if "JFA U-15女子サッカーリーグ" in window or "関東" in window:
            candidates.append(m)

    if not candidates:
        m = pat.search(compact)
        if not m:
            return ""
    else:
        m = candidates[0]

    hh, mm = m.groups()
    return f"{int(z2h(hh)):02d}:{int(z2h(mm)):02d}"


def parse_match_page(source_url: str) -> dict:
    html_text = fetch_text(source_url)
    compact = html_to_compact(html_text)
    block = extract_main_block(compact)

    match_date = parse_date(block)
    if not match_date:
        m_date = re.search(
            r"(2025)年\s*([0-9０-９]{1,2})月\s*([0-9０-９]{1,2})日"
            r"（[月火水木金土日]）\s*-\s*[0-9０-９]{1,2}時[0-9０-９]{2}分",
            compact,
        )
        if m_date:
            y, mo, d = m_date.groups()
            match_date = f"{int(z2h(y)):04d}-{int(z2h(mo)):02d}-{int(z2h(d)):02d}"

    kickoff = parse_kickoff(block)
    if not kickoff:
        kickoff = parse_kickoff_from_compact(compact)

    section = parse_section(block)

    body = after_section_text(block)

    if "試合終了" in body:
        home_team, away_team, home_score, away_score, venue, note = parse_played_from_direct_body(body)
        status = "played" if home_team and away_team and home_score != "" and away_score != "" else "review"
    else:
        home_team, away_team, home_score, away_score, venue, note = parse_scheduled_from_direct_body(body)
        status = "scheduled" if home_team and away_team else "review"

    missing = []
    if not match_date:
        missing.append("match_date")
    if not kickoff:
        missing.append("kickoff")
    if not section:
        missing.append("section")
    if not home_team:
        missing.append("home_team")
    if not away_team:
        missing.append("away_team")

    if missing:
        status = "review"
        add = "missing " + "/".join(missing)
        note = f"{note}; {add}".strip("; ")

    return {
        "match_date": match_date,
        "kickoff": kickoff,
        "section": section,
        "home_team": home_team,
        "away_team": away_team,
        "home_score": home_score,
        "away_score": away_score,
        "venue": venue,
        "status": status,
        "note": note,
    }


def build_rows(sources: Sequence[SourceRow]) -> List[MatchRow]:
    rows: List[MatchRow] = []

    for src in sources:
        match_id, url_key = make_match_id(src.year, src.division, src.source_url)

        try:
            parsed = parse_match_page(src.source_url)
            rows.append(
                MatchRow(
                    year=src.year,
                    division=src.division,
                    match_id=match_id,
                    url_key=url_key,
                    source_url=src.source_url,
                    match_date=parsed["match_date"],
                    kickoff=parsed["kickoff"],
                    section=parsed["section"],
                    home_team=parsed["home_team"],
                    away_team=parsed["away_team"],
                    home_score=parsed["home_score"],
                    away_score=parsed["away_score"],
                    venue=parsed["venue"],
                    status=parsed["status"],
                    fetched_at=now_iso(),
                    source_type=src.source_type,
                    discovered_from=src.discovered_from,
                    note=parsed["note"],
                )
            )
        except (HoldError, HTTPError, URLError, TimeoutError) as e:
            rows.append(
                MatchRow(
                    year=src.year,
                    division=src.division,
                    match_id=match_id,
                    url_key=url_key,
                    source_url=src.source_url,
                    match_date="",
                    kickoff="",
                    section="",
                    home_team="",
                    away_team="",
                    home_score="",
                    away_score="",
                    venue="",
                    status="review",
                    fetched_at=now_iso(),
                    source_type=src.source_type,
                    discovered_from=src.discovered_from,
                    note=str(e),
                )
            )

    return dedupe_rows(rows)


def dedupe_rows(rows: Sequence[MatchRow]) -> List[MatchRow]:
    seen = {}

    for row in rows:
        if row.match_id not in seen:
            seen[row.match_id] = row
            continue

        old = seen[row.match_id]
        same = old.source_url == row.source_url and old.division == row.division
        if not same:
            raise HoldError(f"duplicate match_id mismatch: {row.match_id}")

    return list(seen.values())


def write_csv(rows: Sequence[MatchRow], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "year",
            "division",
            "match_id",
            "url_key",
            "source_url",
            "match_date",
            "kickoff",
            "section",
            "home_team",
            "away_team",
            "home_score",
            "away_score",
            "venue",
            "status",
            "fetched_at",
            "source_type",
            "discovered_from",
            "note",
        ])

        for r in rows:
            writer.writerow([
                r.year,
                r.division,
                r.match_id,
                r.url_key,
                r.source_url,
                r.match_date,
                r.kickoff,
                r.section,
                r.home_team,
                r.away_team,
                r.home_score,
                r.away_score,
                r.venue,
                r.status,
                r.fetched_at,
                r.source_type,
                r.discovered_from,
                r.note,
            ])


def summarize(rows: Sequence[MatchRow]) -> str:
    total = len(rows)
    played = sum(1 for r in rows if r.status == "played")
    scheduled = sum(1 for r in rows if r.status == "scheduled")
    review = sum(1 for r in rows if r.status == "review")
    d1 = sum(1 for r in rows if r.division == "1部")
    d2 = sum(1 for r in rows if r.division == "2部")
    return (
        f"rows={total}; div1={d1}; div2={d2}; "
        f"played={played}; scheduled={scheduled}; review={review}"
    )


def main(argv: Sequence[str]) -> int:
    in_csv = Path(argv[1]) if len(argv) > 1 else Path(IN_CSV)
    out_csv = Path(argv[2]) if len(argv) > 2 else Path(OUT_CSV)

    try:
        sources = read_sources(in_csv)
        rows = build_rows(sources)
        write_csv(rows, out_csv)
        print(summarize(rows))
        return 0
    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
