"""Separate international hockey from NHL, preserve old game records."""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import adaptive_monitor
import competition_policy as policy
import monitor


class NHLCompetitionTests(unittest.TestCase):
    def test_known_nhl_and_non_nhl_types(self):
        self.assertEqual(policy.competition("2025090001"), "international_hockey")
        self.assertEqual(policy.competition("2026010044"), "nhl_preseason")
        self.assertEqual(policy.competition("2026020381"), "nhl_regular_season")
        self.assertEqual(policy.competition("2026030001"), "nhl_playoffs")
        self.assertEqual(policy.competition("2026040001"), "nhl_all_star")
        self.assertFalse(policy.nhl_game("2025090022"))
        self.assertTrue(policy.nhl_game("2026020381"))

    def test_international_events_never_count_as_missing_nhl_reports(self):
        self.assertFalse(adaptive_monitor.reports_missing(
            {"id": "2025090004", "status": "FINAL"}, "NHL"))
        self.assertTrue(adaptive_monitor.reports_missing(
            {"id": "2026010044", "status": "FINAL"}, "NHL"))

    def test_international_events_not_in_current_nhl_schedule(self):
        class Response:
            def raise_for_status(self): pass
            def json(self): return {"games": [
                {"id": 2025090001, "gameState": "FINAL", "awayTeam": {}, "homeTeam": {}},
                {"id": 2026020381, "gameState": "FUT", "awayTeam": {}, "homeTeam": {}},
            ]}
        class Session:
            def get(self, *args, **kwargs): return Response()
        result = monitor.get_games(Session(), date(2026, 11, 23))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "2026020381")

    def test_classification_preserves_olympics_and_flags_preseason(self):
        with tempfile.TemporaryDirectory() as root:
            archive,review=Path(root)/"archive.json",Path(root)/"review.json"
            archive.write_text(json.dumps({"games":[
                {"id":"2025090001","date":"2026-02-11","label":"Sweden @ Italy","status":"FINAL"},
                {"id":"2026010044","date":"2026-09-24","label":"Predators @ Hurricanes","status":"FINAL"},
                {"id":"2025010036","date":"2025-09-25","label":"Flyers @ Capitals","status":"FINAL"},
                {"id":"2026020055","date":"2026-10-14","label":"Hurricanes @ Rangers","status":"OFF",
                 "gs_url":"https://www.nhl.com/scores/htmlreports/20262027/GS020055.HTM",
                 "es_url":"https://www.nhl.com/scores/htmlreports/20262027/ES020055.HTM"},
            ]}))
            result=policy.classify_archive(archive,review)
            saved={g["id"]:g for g in json.loads(archive.read_text())["games"]}
            self.assertEqual(len(saved),4)
            self.assertEqual(saved["2025090001"]["report_requirement"],"not_applicable_nhl")
            self.assertEqual(saved["2026010044"]["report_requirement"],"needs_verification")
            self.assertEqual(len(result["unverified_nhl_preseason_reports"]),1)
            self.assertEqual(result["unverified_nhl_preseason_reports"][0]["date"],"2026-09-24")
            self.assertIn("2025010036",saved)
            self.assertEqual(saved["2026020055"]["gs_url"],
                             "https://www.nhl.com/scores/htmlreports/20262027/GS020055.HTM")
            before=archive.read_text()
            policy.classify_archive(archive,review)
            self.assertEqual(archive.read_text(),before)


if __name__ == "__main__":
    unittest.main()
