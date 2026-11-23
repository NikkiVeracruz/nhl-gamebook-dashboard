#!/usr/bin/env python3
"""Revisit missing official reports without clearing any archived game.

Fast retry: incomplete completed games from the last 7 days, excluding the
current two-day monitor window. Slow retry: at most four older games per day.
"""
import argparse
import importlib
from datetime import datetime, timedelta
from pathlib import Path

import requests
from adaptive_monitor import ET, setting, outstanding, URGENT_DAYS


def recover_one(league, game, session, by_date=None):
    """Only add official reports; do not infer success from a game being final."""
    if league in ("NBA", "WNBA"):
        module = importlib.import_module("monitor" if league == "NBA" else "wnba_monitor")
        if by_date is None:
            raise RuntimeError("NBA/WNBA recovery requires a schedule-date cache")
        day = game["date"]
        if day not in by_date:
            from datetime import date
            by_date[day] = {g.get("id"): g for g in
                            module.games_on(session, date.fromisoformat(day))}
        latest = by_date[day].get(str(game["id"]), {})
        pdf = latest.get("pdf_url")
        if pdf and not game.get("pdf_url"):
            game["pdf_url"] = pdf
            return True
        return False
    if league == "NHL":
        module = importlib.import_module("monitor")
        changed = False
        for kind, key in (("GS", "gs_url"), ("ES", "es_url")):
            if game.get(key):
                continue
            url = module.report_url(game["id"], kind)
            if module.verified_report(session, url, kind, game["id"]):
                game[key] = url
                changed = True
        return changed
    if league == "MLB":
        # Match the live MLB monitor's official game-specific report URLs.
        # Only completed games enter this function (not suspended/postponed).
        ident = str(game.get("id", ""))
        if not ident.isdigit():
            return False
        base = f"https://www.mlb.com/gameday/{ident}"
        changed = False
        if not (game.get("box_url") or game.get("boxscore_url")):
            game["box_url"] = base + "/box-score"
            changed = True
        if not (game.get("plays_url") or game.get("play_url") or
                game.get("playbyplay_url")):
            game["plays_url"] = base + "/play-by-play"
            changed = True
        return changed
    raise ValueError(f"Unrecognized league {league}")


def candidates(league, scope, today):
    games = outstanding(league, today, max_age=None)
    if scope == "recent":
        cutoff = today - timedelta(days=2)
        return [g for g in games
                if cutoff >= __import__("datetime").date.fromisoformat(g["date"])
                and (today - __import__("datetime").date.fromisoformat(g["date"])).days <= URGENT_DAYS]
    backlog = [
        g for g in games
        if (today - __import__("datetime").date.fromisoformat(g["date"])).days > URGENT_DAYS
    ]
    backlog.sort(key=lambda g: (g["date"], str(g.get("id", ""))))
    if not backlog:
        return []
    first = today.toordinal() % len(backlog)
    return [backlog[(first + j) % len(backlog)]
            for j in range(min(len(backlog), 4))]


def run(league, scope, session=None, now=None):
    from archive import atomic_write_json as write_nba
    from archive import load_payload as read_nba
    import archive as archive_module
    if league == "WNBA":
        archive_module = importlib.import_module("wnba_archive")
    now = now or datetime.now(ET).date()
    path = Path(setting(league)["archive"])
    payload = archive_module.load_payload(path, f"{league} original archive")
    chosen = candidates(league, scope, now)
    if not chosen:
        print(f"{league}: no {scope} missing reports to recover")
        return 0
    session = session or requests.Session()
    session.headers.update({"User-Agent": "GamebookAdaptiveRecovery/1.0"})
    matches = {str(g.get("id")): g for g in payload["games"] if g.get("id")}
    date_cache = {}
    added = 0
    for g in chosen:
        old = matches.get(str(g.get("id")))
        if not old:
            continue
        try:
            if recover_one(league, old, session, by_date=date_cache):
                added += 1
        except (requests.RequestException, ValueError, KeyError) as exc:
            print(f"{league}: retry inconclusive for {g.get('id')}: {exc}")
    if added:
        from datetime import timezone
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        archive_module.atomic_write_json(path, payload)
    print(f"{league}: {scope} recovery scanned {len(chosen)} games; updated {added}")
    return added


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("league", choices=("NBA", "WNBA", "NHL", "MLB"))
    parser.add_argument("scope", choices=("recent", "stale"))
    options = parser.parse_args()
    run(options.league, options.scope)


if __name__ == "__main__":
    main()
