from __future__ import annotations

import csv
import html
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

TARGET_YEAR = "2025"
OUT_CSV = "match_sources_2025.csv"
TIMEOUT = 20

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 16) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/135.0.0.0 Mobile Safari/537.36"
)

START_URLS = [
    ("1部", "https://u15.kantolsl.com/2025/div1/"),
    ("2部", "https://u15.kantolsl.com/2025/div2/"),
    ("1部", "https://u15.kantolsl.com/2025/div1"),
    ("2部", "https://u15.kantolsl.com/2025/div2"),
]


@dataclass(frozen=True)
class SourceRow:
    year: str
    division: str
    source_type: str
    source_url: str
    discovered_from: str


class HoldError(RuntimeError):
    pass


def now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def fetched_at() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def backup_existing(path: Path) -> None:
    if path.exists():
        backup = path.with_name(f"{path.name}.bak_{now_stamp()}")
        path.replace(backup)
        print(f"backup={backup}")


def fetch_text(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=TIMEOUT) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        body = resp.read()
    return body.decode(charset, errors="replace")


def normalize_url(url: str) -> str:
    url = url.strip()
    url = url.split("#", 1)[0]
    url = url.split("?", 1)[0]
    return url.rstrip("/")


def division_from_url(url: str, fallback: str) -> str:
    path = urlparse(url).path
    if "/div1/" in path or path.endswith("/div1"):
        return "1部"
    if "/div2/" in path or path.endswith("/div2"):
        return "2部"
    return fallback


def extract_match_urls(page_url: str, html_text: str, fallback_division: str) -> List[SourceRow]:
    rows: List[SourceRow] = []
    seen: Set[str] = set()

    # href=".../2025/div1/m01" などを拾う
    hrefs = re.findall(r"""href=["']([^"']+)["']""", html_text, flags=re.I)

    # 念のため、本文中のURL直書きも拾う
    direct_urls = re.findall(
        r"""https?://[^\s"'<>]+/2025/div[12]/m[0-9]+/?""",
        html_text,
        flags=re.I,
    )

    candidates = hrefs + direct_urls

    for raw in candidates:
        full = normalize_url(urljoin(page_url, html.unescape(raw)))

        if not re.search(r"/2025/div[12]/m[0-9]+$", full):
            continue

        if full in seen:
            continue

        seen.add(full)

        division = division_from_url(full, fallback_division)

        rows.append(
            SourceRow(
                year=TARGET_YEAR,
                division=division,
                source_type="primary_match_page",
                source_url=full,
                discovered_from=page_url,
            )
        )

    return rows


def discover() -> List[SourceRow]:
    all_rows: Dict[str, SourceRow] = {}
    errors: List[str] = []

    for division, url in START_URLS:
        try:
            text = fetch_text(url)
        except (HTTPError, URLError, TimeoutError) as e:
            errors.append(f"{url}: fetch failed: {e}")
            continue

        rows = extract_match_urls(url, text, division)

        for r in rows:
            key = r.source_url
            if key not in all_rows:
                all_rows[key] = r

    if not all_rows:
        msg = "no 2025 match urls discovered"
        if errors:
            msg += " | " + " | ".join(errors)
        raise HoldError(msg)

    return sorted(
        all_rows.values(),
        key=lambda r: (
            r.division,
            int(re.search(r"/m([0-9]+)$", r.source_url).group(1)) if re.search(r"/m([0-9]+)$", r.source_url) else 9999,
            r.source_url,
        ),
    )


def write_csv(rows: Sequence[SourceRow], path: Path) -> None:
    backup_existing(path)

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "year",
            "division",
            "source_type",
            "source_url",
            "discovered_from",
            "fetched_at",
        ])

        stamp = fetched_at()

        for r in rows:
            writer.writerow([
                r.year,
                r.division,
                r.source_type,
                r.source_url,
                r.discovered_from,
                stamp,
            ])


def summarize(rows: Sequence[SourceRow]) -> str:
    div1 = sum(1 for r in rows if r.division == "1部")
    div2 = sum(1 for r in rows if r.division == "2部")
    return f"rows={len(rows)}; div1={div1}; div2={div2}"


def main(argv: Sequence[str]) -> int:
    out_csv = Path(argv[1]) if len(argv) > 1 else Path(OUT_CSV)

    try:
        rows = discover()
        write_csv(rows, out_csv)
        print(summarize(rows))
        print(f"written={out_csv}")
        return 0

    except HoldError as e:
        print(f"HOLD: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
