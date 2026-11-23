"""Offline regression tests for all league calendar and report completion rules."""
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import adaptive_monitor as am
import recover_reports as recovery


class AdaptiveLeagueTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 11, 23)
        self.now = datetime(2026, 11, 23, 14, tzinfo=am.ET)

    def sample(self, league, game_date="2026-11-22", status=None, **links):
        statuses = {"NBA": "Final", "WNBA": "Final",
                    "NHL": "OFF", "MLB": "Final"}
        return {"id": "1234567", "date": game_date,
                "label": "Team A @ Team B",
                "status": status or statuses[league], **links}

    def test_completed_reports_have_league_specific_requirements(self):
        for league in am.SETTINGS:
            with self.subTest(league=league):
                data = self.sample(league)
                self.assertTrue(am.completed(data, league))
                self.assertTrue(am.reports_missing(data, league))
        self.assertFalse(am.reports_missing(
            self.sample("NHL", gs_url="https://www.nhl.com/GS.htm",
                        es_url="https://www.nhl.com/ES.htm"), "NHL"))
        self.assertTrue(am.reports_missing(
            self.sample("NHL", gs_url="https://www.nhl.com/GS.htm"), "NHL"))
        self.assertFalse(am.reports_missing(
            self.sample("MLB", box_url="https://www.mlb.com/gameday/1/box-score",
                        plays_url="https://www.mlb.com/gameday/1/play-by-play"), "MLB"))

    def test_postponed_and_suspended_are_not_overdue(self):
        for league in am.SETTINGS:
            self.assertFalse(am.completed(self.sample(league, status="Postponed"), league))
        self.assertFalse(am.completed(self.sample("MLB", status="Suspended"), "MLB"))
        self.assertFalse(am.completed(self.sample("NHL", status="FUT"), "NHL"))

    def test_would_not_restart_wnba_for_september_gap_in_november(self):
        with patch.object(am, "load") as mocked:
            mocked.side_effect = lambda path: {
                "wnba/archive.json": {"games": [
                    self.sample("WNBA", game_date="2026-09-20")]},
                "wnba/calendar.json": {"game_days": []}
            }[str(path)]
            self.assertEqual(len(am.outstanding("WNBA", self.today)), 0)
            self.assertEqual(len(am.outstanding("WNBA", self.today, max_age=None)), 1)
            self.assertFalse(am.should_poll("WNBA", self.now))

    def test_recent_unverified_pdf_continues_after_three_am(self):
        for league in am.SETTINGS:
            with self.subTest(league=league):
                cfg = am.setting(league)
                def data(path):
                    if str(path) == cfg["calendar"]:
                        return {"game_days": []}
                    return {"games": [self.sample(league)]}
                with patch.object(am, "load", side_effect=data):
                    self.assertTrue(am.should_poll(league, self.now))

    def test_explicit_game_day_and_next_morning_cutoff(self):
        for league in am.SETTINGS:
            cfg = am.setting(league)
            def data(path):
                if str(path) == cfg["calendar"]:
                    return {"game_days": ["2026-11-23"]}
                return {"games": []}
            with patch.object(am, "load", side_effect=data):
                self.assertTrue(am.should_poll(
                    league, datetime(2026, 11, 24, 2, 59, tzinfo=am.ET)))
                self.assertFalse(am.should_poll(
                    league, datetime(2026, 11, 24, 3, tzinfo=am.ET)))

    def test_only_old_gaps_enter_daily_recovery(self):
        league = "WNBA"
        with patch.object(recovery, "outstanding") as result:
            result.return_value = [
                self.sample(league, "2026-09-22"),
                self.sample(league, "2026-11-21"),
            ]
            old = recovery.candidates(league, "stale", self.today)
            recent = recovery.candidates(league, "recent", self.today)
            self.assertEqual([g["date"] for g in old], ["2026-09-22"])
            self.assertEqual([g["date"] for g in recent], ["2026-11-21"])

    def test_heartbeat_throttles_commits_on_unchanged_status(self):
        league = "NBA"
        with tempfile.TemporaryDirectory() as folder:
            status = Path(folder) / "status.json"
            with patch.object(am, "setting", return_value={"status": str(status)}), \
                    patch.object(am, "outstanding", return_value=[]):
                am.heartbeat(league, now=self.now)
                first = status.read_text()
                am.heartbeat(league, now=self.now + timedelta(minutes=10))
                self.assertEqual(status.read_text(), first)
                am.heartbeat(league, now=self.now + timedelta(minutes=41))
                self.assertNotEqual(status.read_text(), first)

    def test_guard_without_calendar_is_not_a_silent_offseason_skip(self):
        with patch.object(am, "load", side_effect=FileNotFoundError):
            with self.assertRaises(FileNotFoundError):
                am.should_poll("NBA", self.now)

    def test_mlb_recover_assigns_only_expected_official_game_pages(self):
        data = self.sample("MLB")
        changed = recovery.recover_one("MLB", data, object())
        self.assertTrue(changed)
        self.assertEqual(data["box_url"], "https://www.mlb.com/gameday/1234567/box-score")
        self.assertEqual(data["plays_url"], "https://www.mlb.com/gameday/1234567/play-by-play")

    def test_dst_uses_eastern_time(self):
        self.assertEqual(am.ET.key, "America/New_York")


if __name__ == "__main__":
    unittest.main()
