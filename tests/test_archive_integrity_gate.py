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


    def test_retry_gate_checks_newer_remote_commit(self):
        # A concurrent publisher may add a game after this run checked out.
        # The candidate must be compared to that NEW upstream baseline too.
        import json
        from unittest.mock import patch
        import archive_integrity_gate as gate

        newer_remote = {"games": [
            entry("1", "https://example.org/old.pdf"),
            entry("another-run-added"),
        ]}
        candidate = {"games": [entry("1", "https://example.org/old.pdf")]}
        with patch.object(gate.subprocess, "check_output", return_value=json.dumps(newer_remote)) as git_show, \
             patch.object(gate, "load_payload", return_value=candidate):
            with self.assertRaisesRegex(ArchiveIntegrityError, "remove 1 archived games"):
                gate.main("archive.json", "FETCH_HEAD")
            git_show.assert_called_once_with(
                ["git", "show", "FETCH_HEAD:archive.json"],
                text=True, stderr=gate.subprocess.PIPE
            )

    def test_retry_gate_uses_wnba_upstream_ref_when_requested(self):
        import json
        from unittest.mock import patch
        import archive_integrity_gate as gate

        current = {"games": [entry("1")]}
        with patch.object(gate.subprocess, "check_output", return_value=json.dumps(current)) as git_show, \
             patch.object(gate, "load_payload", return_value=current):
            gate.main("wnba/archive.json", "origin/main")
            git_show.assert_called_once_with(
                ["git", "show", "origin/main:wnba/archive.json"],
                text=True, stderr=gate.subprocess.PIPE
            )

    def test_publishing_workflows_revalidate_after_rebase(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        paths = [
            (".github/workflows/update.yml", "archive.json", "FETCH_HEAD"),
            (".github/workflows/backfill.yml", "archive.json", "FETCH_HEAD"),
        ]
        if (root / ".github/workflows/wnba-update.yml").exists():
            paths.extend([
                (".github/workflows/wnba-update.yml", "wnba/archive.json", "origin/main"),
                (".github/workflows/wnba-backfill.yml", "wnba/archive.json", "origin/main"),
            ])
        for name, archive_path, git_ref in paths:
            with self.subTest(name=name):
                workflow = (root / name).read_text(encoding="utf-8")
                retry_pos = workflow.index("git rebase -X theirs") if "wnba-" in name else workflow.index("git pull --rebase -X theirs")
                guard_pos = workflow.index(
                    "python tests/archive_integrity_gate.py " + archive_path +
                    " --baseline-ref " + git_ref
                )
                self.assertGreater(guard_pos, retry_pos)


if __name__ == "__main__":
    unittest.main(verbosity=2)
