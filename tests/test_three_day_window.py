"""Verify exactly three Eastern dates and protected archive rollover."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import archive
import three_day_window as win


class ThreeDayWindowTests(unittest.TestCase):
    def test_before_three_am_retains_prior_reporting_day(self):
        before = datetime(2026, 11, 23, 7, 59, tzinfo=timezone.utc)
        self.assertEqual(
            [x.isoformat() for x in win.three_days(before)],
            ["2026-11-21", "2026-11-22", "2026-11-23"],
        )

    def test_three_am_rolls_forward_exactly_one_date(self):
        at = datetime(2026, 11, 23, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(
            [x.isoformat() for x in win.three_days(at)],
            ["2026-11-22", "2026-11-23", "2026-11-24"],
        )

    def test_dst_start_keeps_three_am_local(self):
        before = datetime(2027, 3, 14, 6, 59, tzinfo=timezone.utc)
        after = datetime(2027, 3, 14, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(win.reporting_day(before), date(2027, 3, 13))
        self.assertEqual(win.reporting_day(after), date(2027, 3, 14))

    def test_dst_end_keeps_three_am_local(self):
        before = datetime(2026, 11, 1, 7, 59, tzinfo=timezone.utc)
        after = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(win.reporting_day(before), date(2026, 10, 31))
        self.assertEqual(win.reporting_day(after), date(2026, 11, 1))

    def test_year_and_month_boundary(self):
        now = datetime(2027, 1, 1, 14, tzinfo=timezone.utc)
        self.assertEqual(
            [d.isoformat() for d in win.three_days(now)],
            ["2026-12-31", "2027-01-01", "2027-01-02"],
        )

    def test_naive_datetime_rejected(self):
        with self.assertRaises(ValueError):
            win.three_days(datetime(2026, 11, 23, 3))

    def test_archive_before_removing_oldest_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed = root / "gamebooks.json"
            saved = root / "archive.json"
            old = {"id": "old", "date": "2026-11-21", "label": "Old game",
                   "pdf_url": "https://statsdmz.nba.com/pdfs/old.pdf"}
            keep = {"id": "keep", "date": "2026-11-22", "label": "Today"}
            feed.write_text(json.dumps({"games": [old, keep]}))
            saved.write_text(json.dumps({"games": [
                {"id": "previous", "date": "2026-11-20", "label": "Previous game",
                 "pdf_url": "https://statsdmz.nba.com/pdfs/previous.pdf"}
            ]}))
            days = [date(2026, 11, 22), date(2026, 11, 23), date(2026, 11, 24)]
            self.assertEqual(
                win.archive_outgoing_games(feed, saved, days, archive), 1)
            archived = json.loads(saved.read_text())
            ids = {g["id"] for g in archived["games"]}
            self.assertEqual(ids, {"old", "previous"})
            self.assertEqual(
                next(g for g in archived["games"] if g["id"] == "old")["pdf_url"],
                old["pdf_url"])
            before_second = saved.read_text()
            self.assertEqual(
                win.archive_outgoing_games(feed, saved, days, archive), 1)
            self.assertEqual(saved.read_text(), before_second)

    def test_corrupt_archive_refuses_feed_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            feed, saved = root / "gamebooks.json", root / "archive.json"
            feed.write_text(json.dumps({"games": [
                {"id": "old", "date": "2026-11-21", "label": "Old game"}
            ]}))
            saved.write_text("{ invalid json")
            original = feed.read_text()
            days = [date(2026, 11, 22), date(2026, 11, 23), date(2026, 11, 24)]
            with self.assertRaises(archive.ArchiveIntegrityError):
                win.archive_outgoing_games(feed, saved, days, archive)
            self.assertEqual(feed.read_text(), original)


if __name__ == "__main__":
    unittest.main()
