#!/usr/bin/env python3
"""Offline tests for the prepublication archive gate."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from archive_integrity_gate import verify_change
from archive import ArchiveIntegrityError


def entry(key, pdf=None):
    record = {"id": key, "date": "2026-11-22", "label": key}
    if pdf is not None:
        record["pdf_url"] = pdf
    return record


class ArchiveGateTests(unittest.TestCase):
    def test_identical_archive_allowed(self):
        data = {"games": [entry("1")]}
        self.assertEqual(verify_change(data, data), (1, 1))

    def test_added_games_allowed(self):
        self.assertEqual(
            verify_change({"games": [entry("1")]},
                          {"games": [entry("1"), entry("2")]}),
            (1, 2),
        )

    def test_missing_historical_game_blocked(self):
        with self.assertRaisesRegex(ArchiveIntegrityError, "remove 1 archived"):
            verify_change({"games": [entry("1"), entry("2")]},
                          {"games": [entry("2")]})

    def test_removal_of_saved_document_blocked(self):
        with self.assertRaisesRegex(ArchiveIntegrityError, "remove saved pdf_url"):
            verify_change({"games": [entry("1", "https://example.org/book.pdf")]},
                          {"games": [entry("1")]})

    def test_verified_link_replacement_is_permitted(self):
        self.assertEqual(
            verify_change({"games": [entry("1", "https://a.example/book.pdf")]},
                          {"games": [entry("1", "https://b.example/book.pdf")]}),
            (1, 1),
        )

    def test_invalid_candidate_blocked(self):
        with self.assertRaises(ArchiveIntegrityError):
            verify_change({"games": [entry("1")]}, {"games": "bad"})

    def test_duplicate_candidate_blocked(self):
        with self.assertRaises(ArchiveIntegrityError):
            verify_change({"games": [entry("1")]},
                          {"games": [entry("1"), entry("1")]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
