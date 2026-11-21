"""Maintain a separate, cumulative archive without altering the live dashboard feed."""
import json
from datetime import datetime, timezone
from pathlib import Path

LIVE = Path("gamebooks.json")
ARCHIVE = Path("archive.json")
KEYS = ("id", "slug")

def identity(game):
    for key in KEYS:
        if game.get(key):
            return str(game[key])
    return str(game.get("date", "")) + "|" + str(game.get("label", ""))

def main():
    live = json.loads(LIVE.read_text(encoding="utf-8"))
    try:
        previous = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {"games": []}
    saved = {identity(g): g for g in previous.get("games", []) if isinstance(g, dict)}
    for game in live.get("games", []):
        if not isinstance(game, dict) or not game.get("date"):
            continue
        key = identity(game)
        old = saved.get(key, {})
        # Preserve report URLs already discovered if a later fetch omits them.
        saved[key] = {**old, **{k: v for k, v in game.items() if v is not None}}
    games = sorted(saved.values(), key=lambda g: (g.get("date", ""), g.get("label", "")), reverse=True)
    output = {"updated_at": datetime.now(timezone.utc).isoformat(), "games": games}
    ARCHIVE.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
