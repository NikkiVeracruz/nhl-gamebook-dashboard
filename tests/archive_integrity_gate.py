#!/usr/bin/env python3
"""Fail-closed prepublication archive gate shared by current and backfill jobs.

Compare the archive in the working tree to its immutable checkout baseline.
In particular, never publish a change that loses historical IDs or report links.
"""
import json
import subprocess
import sys
from pathlib import Path

from archive import ArchiveIntegrityError, REPORT_KEYS, load_payload, validate_games

ALLOWED_ARCHIVES = {"archive.json", "wnba/archive.json"}


def verify_change(old, new, source="archive"):
    prior = validate_games(old, f"{source}: Git baseline")
    proposed = validate_games(new, f"{source}: proposed publication")
    lost = sorted(set(prior) - set(proposed))
    if lost:
        raise ArchiveIntegrityError(
            f"{source}: publication would remove {len(lost)} archived games; "
            f"examples: {', '.join(lost[:5])}"
        )
    for game_id, game in prior.items():
        published = proposed[game_id]
        for field in REPORT_KEYS:
            if game.get(field) and not published.get(field):
                raise ArchiveIntegrityError(
                    f"{source}: publication would remove saved {field} for {game_id}"
                )
    return len(prior), len(proposed)


def main(path):
    if path not in ALLOWED_ARCHIVES:
        raise ArchiveIntegrityError("Only known archive paths may be checked")
    try:
        baseline_text = subprocess.check_output(
            ["git", "show", f"HEAD:{path}"], text=True, stderr=subprocess.PIPE
        )
        baseline = json.loads(baseline_text)
    except (subprocess.CalledProcessError, ValueError, OSError) as exc:
        raise ArchiveIntegrityError(
            f"{path}: cannot verify the committed baseline; refusing publication"
        ) from exc
    candidate = load_payload(Path(path), "Proposed archive")
    before, after = verify_change(baseline, candidate, path)
    print(f"ARCHIVE SAFE TO PUBLISH {path}: {before} previous games, {after} proposed games")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python tests/archive_integrity_gate.py archive.json|wnba/archive.json")
    try:
        main(sys.argv[1])
    except ArchiveIntegrityError as exc:
        sys.exit(f"ARCHIVE PUBLICATION BLOCKED: {exc}")
