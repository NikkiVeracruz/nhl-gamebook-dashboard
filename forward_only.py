"""Forward-only archive policy: retain only complete current-and-future games.

This policy is deliberately applied ONLY to tracked production archive paths.
Temporary paths used by archive-integrity tests retain their original behavior.
Backfill scripts are preserved but their scheduled workflows are suspended.
Historical data is recoverable from the pre-migration Git backup branch.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ARCHIVES = {
  "archive.json": {
    "league": "NHL",
    "cutoff": "2026-11-22"
  }
}  # Set on 2026-11-23.
REPORT_KEYS = ("pdf_url", "gs_url", "es_url", "box_url", "plays_url",
               "boxscore_url", "play_url", "playbyplay_url")


def complete(game, league):
    """No archived game without every league-required report AND final status."""
    status = str(game.get("status", "")).lower()
    if league == "NFL":
        # NFL.com official gamebooks appear after a game completes;
        # the URL was checked for actual PDF bytes by monitor.py.
        return bool(game.get("pdf_url"))
    if league in ("NBA", "WNBA"):
        return "final" in status and bool(game.get("pdf_url"))
    if league == "NHL":
        return status in ("final", "off") and bool(game.get("gs_url") and game.get("es_url"))
    if league == "MLB":
        return ("final" in status and game.get("link_verification") == "verified_api"
                and bool(game.get("box_url") and game.get("plays_url")))
    raise ValueError("Unknown league " + league)


def configured(path):
    """Only the actual tracked archive, not test fixtures, is filtered."""
    p = Path(path).resolve()
    try:
        rel = p.relative_to(ROOT).as_posix()
    except ValueError:
        return None
    return ARCHIVES.get(rel)


def filter_archive(path, payload):
    policy = configured(path)
    if policy is None:
        return payload
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        raise ValueError("Invalid archive payload; refusing purge")
    seen = set()
    kept = []
    for game in payload["games"]:
        if not isinstance(game, dict) or not isinstance(game.get("date"), str):
            raise ValueError("Malformed archived game; refusing purge")
        ident = str(game.get("slug") or game.get("id") or "")
        if not ident or ident in seen:
            raise ValueError("Missing or duplicate archived game ID; refusing purge")
        seen.add(ident)
        if game["date"] >= policy["cutoff"] and complete(game, policy["league"]):
            kept.append(game)
    return {**payload, "games": kept}


def apply():
    import archive
    from pathlib import Path
    for relative, policy in ARCHIVES.items():
        target = ROOT / relative
        data = json.loads(target.read_text(encoding="utf-8"))
        before = archive.validate_games(data, relative)
        output = filter_archive(target, data)
        # Structural contract: every record that survives is byte-equivalent
        # to its original game object, including its trusted document link.
        after = archive.validate_games(output, relative + " proposed")
        if not set(after).issubset(before):
            raise ValueError(relative + ": introduced an unknown game")
        for key, game in after.items():
            if before[key] != game:
                raise ValueError(relative + ": changed an existing game")
            if game["date"] < policy["cutoff"] or not complete(game, policy["league"]):
                raise ValueError(relative + ": incomplete or old record retained")
        if len(after) != len(before):
            # Important: intentionally bypass old no-deletions gate exactly
            # here, after the explicit forward-only migration validation.
            archive.atomic_write_json(target, output)
        print(f"FORWARD_ONLY {relative}: {len(before)} -> {len(after)} complete current/new games; "
              f"{len(before)-len(after)} historical/incomplete records purged", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] != "apply":
        raise SystemExit("Usage: python forward_only.py apply")
    apply()
