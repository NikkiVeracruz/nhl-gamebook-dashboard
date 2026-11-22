#!/usr/bin/env python3
"""Read-only dashboard regression checks. Never modifies published data."""
import ast
import json
import sys
from pathlib import Path

def check(condition, message):
    if not condition:
        raise AssertionError(message)

def main():
    for filename in ("monitor.py", "archive.py"):
        ast.parse(Path(filename).read_text(encoding="utf-8"), filename=filename)
        print("PASS Python syntax:", filename)
    for filename in ("gamebooks.json", "archive.json"):
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        check(isinstance(data, dict), filename + " must contain an object")
        check(isinstance(data.get("games"), list), filename + " needs games list")
        seen = set()
        for game in data["games"]:
            check(isinstance(game, dict), filename + " contains invalid game")
            check(isinstance(game.get("date"), str), filename + " has game without date")
            key = str(game.get("id") or game.get("slug") or game["date"] + "|" + str(game.get("label")))
            check(key not in seen, filename + " duplicate game: " + key)
            seen.add(key)
            for field in ("pdf_url", "gs_url", "es_url", "box_url", "plays_url"):
                if game.get(field):
                    check(str(game[field]).startswith("https://"), filename + " invalid " + field)
        print("PASS JSON structure and unique games:", filename, len(data["games"]))
    html = Path("index.html").read_text(encoding="utf-8")
    check("gamebooks.json" in html, "Dashboard is not referencing current feed")
    check("archive.json" in html, "Dashboard is not referencing archive")
    print("PASS dashboard feed references")
    print("PASS all read-only checks")

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("FAIL:", exc, file=sys.stderr)
        sys.exit(1)
