#!/usr/bin/env python3
"""Read-only rehearsal against the latest immutable production main snapshot.

CI fetches main into FETCH_HEAD. This script reads blobs via git show and
merges in memory only. Neither staged nor production archives are modified.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import archive
from archive_integrity_gate import verify_change


def git_payload(path, ref="FETCH_HEAD"):
    try:
        raw = subprocess.check_output(
            ["git", "show", f"{ref}:{path}"], text=True, stderr=subprocess.PIPE
        )
        return json.loads(raw)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise archive.ArchiveIntegrityError(
            f"Cannot inspect current production {path} at {ref}"
        ) from exc


def rehearse(league, live_path, archive_path, writer):
    previous = git_payload(archive_path)
    live = git_payload(live_path)
    proposed = writer.build_archive(live, previous)
    before, after = verify_change(previous, proposed, archive_path)
    if after < before:
        raise archive.ArchiveIntegrityError(
            f"{league}: in-memory rehearsal lost {before - after} games"
        )
    print(f"PASS {league}: latest production archive retains {before} "
          f"records, proposed in-memory merge contains {after}")


def main():
    rehearse("Primary league", "gamebooks.json", "archive.json", archive)
    if (ROOT / "wnba_archive.py").exists():
        import wnba_archive
        rehearse("WNBA", "wnba/gamebooks.json", "wnba/archive.json", wnba_archive)
    print("No production or staged archive files were written.")


if __name__ == "__main__":
    main()
