#!/usr/bin/env python3
"""NHL official HTML report monitor; 3 AM America/New_York rollover."""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests

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

def main():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    today = (datetime.now(ET) - timedelta(hours=3)).date()
    days = [today - timedelta(days=1), today]
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
    games.sort(key=lambda g: (g["date"], g["label"]))
    data = {"window_label": f"{days[0]:%b %d, %Y} – {days[1]:%b %d, %Y} (ET; 3 AM rollover)",
            "updated_at": datetime.now(timezone.utc).isoformat(), "games": games}
    if failures:
        data["warning"] = "NHL schedule data is temporarily unavailable for " + ", ".join(failures)
    OUT.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    LOG.info("Published %d games, %d reports", len(games), sum(bool(g.get(k)) for g in games for k in ("gs_url", "es_url")))
    if len(failures) == len(days):
        raise RuntimeError("Both NHL schedule requests failed")

if __name__ == "__main__":
    main()
