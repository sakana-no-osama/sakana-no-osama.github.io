"""Regression cases for postponements and unpublished official venue fields."""
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_next_fixtures_2026 import parse_page, HoldError
from official_division import parse_matches

TEAMS = {f"Team{i}" for i in range(8)}


def game(mid, when, home, away, venue="Ground"):
    stadium = f'<div class="match-slim__stadium">{venue}</div>' if venue else ""
    return f'''<div class="anwp-fl-game match-list__item game-status-0" data-fl-game-datetime="{when}T12:00:00+09:00">
<span class="match-slim__time match__time-formatted">12時00分</span>
<div class="match-slim__team-home-title">{home}</div><div class="match-slim__team-away-title">{away}</div>
<span class="match-slim__scores-home">-</span><span class="match-slim__scores-away">-</span>
{stadium}<a class="anwp-link-cover" href="https://u15.kantolsl.com/2026/div1/m{mid:02d}/"></a></div>'''


def page(missing_next_venue=False):
    result = '<div class="sec">後期・第３節</div>'
    result += "".join(game(i+1, "2026-11-21", f"Team{i*2}", f"Team{i*2+1}") for i in range(4))
    result += '<div class="sec">後期・第４節</div>'
    result += "".join(game(i+5, "2026-10-03", f"Team{i*2}", f"Team{i*2+1}",
                           "" if missing_next_venue and i == 0 else "Ground") for i in range(4))
    result += '<div class="sec">後期・第５節</div>'
    result += game(9, "2026-11-28", "Team0", "Team1", "")
    return result


class OfficialSources(unittest.TestCase):
    def test_postponed_round_does_not_hide_earlier_future_round(self):
        rows = parse_page(page(), "1部", "source", date(2026, 10, 2), TEAMS)
        self.assertEqual([r.match_id for r in rows], [f"2026_D1_m{i:02d}" for i in range(5, 9)])
        self.assertTrue(all(r.match_date == "2026-10-03" for r in rows))

    def test_unpublished_venue_is_blank_with_explicit_note(self):
        rows = parse_page(page(True), "1部", "source", date(2026, 10, 2), TEAMS)
        self.assertEqual(rows[0].venue, "")
        self.assertEqual(rows[0].note, "venue_not_published")

    def test_listing_preserves_missing_venue_and_scheduled_scores(self):
        rows = parse_matches(page(True), "1部", "2026-10-02T12:00:00+09:00", TEAMS)
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[4]["note"], "venue_not_published")
        self.assertTrue(all(r["home_score"] == r["away_score"] == "" for r in rows))

    def test_unknown_team_fails(self):
        with self.assertRaises(ValueError):
            parse_matches(page().replace("Team0", "Unknown"), "1部", "now", TEAMS)

    def test_wrong_division_link_fails(self):
        with self.assertRaises(ValueError):
            parse_matches(page().replace("/div1/", "/div2/"), "1部", "now", TEAMS)

    def test_duplicate_official_match_fails(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_matches(page().replace("/m02/", "/m01/"), "1部", "now", TEAMS)


if __name__ == "__main__":
    unittest.main()
