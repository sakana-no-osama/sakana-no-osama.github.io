"""Verify the played subset and scorer total for each team in every match."""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from ranking_checks import DATA, check_matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    args = parser.parse_args()
    try:
        print(check_matches(args.data_dir))
        print("VERDICT=PASS")
        return 0
    except (OSError, ValueError, KeyError, csv.Error) as exc:
        print(f"VERDICT=FAIL\nFAIL_REASON={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
