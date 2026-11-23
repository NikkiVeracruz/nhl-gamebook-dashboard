#!/usr/bin/env python3
"""NHL official HTML report monitor; 3 AM America/New_York rollover."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import archive as archive_module
from three_day_window import three_days, archive_outgoing_games, scheduled_games_in_window
from competition_policy import nhl_game

ET = ZoneInfo("America/New_York")
OUT = Path("gamebooks.json")
API = "https://api-web.nhle.com/v1/score"
REPORTS = "https://www.nhl.com/scores/htmlreports"
LOG = logging.getLogger("nhl-reports")
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; NHLGamebookDashboard/1.0)", "Accept": "text/html,application/json,*/*"}

def report_url(game_id, kind):
    # NHL game IDs are YYYY + two-digit game type + four-digit game number.
    # The official report filename uses the final six digits.
    game_id = str(game_id)
    if len(game_id) != 10 or not game_id.isdigit():
        raise ValueError("Invalid NHL game ID")
    start = int(game_id[:4])
    return f"{REPORTS}/{start}{start+1}/{kind}{game_id[4:]}.HTM"

def verified_report(session, url, kind, game_id):
    """Validate the official URL and the expected HTML report type."""
    try:
        r = session.get(url, timeout=18)
        r.raise_for_status()
        if not r.url.startswith(REPORTS + "/"):
            return False
        content = r.text[:250000].lower()
        # Some NHL reports contain an HTML title, others a heading.
        expected = "game summary" if kind == "GS" else "event summary"
        if expected not in content or "<html" not in content:
            return False
        # Report identifiers are constructed exclusively from the NHL game ID.
        return True
    except requests.RequestException as exc:
        LOG.info("Report not ready: %s (%s)", url, exc)
        return False

def get_games(session, day):
    r = session.get(f"{API}/{day.isoformat()}", timeout=25)
    r.raise_for_status()
    games = []
    for g in r.json().get("games", []):
        gid = str(g.get("id", ""))
        if len(gid) != 10 or not gid.isdigit():
            continue
        if not nhl_game(gid):
            LOG.info("Skip non-NHL event %s from current NHL games", gid)
            continue
        away, home = g.get("awayTeam", {}), g.get("homeTeam", {})
        away_name = away.get("name", {}).get("default") or away.get("abbrev", "Away")
        home_name = home.get("name", {}).get("default") or home.get("abbrev", "Home")
        status = g.get("gameState", "Scheduled")
        game = {"id": gid, "date": day.isoformat(), "label": f"{away_name} @ {home_name}", "status": status}
        # NHL publishes report pages during or after games; never show an
        # unverified link, and do not assume a game is final.
        if status in {"LIVE", "CRIT", "OFF", "FINAL"}:
            for kind, key in (("GS", "gs_url"), ("ES", "es_url")):
                url = report_url(gid, kind)
                if verified_report(session, url, kind, gid):
                    game[key] = url
                    LOG.info("Verified %s for %s", kind, gid)
        games.append(game)
    return games

def write_if_changed(path, payload):
    """Publish only genuine feed changes; save successful checks separately."""
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = {}
    visible = lambda x: {k: v for k, v in x.items() if k != "updated_at"}
    if visible(prior) == visible(payload):
        LOG.info("Feed unchanged; skipped timestamp-only commit")
        return False
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    return True


def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    # Archive disappearing dates *before* publishing the new three-day feed.
    days = three_days()
    archive_outgoing_games(OUT, archive_module.ARCHIVE, days, archive_module)
    # Seasonal guard: keep the website live but avoid report scraping in the offseason.
    # Broad calendar boundaries allow preseason and late postseason games; the
    # schedule source itself determines which games actually appear.
    if datetime.now(ET).month not in [9,10,11,12,1,2,3,4,5,6] and not scheduled_games_in_window("league-calendar.json", days) and not __import__("adaptive_monitor").should_poll("NHL"):
        now = datetime.now(timezone.utc).isoformat()
        write_if_changed(OUT, {"window_label": f"{days[0]:%b %d, %Y} – {days[-1]:%b %d, %Y} (ET; 3 AM rollover)", "window_dates": [d.isoformat() for d in days], "updated_at": now, "offseason": True, "games": []})
        LOG.info("Offseason: skipping gamebook checks")
        return

    session = requests.Session()
    session.headers.update(HEADERS)
    games, failures = [], []
    for day in days:
        try:
            day_games = get_games(session, day)
            LOG.info("%s: %d games", day, len(day_games))
            games.extend(day_games)
        except (requests.RequestException, ValueError, KeyError) as exc:
            LOG.exception("Schedule request failed for %s", day)
            failures.append(day.isoformat())
    if failures:
        try:
            previous = json.loads(OUT.read_text(encoding="utf-8"))
            existing = {g["id"] for g in games}
            for g in previous.get("games", []):
                if g.get("date") in {str(d) for d in days} and g.get("id") not in existing:
                    games.append(g)
        except (OSError, ValueError, KeyError):
            pass
    # Completeness guard: a successful but partial schedule response must not erase games.
    try:
        prior_data = json.loads(OUT.read_text(encoding="utf-8"))
        known = {str(g["id"]): g for g in prior_data.get("games", []) if g.get("date") in {d.isoformat() for d in days} and g.get("id")}
        seen = {str(g["id"]) for g in games}
        missing = [g for gid, g in known.items() if gid not in seen]
        if missing:
            LOG.warning("SCHEDULE COMPLETENESS ALERT: %d previously known NHL games missing from source; retaining them", len(missing))
            games.extend(missing)
            failures.append("partial schedule: " + ", ".join(g["date"] for g in missing))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Preserve links verified in a previous successful run if the official host
    # temporarily fails. Only restore the exact expected official URL for the
    # same game ID and date; never accept arbitrary URLs from old data.
    try:
        previous_data = json.loads(OUT.read_text(encoding="utf-8"))
        prior_by_id = {str(g.get("id")): g for g in previous_data.get("games", [])
                       if isinstance(g, dict) and g.get("id")}
        for game in games:
            old = prior_by_id.get(str(game.get("id")))
            if not old or old.get("date") != game.get("date"):
                continue
            for kind, key in (("GS", "gs_url"), ("ES", "es_url")):
                expected_url = report_url(game["id"], kind)
                if not game.get(key) and old.get(key) == expected_url:
                    game[key] = expected_url
                    LOG.warning("Retained previously verified NHL %s report for %s", kind, game["id"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        LOG.warning("Could not restore previously verified report links: %s", exc)
    games.sort(key=lambda g: (g["date"], g["label"]))
    data = {"window_label": f"{days[0]:%b %d, %Y} – {days[-1]:%b %d, %Y} (ET; 3 AM rollover)",
            "window_dates": [d.isoformat() for d in days],
            "updated_at": datetime.now(timezone.utc).isoformat(), "games": games}
    if failures:
        data["warning"] = "NHL schedule data is temporarily unavailable for " + ", ".join(failures)
    write_if_changed(OUT, data)
    LOG.info("Published %d games, %d reports", len(games), sum(bool(g.get(k)) for g in games for k in ("gs_url", "es_url")))
    if len(failures) == len(days):
        raise RuntimeError("All three NHL schedule requests failed")

if __name__ == "__main__":
    main()
