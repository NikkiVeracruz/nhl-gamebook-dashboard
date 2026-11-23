#!/usr/bin/env python3
"""Behavioral archive-integrity tests. Never writes the tracked archive."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import archive


def game(game_id, day="2026-11-22", **kwargs):
    return {"id": str(game_id), "date": day, "label": f"Game {game_id}", **kwargs}


def payload(*games):
    return {"games": list(games)}


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.live = self.directory / "gamebooks.json"
        self.history = self.directory / "archive.json"
        self.old_games = payload(
            game("old-one", "2026-11-20", pdf_url="https://official.example/old.pdf"),
            game("old-two", "2026-11-21"),
        )
        self.put(self.live, payload(game("old-one", pdf_url=None), game("new-one")))
        self.put(self.history, self.old_games)

    def put(self, path, contents):
        path.write_text(json.dumps(contents), encoding="utf-8")

    def run_archive(self):
        with patch.object(archive, "LIVE", self.live), patch.object(archive, "ARCHIVE", self.history):
            archive.main()

    def assert_unchanged_on_failure(self):
        before = self.history.read_bytes()
        with self.assertRaises(archive.ArchiveIntegrityError):
            self.run_archive()
        self.assertEqual(before, self.history.read_bytes())

    def test_preserves_old_games_and_report_links(self):
        self.run_archive()
        actual = json.loads(self.history.read_text())["games"]
        indexed = {g["id"]: g for g in actual}
        self.assertEqual(len(indexed), 3)
        self.assertEqual(indexed["old-one"]["pdf_url"], "https://official.example/old.pdf")
        self.assertIn("old-two", indexed)
        self.assertIn("new-one", indexed)

    def test_empty_offseason_feed_never_removes_archive(self):
        self.put(self.live, {"offseason": True, "games": []})
        self.run_archive()
        self.assertEqual(len(json.loads(self.history.read_text())["games"]), 2)

    def test_blank_report_link_does_not_erase_verified_link(self):
        self.put(self.live, payload(game("old-one", pdf_url="")))
        self.run_archive()
        indexed = {g["id"]: g for g in json.loads(self.history.read_text())["games"]}
        self.assertEqual(indexed["old-one"]["pdf_url"], "https://official.example/old.pdf")

    def test_corrupt_archive_is_never_overwritten(self):
        self.history.write_text('{"games": [', encoding="utf-8")
        self.assert_unchanged_on_failure()

    def test_missing_archive_is_not_silently_initialized(self):
        self.history.unlink()
        with self.assertRaises(archive.ArchiveIntegrityError):
            self.run_archive()
        self.assertFalse(self.history.exists())

    def test_wrong_archive_shape_is_rejected(self):
        self.put(self.history, {"games": {"old-one": {}}})
        self.assert_unchanged_on_failure()

    def test_bad_historical_game_is_rejected(self):
        self.put(self.history, payload({"id": "old-one"}))
        self.assert_unchanged_on_failure()

    def test_duplicate_historical_ids_are_rejected(self):
        self.put(self.history, payload(game("dup"), game("dup")))
        self.assert_unchanged_on_failure()

    def test_duplicate_live_ids_are_rejected(self):
        self.put(self.live, payload(game("dup"), game("dup")))
        self.assert_unchanged_on_failure()

    def test_malformed_live_feed_is_rejected(self):
        self.live.write_text("not JSON", encoding="utf-8")
        self.assert_unchanged_on_failure()

    def test_atomic_replacement_failure_keeps_previous_bytes(self):
        original = self.history.read_bytes()
        with patch.object(archive.os, "replace", side_effect=OSError("simulated disk error")):
            with self.assertRaises(OSError):
                self.run_archive()
        self.assertEqual(original, self.history.read_bytes())
        self.assertFalse(list(self.directory.glob(".archive.json.*.tmp")))

    def test_atomic_write_leaves_no_temp_files(self):
        self.run_archive()
        self.assertFalse(list(self.directory.glob(".archive.json.*.tmp")))

    def test_real_repository_archive_is_safe_to_merge(self):
        # Use the checked-out repository's actual archive and live feed.
        # Copy historical bytes into a temporary path to prevent ANY data writes.
        root = Path(__file__).resolve().parents[1]
        historical = (root / "archive.json").read_bytes()
        self.history.write_bytes(historical)
        self.live.write_bytes((root / "gamebooks.json").read_bytes())
        before = json.loads(historical)
        before_ids = set(archive.validate_games(before, "Repository archive"))
        self.run_archive()
        after = json.loads(self.history.read_text())
        after_ids = set(archive.validate_games(after, "Merged preview"))
        self.assertTrue(before_ids.issubset(after_ids))
        self.assertGreaterEqual(len(after["games"]), len(before["games"]))
        self.assertEqual(historical, (root / "archive.json").read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
