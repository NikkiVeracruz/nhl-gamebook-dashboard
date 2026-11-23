"""A backup must only run when an active league's monitor is stale."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import adaptive_watchdog as wd


class AdaptiveWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,11,23,14,tzinfo=timezone.utc)

    def test_no_backup_when_schedule_is_intentionally_idle(self):
        with patch.object(wd,"should_poll",return_value=False):
            with patch.object(wd,"load") as read:
                needed, reason=wd.needs_backup("WNBA",self.now)
                self.assertFalse(needed)
                read.assert_not_called()

    def test_backup_when_active_monitor_never_checked(self):
        with patch.object(wd,"should_poll",return_value=True), patch.object(wd,"load",return_value={"last_checked_at":None}):
            needed,_=wd.needs_backup("NBA",self.now)
            self.assertTrue(needed)

    def test_no_backup_for_healthy_poll_heartbeat(self):
        with patch.object(wd,"should_poll",return_value=True), patch.object(wd,"load",return_value={"last_checked_at":(self.now-timedelta(minutes=40)).isoformat()}):
            needed,_=wd.needs_backup("NHL",self.now)
            self.assertFalse(needed)

    def test_backup_when_genuine_monitor_stall(self):
        with patch.object(wd,"should_poll",return_value=True), patch.object(wd,"load",return_value={"last_checked_at":(self.now-timedelta(minutes=125)).isoformat()}):
            needed,_=wd.needs_backup("MLB",self.now)
            self.assertTrue(needed)

    def test_rejects_invalid_or_future_heartbeat(self):
        with patch.object(wd,"should_poll",return_value=True):
            for value in ["not-a-date",(self.now+timedelta(hours=1)).isoformat()]:
                with patch.object(wd,"load",return_value={"last_checked_at":value}):
                    with self.assertRaises(ValueError):
                        wd.needs_backup("NBA",self.now)


if __name__=="__main__":
    unittest.main()
