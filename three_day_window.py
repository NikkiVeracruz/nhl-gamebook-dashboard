#!/usr/bin/env python3
"""Exactly three Eastern reporting dates; safely archive records before rollover.

The reporting day changes at 03:00 America/New_York local time, even when
daylight saving time starts or ends. Display and archival retention are separate.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def reporting_day(now=None):
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        raise ValueError("An aware datetime is required for Eastern rollover")
    local = instant.astimezone(ET)
    return local.date() - timedelta(days=1) if local.hour < 3 else local.date()


def three_days(now=None):
    today = reporting_day(now)
    return [today - timedelta(days=1), today, today + timedelta(days=1)]


def archive_outgoing_games(feed_path, archive_path, days, archive_module):
    """Persist every outgoing record and official link before removing it from feed.

    The existing archive is mandatory. Never create an empty replacement and
    never overwrite stored report links when a current feed lacks a link.
    """
    previous_feed = archive_module.load_payload(
        Path(feed_path), "Existing rolling game feed"
    )
    keep = {d.isoformat() for d in days}
    outgoing = [game for game in previous_feed["games"]
                if game.get("date") not in keep]
    if not outgoing:
        return 0
    archive_path = Path(archive_path)
    previous_archive = archive_module.load_payload(
        archive_path, "Cumulative historical archive"
    )
    merged = archive_module.build_archive({"games": outgoing}, previous_archive)
    if merged["games"] != previous_archive["games"]:
        archive_module.atomic_write_json(archive_path, merged)
        print(f"Safely archived {len(outgoing)} outgoing records before rollover")
    else:
        print(f"Verified {len(outgoing)} outgoing records are already archived")
    return len(outgoing)
