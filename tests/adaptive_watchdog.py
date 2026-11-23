#!/usr/bin/env python3
"""Read-only watchdog: request a manual backup only when active polling stalls."""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adaptive_monitor import load, setting, should_poll

MAX_AGE_MINUTES = 105


def needs_backup(league, now=None):
    current = now or datetime.now(timezone.utc)
    if not should_poll(league, current):
        return False, f"{league} intentionally idle; no backup needed"
    state = load(setting(league)["status"])
    value = state.get("last_checked_at")
    if not isinstance(value, str):
        return True, f"{league} active but never successfully checked"
    try:
        checked = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{league} has invalid heartbeat timestamp") from exc
    if checked.tzinfo is None:
        raise ValueError("Monitor heartbeat lacks timezone")
    age = (current - checked).total_seconds() / 60
    if age < -10:
        raise ValueError("Monitor heartbeat in future")
    return age > MAX_AGE_MINUTES, (
        f"{league} last successful check {age:.0f} minutes ago"
    )


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("NBA", "WNBA", "NHL", "MLB"):
        raise SystemExit("Usage: adaptive_watchdog.py NBA|WNBA|NHL|MLB")
    required, reason = needs_backup(sys.argv[1])
    print(("BACKUP REQUIRED: " if required else "NO BACKUP: ") + reason)
    output = os.getenv("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"needed={'true' if required else 'false'}\n")


if __name__ == "__main__":
    main()
