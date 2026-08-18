from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
)
TIMEOUT = 20
TARGET_YEAR = 2026
OUT_CSV = "match_sources_2026.csv"

PRIMARY_ENTRY = "https://u15.kantolsl.com/"
FALLBACK_ENTRY = "https://www.jfa.jp/match/u15_womens_league_2026/kanto/"

DIVISIONS = ("D1", "D2")

DIVISION_PATTERNS = {
    "D1": [re.compile(r"/2026/div1/?$", re.I), re.compile(r"1部")],
    "D2": [re.compile(r"/2026/div2/?$", re.I), re.compile(r"2部")],
}

MATCH_URL_PATTERNS = {
    "D1": re.compile(r"https?://u15\.kantolsl\.com/2026/div1/m\d+/?$", re.I),
    "D2": re.compile(r"https?://u15\.kantolsl\.com/2026/div2/m\d+/?$", re.I),
}
JFA_MATCH_PATTERN = re.compile(
    r"https?://www\.jfa\.jp/match(?:_[^/]+)?/.*/u15_womens_league_2026/.*/match_page/m\d+\.html$",
    re.I,
)


@dataclass(frozen=True)
class SourceRow:
    year: int
    division: str
    source_type: str
    source_url: str
    discovered_from: str


class HoldError(RuntimeError):
    pass


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read()
    return body.decode(charset, errors="replace")


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    path = re.sub(r"/+", "/", parsed.path)
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return parsed._replace(path=path, fragment="").geturl()


def extract_links(base_url: str, text: str) -> List[Tuple[str, str]]:
    links: List[Tuple[str, str]] = []
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
        url = normalize_url(urljoin(base_url, html.unescape(href.strip())))
        plain = re.sub(r"<[^>]+>", " ", label)
        plain = html.unescape(re.sub(r"\s+", " ", plain)).strip()
        links.append((url, plain))
    return links


def find_primary_division_pages(home_url: str, home_html: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for url, label in extract_links(home_url, home_html):
        for div, patterns in DIVISION_PATTERNS.items():
            if div in found:
                continue
            want = f"/2026/div{1 if div == 'D1' else 2}"
            parsed_ok = url.endswith(want) or url.endswith(want + "/")
            if (any(p.search(url) for p in patterns) or any(p.search(label) for p in patterns)) and parsed_ok:
                found[div] = url
    if "D1" not in found:
        found["D1"] = normalize_url(urljoin(home_url, f"/{TARGET_YEAR}/div1/"))
    if "D2" not in found:
        found["D2"] = normalize_url(urljoin(home_url, f"/{TARGET_YEAR}/div2/"))
    return found


def discover_primary_match_urls(div_page_url: str, division: str) -> List[str]:
    text = fetch_text(div_page_url)
    links = extract_links(div_page_url, text)
    pat = MATCH_URL_PATTERNS[division]
    urls = sorted({url for url, _ in links if pat.match(url)})
    if urls:
        return urls
    guessed = sorted({
        normalize_url(urljoin(div_page_url, m.group(0)))
        for m in re.finditer(rf"/{TARGET_YEAR}/div{'1' if division == 'D1' else '2'}/m\d+/", text, re.I)
    })
    return guessed


def discover_jfa_match_urls(entry_url: str) -> dict[str, List[str]]:
    text = fetch_text(entry_url)
    links = extract_links(entry_url, text)
    out = {"D1": [], "D2": []}
    for url, label in links:
        normalized = normalize_url(url)
        if not JFA_MATCH_PATTERN.match(normalized):
            continue
        div: Optional[str] = None
        low = normalized.lower()
        if "kanto1" in low or "div1" in low or "1部" in label:
            div = "D1"
        elif "kanto2" in low or "div2" in low or "2部" in label:
            div = "D2"
        if div is None:
            if re.search(r"1部", label):
                div = "D1"
            elif re.search(r"2部", label):
                div = "D2"
        if div is not None:
            out[div].append(normalized)
    out = {k: sorted(set(v)) for k, v in out.items()}
    return out


def build_rows() -> List[SourceRow]:
    rows: List[SourceRow] = []
    holds: List[str] = []

    try:
        home_html = fetch_text(PRIMARY_ENTRY)
        div_pages = find_primary_division_pages(PRIMARY_ENTRY, home_html)
    except (HTTPError, URLError, TimeoutError) as e:
        raise HoldError(f"PRIMARY_ENTRY fetch failed: {e}") from e

    for div in DIVISIONS:
        div_page = div_pages.get(div)
        if not div_page:
            holds.append(f"{div}: division page not found on primary entry")
            continue
        rows.append(SourceRow(TARGET_YEAR, div, "primary_division_page", div_page, PRIMARY_ENTRY))
        try:
            match_urls = discover_primary_match_urls(div_page, div)
        except (HTTPError, URLError, TimeoutError) as e:
            holds.append(f"{div}: failed to fetch division page {div_page}: {e}")
            continue
        if not match_urls:
            holds.append(f"{div}: no primary match URLs discovered from {div_page}")
        for url in match_urls:
            rows.append(SourceRow(TARGET_YEAR, div, "primary_match_page", url, div_page))

    primary_count = sum(1 for r in rows if r.source_type == "primary_match_page")

    need_fallback = primary_count == 0 or any(h.startswith("D1") for h in holds) or any(h.startswith("D2") for h in holds)
    if need_fallback:
        try:
            jfa = discover_jfa_match_urls(FALLBACK_ENTRY)
        except (HTTPError, URLError, TimeoutError) as e:
            holds.append(f"fallback fetch failed: {e}")
            jfa = {"D1": [], "D2": []}
        for div in DIVISIONS:
            if jfa[div]:
                rows.append(SourceRow(TARGET_YEAR, div, "fallback_entry", FALLBACK_ENTRY, FALLBACK_ENTRY))
                for url in jfa[div]:
                    rows.append(SourceRow(TARGET_YEAR, div, "fallback_match_page", url, FALLBACK_ENTRY))
            elif not any(r.division == div and r.source_type == "primary_match_page" for r in rows):
                holds.append(f"{div}: fallback also failed to discover match URLs")

    for div in DIVISIONS:
        has_any = any(r.division == div and r.source_type in {"primary_match_page", "fallback_match_page"} for r in rows)
        if not has_any:
            holds.append(f"{div}: no match URLs discovered from any source")

    if holds:
        msg = " | ".join(dict.fromkeys(holds))
        raise HoldError(msg)

    deduped: List[SourceRow] = []
    seen = set()
    for row in rows:
        key = (row.year, row.division, row.source_type, row.source_url, row.discovered_from)
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def write_csv(rows: Sequence[SourceRow], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["year", "division", "source_type", "source_url", "discovered_from"])
        for r in rows:
            writer.writerow([r.year, r.division, r.source_type, r.source_url, r.discovered_from])


def summarize(rows: Sequence[SourceRow]) -> str:
    counts = {}
    for div in DIVISIONS:
        counts[div] = sum(1 for r in rows if r.division == div and r.source_type in {"primary_match_page", "fallback_match_page"})
    return f"rows={len(rows)}; D1_match_urls={counts['D1']}; D2_match_urls={counts['D2']}"


def main(argv: Sequence[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else Path(OUT_CSV)
    try:
        rows = build_rows()
        write_csv(rows, out)
        print(summarize(rows))
        return 0
    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
