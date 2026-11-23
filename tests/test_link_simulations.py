#!/usr/bin/env python3
"""Offline end-to-end regression simulations for official report retention.

Runs monitor.main() with a temporary JSON output and mocked league responses.
No network calls and no writes to production files.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import monitor

IS_NBA = hasattr(monitor, "PDF_BASE")
KEY = "pdf_url" if IS_NBA else "gs_url"
OUTPUT_NAME = "OUTPUT" if IS_NBA else "OUT"
FETCH_NAME = "games_on" if IS_NBA else "get_games"
GID = "401999999" if IS_NBA else "2026020999"
OTHER_ID = "401999998" if IS_NBA else "2026020998"
LABEL = "Away @ Home"

def official_url(day, gid=GID):
    if IS_NBA:
        return f"{monitor.PDF_BASE}/{day.replace('-', '')}/{day.replace('-', '')}_BOSNYK_book.pdf"
    return monitor.report_url(gid, "GS")

def game(day, gid=GID, url=None, label=LABEL):
    result = {"id": gid, "date": day, "label": label, "status": "Final"}
    if url:
        result[KEY] = url
    return result

class RetentionSimulations(unittest.TestCase):
    def run_monitor(self, previous, current, second=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gamebooks.json"
            path.write_text(json.dumps({"games": previous}), encoding="utf-8")
            # Use the monitor's own current reporting dates to avoid timezone drift.
            from datetime import datetime, timedelta
            today = (datetime.now(monitor.ET) - timedelta(hours=3)).date()
            days = [(today - timedelta(days=1)).isoformat(), today.isoformat()]
            previous = [dict(g, date=days[0]) for g in previous]
            current = [dict(g, date=days[0]) for g in current]
            second = [] if second is None else [dict(g, date=days[1]) for g in second]
            for item in previous:
                if item.get(KEY):
                    item[KEY] = official_url(days[0], item["id"]) if item[KEY] == "__OFFICIAL__" else item[KEY]
            for item in current:
                if item.get(KEY):
                    item[KEY] = official_url(days[0], item["id"]) if item[KEY] == "__OFFICIAL__" else item[KEY]
            path.write_text(json.dumps({"games": previous}), encoding="utf-8")
            with patch.object(monitor, OUTPUT_NAME, path), patch.object(monitor, FETCH_NAME, side_effect=[current, second]):
                monitor.main()
            return json.loads(path.read_text(encoding="utf-8"))["games"], days[0]

    def test_transient_outage_preserves_verified_link(self):
        result, day = self.run_monitor([game("placeholder", url="__OFFICIAL__")], [game("placeholder")])
        self.assertEqual(result[0][KEY], official_url(day))

    def test_newly_verified_link_still_appears(self):
        result, day = self.run_monitor([], [game("placeholder", url="__OFFICIAL__")])
        self.assertEqual(result[0][KEY], official_url(day))

    def test_wrong_game_id_does_not_inherit_link(self):
        result, _ = self.run_monitor([game("placeholder", url="__OFFICIAL__")], [game("placeholder", gid=OTHER_ID)])
        target = next(g for g in result if g["id"] == OTHER_ID)
        self.assertNotIn(KEY, target)

    def test_malformed_old_url_not_restored(self):
        result, _ = self.run_monitor([game("placeholder", url="https://untrusted.example/report.pdf")], [game("placeholder")])
        target = next(g for g in result if g["id"] == GID)
        self.assertNotIn(KEY, target)

    def test_old_date_not_restored(self):
        from datetime import datetime, timedelta
        today = (datetime.now(monitor.ET) - timedelta(hours=3)).date()
        old_date = (today - timedelta(days=3)).isoformat()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gamebooks.json"
            path.write_text(json.dumps({"games": [game(old_date, url=official_url(old_date))]}), encoding="utf-8")
            current_day = (today - timedelta(days=1)).isoformat()
            with patch.object(monitor, OUTPUT_NAME, path), patch.object(monitor, FETCH_NAME, side_effect=[[game(current_day)], []]):
                monitor.main()
            published = json.loads(path.read_text(encoding="utf-8"))["games"]
            self.assertNotIn(KEY, published[0])

if __name__ == "__main__":
    unittest.main(verbosity=2)
