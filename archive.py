"""Maintain a cumulative archive without allowing corrupt input to erase history.

Safety properties:
- Never silently recreate a missing or unreadable archive.
- Reject malformed and duplicate game identities before writing.
- Preserve previously saved game records and report links.
- Replace archive.json atomically only after validation.
"""
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

LIVE = Path("gamebooks.json")
ARCHIVE = Path("archive.json")
KEYS = ("id", "slug")
REPORT_KEYS = (
    "pdf_url", "gs_url", "es_url", "box_url", "plays_url",
    "play_url", "boxscore_url", "playbyplay_url"
)


class ArchiveIntegrityError(RuntimeError):
    """A dataset failed validation; the existing archive is left unchanged."""


def identity(game):
    for key in KEYS:
        if game.get(key):
            return str(game[key])
    return str(game.get("date", "")) + "|" + str(game.get("label", ""))


def validate_games(payload, source):
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), list):
        raise ArchiveIntegrityError(f"{source}: expected an object with a games list")
    unique = {}
    for index, game in enumerate(payload["games"]):
        if not isinstance(game, dict):
            raise ArchiveIntegrityError(f"{source}: game #{index} is not an object")
        if not isinstance(game.get("date"), str) or not game["date"]:
            raise ArchiveIntegrityError(f"{source}: game #{index} has no date")
        if not any(game.get(k) for k in KEYS) and not game.get("label"):
            raise ArchiveIntegrityError(f"{source}: game #{index} has no identity")
        key = identity(game)
        if key in unique:
            raise ArchiveIntegrityError(f"{source}: duplicate game identity {key}")
        unique[key] = game
    return unique


def load_payload(path, source):
    # In particular, do not convert FileNotFoundError/JSONDecodeError to an
    # empty archive. Both should fail the publishing workflow visibly.
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ArchiveIntegrityError(
            f"{source}: unable to read valid JSON at {path}; existing data NOT replaced"
        ) from exc


def build_archive(live, previous, now=None):
    current = validate_games(live, "Current feed")
    saved = validate_games(previous, "Historical archive").copy()
    original_ids = set(saved)
    original_links = {
        key: {field: game[field] for field in REPORT_KEYS if game.get(field)}
        for key, game in saved.items()
    }

    for key, game in current.items():
        old = saved.get(key, {})
        # Missing, null or empty report fields are not evidence that a
        # previously verified document has disappeared.
        incoming = {
            field: value for field, value in game.items()
            if value is not None and (field not in REPORT_KEYS or value)
        }
        saved[key] = {**old, **incoming}

    if not original_ids.issubset(saved):
        raise ArchiveIntegrityError("Historical archive lost one or more saved game identities")
    for key, links in original_links.items():
        for field, previous_url in links.items():
            if not saved[key].get(field):
                raise ArchiveIntegrityError(
                    f"Previously saved report {field} disappeared for game {key}"
                )

    games = sorted(saved.values(), key=lambda g: (
        g.get("date", ""), g.get("label", "")
    ), reverse=True)
    when = now if now is not None else datetime.now(timezone.utc)
    return {"updated_at": when.isoformat(), "games": games}


def atomic_write_json(path, output):
    # Forward-only policy applies to the tracked production archive exclusively;
    # temporary regression fixtures and legacy restoration code remain intact.
    from forward_only import filter_archive
    output = filter_archive(path, output)
    serialized = json.dumps(output, indent=2, ensure_ascii=False) + "\n"
    # Serialize and parse before replacing anything.
    json.loads(serialized)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as handle:
            tmp_path = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        # Preserve the source file's read permissions where available.
        os.chmod(tmp_path, stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def main():
    live = load_payload(LIVE, "Current feed")
    previous = load_payload(ARCHIVE, "Historical archive")
    output = build_archive(live, previous)
    # Compare what would actually be retained, not unverified provisional
    # live records that the forward-only writer would otherwise discard.
    from forward_only import filter_archive
    output = filter_archive(ARCHIVE, output)
    if output["games"] == previous["games"]:
        print("Archive unchanged; no write required")
        return
    atomic_write_json(ARCHIVE, output)
    print(
        "Archive integrity PASS: "
        f"{len(previous['games'])} previous records, "
        f"{len(output['games'])} retained/updated records"
    )


if __name__ == "__main__":
    main()
