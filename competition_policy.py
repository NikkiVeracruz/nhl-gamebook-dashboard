"""Classify NHL game identifiers without ever discarding archived records.

NHL game IDs: season (4), competition code (2), game number (4).
09 is the distinct international/Olympic hockey feed, not an NHL fixture.
"""
from datetime import date

NHL_TYPES = {
    "01": "nhl_preseason",
    "02": "nhl_regular_season",
    "03": "nhl_playoffs",
    "04": "nhl_all_star",
}
INTERNATIONAL = "international_hockey"


def competition(game_id):
    token = str(game_id or "")
    if len(token) != 10 or not token.isdigit():
        return "unknown_needs_review"
    kind = token[4:6]
    if kind == "09":
        return INTERNATIONAL
    return NHL_TYPES.get(kind, "unknown_needs_review")


def nhl_game(game_id):
    return competition(game_id) in NHL_TYPES.values()


def needs_nhl_reports(game):
    # International hockey is never treated as an NHL GS/ES PDF failure.
    return nhl_game(game.get("id"))


def review_annotation(game):
    category = competition(game.get("id"))
    existing = game.get("competition")
    if category == INTERNATIONAL:
        return {"competition": INTERNATIONAL, "report_requirement": "not_applicable_nhl"}
    if category == "nhl_preseason" and not (game.get("gs_url") and game.get("es_url")):
        return {"competition": category, "report_requirement": "needs_verification"}
    if existing in (INTERNATIONAL, "nhl_preseason"):
        return {"competition": category,
                "report_requirement": "verified" if game.get("gs_url") and game.get("es_url")
                else "needs_verification"}
    return {}


def classify_archive(archive_path=None, summary_path=None):
    import json
    from pathlib import Path
    import archive
    archive_path = Path(archive_path or "archive.json")
    summary_path = Path(summary_path or "competition-review.json")
    original = archive.load_payload(archive_path, "NHL historical archive")
    archive.validate_games(original, "NHL unmodified archive")
    changed = 0
    international, pending = [], []
    for g in original["games"]:
        annotation = review_annotation(g)
        if annotation:
            for key, value in annotation.items():
                if g.get(key) != value:
                    g[key] = value
                    changed += 1
        if competition(g.get("id")) == INTERNATIONAL:
            international.append(str(g["id"]))
        if (competition(g.get("id")) == "nhl_preseason"
                and g.get("date", "").startswith("2026")
                and str(g.get("status", "")).lower() in ("off", "final")
                and not (g.get("gs_url") and g.get("es_url"))):
            pending.append({
                "id": str(g["id"]), "date": g["date"],
                "label": g.get("label", ""), "classification": "needs_verification",
                "missing_reports": [name for name in ("gs_url", "es_url") if not g.get(name)],
            })
    if changed:
        # Assert reports and game IDs are not lost through classification.
        safe = archive.build_archive({"games": original["games"]},
                                     archive.load_payload(archive_path, "Original NHL archive"))
        archive.atomic_write_json(archive_path, safe)
    result = {
        "international_hockey_preserved": sorted(international),
        "unverified_nhl_preseason_reports": sorted(pending, key=lambda x: x["date"], reverse=True),
    }
    if (not summary_path.exists() or
            json.loads(summary_path.read_text(encoding="utf-8")) != result):
        summary_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8")
    print(f"NHL: {len(international)} non-NHL international games classified and retained; "
          f"{len(pending)} NHL preseason records need official report verification; "
          f"{changed} metadata fields updated")
    return result


if __name__ == "__main__":
    classify_archive()
