"""Regression tests use temporary copies; no network and no writes to real data."""
import contextlib
import csv
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tools")]
from ranking_checks import check_matches, check_rankings, read_csv
from workflow_io import atomic_text_writer
import build_all_years_ranking_html as renderer
import build_goal_events_2026 as events
import build_matches_2026_from_sources as matches
import build_preview
from preview_checks import check_page


class WorkflowSafety(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="kanto-test-")
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.data = self.work / "data"
        shutil.copytree(ROOT / "data", self.data)

    def edit(self, name, change):
        path = self.data / name
        rows = read_csv(path)
        fields = list(rows[0])
        change(rows)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_saved_data_pass(self):
        self.assertEqual(check_rankings(self.data)["all"], check_matches(self.data)["goals"])

    def test_reassigned_scorer_with_same_total_fails(self):
        self.edit("goal_ranking_2026_all.csv", lambda rows: rows[0].update(player="別の選手"))
        with self.assertRaises(ValueError):
            check_rankings(self.data)

    def test_wrong_rank_fails(self):
        self.edit("goal_ranking_2026_all.csv", lambda rows: rows[0].update(rank="2"))
        with self.assertRaises(ValueError):
            check_rankings(self.data)

    def test_invalid_number_fails(self):
        self.edit("goal_ranking_2026_all.csv", lambda rows: rows[0].update(goals="-1"))
        with self.assertRaises(ValueError):
            check_rankings(self.data)

    def test_wrong_division_fails(self):
        self.edit("goal_events_2026.csv", lambda rows: rows[0].update(division="3部"))
        with self.assertRaises(ValueError):
            check_rankings(self.data)

    def test_opponents_swapped_with_same_match_total_fails(self):
        def swap(rows):
            rows[0]["team"], rows[1]["team"] = rows[1]["team"], rows[0]["team"]
        self.edit("goal_events_2026.csv", swap)
        with self.assertRaisesRegex(ValueError, "score/scorers"):
            check_matches(self.data)

    def test_stale_played_subset_fails(self):
        self.edit("matches_2026_played.csv", lambda rows: rows.pop())
        with self.assertRaisesRegex(ValueError, "subset"):
            check_matches(self.data)

    def test_unknown_event_and_duplicate_fail(self):
        self.edit("goal_events_2026.csv", lambda rows: rows.append(dict(rows[0])))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            check_matches(self.data)

    def test_event_date_mismatch_fails(self):
        self.edit("goal_events_2026.csv", lambda rows: rows[0].update(match_date="2000-01-01"))
        with self.assertRaisesRegex(ValueError, "date"):
            check_matches(self.data)

    def test_atomic_write_failure_keeps_previous_file(self):
        output = self.work / "output.csv"
        output.write_text("verified", encoding="utf-8")
        with self.assertRaises(OSError):
            with atomic_text_writer(output) as handle:
                handle.write("incomplete")
                raise OSError("simulated disk error")
        self.assertEqual(output.read_text(), "verified")
        self.assertEqual(list(self.work.glob(".writing-*")), [])

    def test_fetch_failure_preserves_event_file(self):
        output = self.data / "goal_events_2026.csv"
        before = output.read_bytes()
        with patch.object(events, "fetch_text", side_effect=URLError("offline")):
            with contextlib.redirect_stderr(io.StringIO()):
                code = events.main(["events", str(self.data / "matches_2026_played.csv"), str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), before)

    def test_fetch_failure_preserves_match_file(self):
        output = self.data / "matches_2026.csv"
        before = output.read_bytes()
        with patch.object(matches, "parse_match_page", side_effect=URLError("offline")):
            with contextlib.redirect_stderr(io.StringIO()):
                code = matches.main(["matches", str(self.data / "match_sources_2026.csv"), str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), before)

    def test_regeneration_from_other_directory_matches_all_six_csvs(self):
        for kind in ("goal", "team"):
            process = subprocess.run([sys.executable, "-B", str(ROOT / "scripts" / f"build_{kind}_ranking_2026.py"),
                                      str(self.data / "goal_events_2026.csv"), str(self.work)],
                                     cwd=self.work, capture_output=True)
            self.assertEqual(process.returncode, 0, process.stderr)
            for scope in ("all", "div1", "div2"):
                name = f"{kind}_ranking_2026_{scope}.csv"
                self.assertEqual(read_csv(self.work / name), read_csv(self.data / name))

    def test_failed_verifier_returns_nonzero_exit(self):
        self.edit("goal_ranking_2026_all.csv", lambda rows: rows[0].update(rank="999"))
        process = subprocess.run([sys.executable, "-B", str(ROOT / "tests" / "verify_2026_rankings.py"),
                                  "--data-dir", str(self.data)], capture_output=True)
        self.assertEqual(process.returncode, 1)
        self.assertIn(b"VERDICT=FAIL", process.stdout)

    def test_fetch_review_preserves_previous_matches(self):
        output = self.data / "matches_2026.csv"
        before = output.read_bytes()
        rows = [matches.MatchRow(**row) for row in read_csv(output)]
        with patch.object(matches, "build_rows", return_value=rows):
            with contextlib.redirect_stderr(io.StringIO()):
                code = matches.main(["matches", str(self.data / "match_sources_2026.csv"), str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), before)

    def test_disappearing_played_match_preserves_previous_matches(self):
        output = self.data / "matches_2026.csv"
        before = output.read_bytes()
        rows = [matches.MatchRow(**row) for row in read_csv(output) if row["status"] == "played"][1:]
        with patch.object(matches, "build_rows", return_value=rows):
            with contextlib.redirect_stderr(io.StringIO()):
                code = matches.main(["matches", str(self.data / "match_sources_2026.csv"), str(output)])
        self.assertEqual(code, 2)
        self.assertEqual(output.read_bytes(), before)

    def test_html_and_drawer_match_and_tamper_fails(self):
        datasets = renderer.load_datasets(self.data)
        page = renderer.build_html(datasets)
        check_page(page, datasets)
        changed = page.replace('<td class="num">7</td>', '<td class="num">999</td>', 1)
        self.assertNotEqual(changed, page)
        with self.assertRaisesRegex(ValueError, "table mismatch"):
            check_page(changed, datasets)

    def test_json_preserves_ampersands_and_escapes_script_end(self):
        row = {"rank": "1", "player": "A&B </script>", "team": "T", "goals": "1", "match_count": "1"}
        payload = renderer.dataset_json({"x": renderer.Dataset("2026", "player", "all", [row], "test")})
        self.assertNotIn("</script>", payload)
        self.assertEqual(json.loads(payload)["x"][0], row)

    def test_cache_validates_output_hash_and_never_changes_source_data(self):
        before = {p.name: p.read_bytes() for p in (ROOT / "data").glob("*.csv")}
        output = self.work / "preview"
        first = build_preview.build(output)
        second = build_preview.build(output)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        (output / "index.html").write_text("tampered", encoding="utf-8")
        third = build_preview.build(output)
        self.assertFalse(third["cached"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in (ROOT / "data").glob("*.csv")})

    def test_failed_build_keeps_last_preview(self):
        output = self.work / "preview"
        build_preview.build(output)
        before = (output / "index.html").read_bytes()
        with patch.object(build_preview, "check_matches", side_effect=ValueError("broken source")):
            with self.assertRaises(ValueError):
                build_preview.build(output, force=True)
        self.assertEqual((output / "index.html").read_bytes(), before)

    def test_preview_cannot_overwrite_public_index(self):
        with self.assertRaises(ValueError):
            build_preview.build(ROOT)


if __name__ == "__main__":
    unittest.main()
