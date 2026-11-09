"""Explicit partial updates: missing records stay visible and cannot hide errors."""
import csv
from datetime import date
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tools")]
from ranking_checks import check_matches, read_csv, read_pending_scorers, PENDING_FIELDS, PENDING_FILE
import build_all_years_ranking_html as renderer
import prepare_2026_update as updater


def write(path, rows, fields=None):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


class PendingScorers(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="kanto-pending-test-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.data = self.root / "data"
        shutil.copytree(ROOT / "data", self.data)
        self.original_events = read_csv(self.data / "goal_events_2026.csv")
        self.pending = read_pending_scorers(self.data)
        self.match = next(r for r in read_csv(self.data / "matches_2026_played.csv")
                          if r["match_id"] not in self.pending and int(r["home_score"]) + int(r["away_score"]) > 0)
        self.mid = self.match["match_id"]
        template = next(r for r in self.original_events if r["match_id"] == self.mid)
        diagnostic = dict(template, team="", player="", goals="0", goal_minutes="", note="scorers_block_not_found")
        self.events = [r for r in self.original_events if r["match_id"] != self.mid] + [diagnostic]
        write(self.data / "goal_events_2026.csv", self.events)
        self.pending[self.mid] = dict(match_id=self.mid, home_score=self.match["home_score"],
                                     away_score=self.match["away_score"], source_url=self.match["source_url"],
                                     checked_on="2026-11-09", source_sha256="0" * 64,
                                     reason="official_scorers_not_published")
        self.save_pending()

    def save_pending(self):
        write(self.data / PENDING_FILE, list(self.pending.values()), PENDING_FIELDS)

    def test_registered_missing_record_reports_separate_totals(self):
        result = check_matches(self.data)
        self.assertEqual(result["scorer_completeness"], "HOLD")
        self.assertEqual(result["score_goals"], result["goals"] + result["pending_goals"])
        self.assertEqual(result["pending_matches"], len(self.pending))

    def test_missing_registration_fails(self):
        del self.pending[self.mid]
        self.save_pending()
        with self.assertRaisesRegex(ValueError, "nonzero"):
            check_matches(self.data)

    def test_changed_score_or_unknown_id_cannot_be_exempted(self):
        self.pending[self.mid]["home_score"] = str(int(self.match["home_score"]) + 1)
        self.save_pending()
        with self.assertRaisesRegex(ValueError, "evidence differs"):
            check_matches(self.data)
        self.pending["unknown"] = dict(self.pending.pop(self.mid), match_id="unknown")
        self.save_pending()
        with self.assertRaisesRegex(ValueError, "not a played"):
            check_matches(self.data)

    def test_parse_error_is_not_treated_as_unpublished(self):
        self.events[-1]["note"] = "scorers_block_empty"
        write(self.data / "goal_events_2026.csv", self.events)
        with self.assertRaisesRegex(ValueError, "unsupported zero"):
            check_matches(self.data)

    def test_duplicate_diagnostic_fails(self):
        write(self.data / "goal_events_2026.csv", self.events + [self.events[-1]])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            check_matches(self.data)

    def test_registered_entry_cannot_hide_positive_events(self):
        write(self.data / "goal_events_2026.csv", self.original_events)
        with self.assertRaisesRegex(ValueError, "must be resolved"):
            check_matches(self.data)

    def test_result_card_distinguishes_missing_from_zero(self):
        rows = renderer.load_match_result_datasets(self.data)["2026_results_all"].rows
        row = next(r for r in rows if r["match_id"] == self.mid)
        page = renderer.build_result_cards([row])
        scoring_sides = sum(int(row[s + "_score"]) > 0 for s in ("home", "away"))
        self.assertEqual(page.count("得点者は公式記録の掲載待ちです"), scoring_sides)
        self.assertEqual(page.count("得点者なし"), 2 - scoring_sides)

    def test_resolved_official_records_are_imported_on_next_update(self):
        # Fake saved source responses in a temporary workspace; no network.
        raw = self.root / "raw"
        raw.mkdir()
        masters = read_csv(self.data / "matches_2026.csv")
        by_url = {r["source_url"]: r for r in masters}
        for n in (1, 2):
            (raw / f"div{n}.html").write_text(str(n), encoding="utf-8")
        for r in masters:
            if r["status"] == "played":
                (raw / (r["match_id"] + ".html")).write_text(r["match_id"], encoding="utf-8")
        fixtures = [updater.fixtures.Fixture(**r) for r in read_csv(self.data / "next_fixtures_2026.csv")]
        _, aliases = updater.standings.load_names()
        def listing(page, division, *args):
            return [dict(r, **{key: aliases.get((division, r[key]), r[key]) for key in ("home_team", "away_team")})
                    for r in masters if r["division"] == division]
        def official_events(match, body):
            return [updater.goal_events.GoalEvent(**dict(r, goals=int(r["goals"])))
                    for r in self.original_events if r["match_id"] == match.match_id]
        with patch.object(updater, "ROOT", self.root), \
             patch.object(updater, "parse_matches", side_effect=listing), \
             patch.object(updater.match_pages, "parse_match_page", side_effect=lambda url, body: by_url[url]), \
             patch.object(updater.goal_events, "parse_goal_events_for_match", side_effect=official_events), \
             patch.object(updater.fixtures, "parse_page", side_effect=lambda page, division, *a: [f for f in fixtures if f.division == division]):
            report = updater.prepare(raw, self.root / "candidate", date(2026, 11, 9))
        self.assertIn(self.mid, report["resolved_pending"])
        self.assertNotIn(self.mid, read_pending_scorers(self.root / "candidate"))
        restored = [r for r in read_csv(self.root / "candidate/goal_events_2026.csv") if r["match_id"] == self.mid]
        self.assertEqual(restored, [r for r in self.original_events if r["match_id"] == self.mid])
        check_matches(self.root / "candidate")


if __name__ == "__main__":
    unittest.main()
