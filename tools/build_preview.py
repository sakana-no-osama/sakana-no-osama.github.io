"""Validate saved data and build a local preview, without network or publication."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import platform
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]
from ranking_checks import check_matches, check_rankings
from build_all_years_ranking_html import load_datasets, build_html
from preview_checks import check_page
from workflow_io import atomic_write_text
import verify_2026_standings_fixtures as standings


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def inputs() -> dict[str, str]:
    files = sorted((ROOT / "data").glob("*.csv"))
    for folder in ("scripts", "tests", "tools", "web", "docs"):
        files += sorted(path for path in (ROOT / folder).iterdir()
                        if path.suffix in {".py", ".ps1", ".js", ".css", ".md"})
    return {str(path.relative_to(ROOT)): sha(path.read_bytes()) for path in files}


def build(output: Path, force: bool = False) -> dict:
    if (output / "index.html").resolve() == (ROOT / "index.html").resolve():
        raise ValueError("The public index.html cannot be the preview output")
    started = perf_counter()
    source_hashes = inputs()
    fingerprint = sha(json.dumps([source_hashes, platform.python_version()], sort_keys=True).encode())
    manifest = output / "manifest.json"
    page_path = output / "index.html"
    if not force and manifest.exists() and page_path.exists():
        try:
            saved = json.loads(manifest.read_text(encoding="utf-8"))
            if (saved["fingerprint"] == fingerprint and saved["verdict"] == "PASS"
                    and saved["html_sha256"] == sha(page_path.read_bytes())):
                return {"verdict": "PASS", "cached": True, "seconds": round(perf_counter() - started, 3),
                        "html": str(page_path), "bytes": page_path.stat().st_size}
        except (KeyError, ValueError):
            pass
    matches = check_matches()
    rankings = check_rankings()
    capture = io.StringIO()
    with contextlib.redirect_stdout(capture), contextlib.redirect_stderr(capture):
        result = standings.main()
    if result != 0 or "VERDICT=PASS" not in capture.getvalue():
        raise ValueError(capture.getvalue())
    datasets = load_datasets()
    page = build_html(datasets)
    check_page(page, datasets)
    if inputs() != source_hashes:
        raise ValueError("Source files changed during the build; rerun after editing finishes")
    output.mkdir(parents=True, exist_ok=True)
    atomic_write_text(page_path, page)
    report = {"verdict": "PASS", "cached": False, "fingerprint": fingerprint,
              "html_sha256": sha(page_path.read_bytes()), "inputs": source_hashes,
              "matches": matches, "rankings": rankings, "bytes": page_path.stat().st_size,
              "seconds": round(perf_counter() - started, 3), "html": str(page_path)}
    atomic_write_text(manifest, json.dumps(report, ensure_ascii=False, indent=2))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / ".preview")
    parser.add_argument("--force", action="store_true", help="Repeat all checks and generation")
    args = parser.parse_args()
    try:
        result = build(args.output_dir, args.force)
        print(json.dumps({k: v for k, v in result.items() if k not in {"inputs", "fingerprint", "html_sha256"}}, ensure_ascii=False))
        print("VERDICT=PASS")
        return 0
    except (OSError, ValueError, KeyError, RuntimeError) as exc:
        print(f"VERDICT=FAIL\nFAIL_REASON={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
