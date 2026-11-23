"""Pure forward-only policy tests; never writes a tracked archive."""
import tempfile
import unittest
from pathlib import Path

from forward_only import ROOT, ARCHIVES, complete, configured, filter_archive


class ForwardOnlyTests(unittest.TestCase):
    def fixture(self, league, date="2026-11-23", status="Final", complete_data=True):
        game = {"id": "test-game", "date": date, "label": "Away @ Home", "status": status}
        if complete_data:
            if league == "NFL":
                game["pdf_url"] = "https://static.www.nfl.com/test.pdf"
            elif league in ("NBA", "WNBA"):
                game["pdf_url"] = "https://statsdmz.nba.com/test.pdf"
            elif league == "NHL":
                game.update(gs_url="https://www.nhl.com/gs", es_url="https://www.nhl.com/es")
            elif league == "MLB":
                game.update(link_verification="verified_api",
                            box_url="https://www.mlb.com/box",
                            plays_url="https://www.mlb.com/plays")
        return game

    def test_stored_archive_contains_only_complete_new_games(self):
        for filename, policy in ARCHIVES.items():
            with self.subTest(filename=filename):
                league = policy["league"]
                ready = self.fixture(league)
                old = self.fixture(league, date="2025-10-10")
                old["id"] = "old-id"
                incomplete = self.fixture(league, complete_data=False)
                incomplete["id"] = "missing-link"
                scheduled = self.fixture(league, status="Scheduled")
                scheduled["id"] = "scheduled"
                filtered = filter_archive(ROOT / filename,
                                          {"games": [ready, old, incomplete, scheduled]})
                self.assertEqual(filtered["games"], [ready])
                self.assertEqual(complete(ready, league), True)

    def test_nhl_requires_both_reports(self):
        if "NHL" in [p["league"] for p in ARCHIVES.values()]:
            one = self.fixture("NHL")
            one.pop("es_url")
            self.assertFalse(complete(one, "NHL"))

    def test_mlb_requires_actual_api_verification(self):
        if "MLB" in [p["league"] for p in ARCHIVES.values()]:
            one = self.fixture("MLB")
            one["link_verification"] = "needs_review"
            self.assertFalse(complete(one, "MLB"))

    def test_temp_archives_are_never_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "archive.json"
            original = {"games": [{"id": "old", "date": "2025-01-01"}]}
            self.assertIs(filter_archive(f, original), original)
            self.assertIsNone(configured(f))

    def test_duplicates_fail_closed(self):
        for filename, policy in ARCHIVES.items():
            item = self.fixture(policy["league"])
            with self.assertRaises(ValueError):
                filter_archive(ROOT / filename, {"games": [item, item]})


if __name__ == "__main__":
    unittest.main()
