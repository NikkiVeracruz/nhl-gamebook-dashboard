#!/usr/bin/env python3
"""Shared calendar and activity guard for independent gamebook league workflows.

No scheduled run edits GitHub workflow YAML. A daily coordinator enables/disables
the monitor via the GitHub Actions API, with a separate manual escape hatch.
"""
import argparse
import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SETTINGS = {
    "NBA": dict(source="espn", sport="basketball/nba", archive="archive.json",
                feed="gamebooks.json", calendar="nba-calendar.json",
                status="nba-poll-status.json", season_month=7),
    "WNBA": dict(source="espn", sport="basketball/wnba", archive="wnba/archive.json",
                 feed="wnba/gamebooks.json", calendar="wnba/calendar.json",
                 status="wnba/poll-status.json", season_month=4),
    "NHL": dict(source="nhl", archive="archive.json", feed="gamebooks.json",
                calendar="league-calendar.json", status="poll-status.json",
                season_month=7),
    "MLB": dict(source="mlb", archive="archive.json", feed="gamebooks.json",
                calendar="league-calendar.json", status="poll-status.json",
                season_month=1),
}
LOOKAHEAD = 21
URGENT_DAYS = 7


def setting(league):
    return SETTINGS[league.upper()]


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def season_start(league, today):
    month = setting(league)["season_month"]
    year = today.year if today.month >= month else today.year - 1
    return date(year, month, 1)


def completed(game, league):
    status = str(game.get("status", "")).strip().lower()
    if league in ("NBA", "WNBA"):
        return status in ("final", "final/ot", "final/2ot", "final/3ot")
    if league == "NHL":
        return status in ("final", "off")
    return status in ("final", "game over", "completed", "completed early",
                      "completed early: rain")


def reports_missing(game, league):
    if league in ("NBA", "WNBA"):
        return not game.get("pdf_url")
    if league == "NHL":
        return not (game.get("gs_url") and game.get("es_url"))
    return not ((game.get("box_url") or game.get("boxscore_url")) and
                (game.get("plays_url") or game.get("play_url") or
                 game.get("playbyplay_url")))


def outstanding(league, today, max_age=URGENT_DAYS):
    result = []
    oldest = season_start(league, today)
    for game in load(setting(league)["archive"])["games"]:
        if not isinstance(game, dict):
            continue
        try:
            day = date.fromisoformat(game["date"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (oldest <= day < today) or not completed(game, league):
            continue
        if max_age is not None and (today - day).days > max_age:
            continue
        if reports_missing(game, league):
            result.append(game)
    return result


def fetch_days(league, today, session=None, horizon=LOOKAHEAD):
    if session is None:
        import requests
        session = requests.Session()
    cfg = setting(league)
    days = set()
    for index in range(-1, horizon + 1):
        day = today + timedelta(days=index)
        if cfg["source"] == "espn":
            response = session.get(
                "https://site.api.espn.com/apis/site/v2/sports/"
                + cfg["sport"] + "/scoreboard",
                params={"dates": day.strftime("%Y%m%d"), "limit": 100},
                timeout=25,
            )
            response.raise_for_status()
            events = response.json().get("events")
            if not isinstance(events, list):
                raise ValueError(f"Malformed {league} ESPN response: {day}")
            for event in events:
                if not isinstance(event, dict) or "date" not in event:
                    raise ValueError(f"Malformed {league} event on {day}")
                kickoff = datetime.fromisoformat(
                    event["date"].replace("Z", "+00:00"))
                if kickoff.tzinfo is None:
                    raise ValueError("Game kickoff has no timezone")
                event_day = kickoff.astimezone(ET).date()
                if event_day == day:
                    days.add(day)
        elif cfg["source"] == "nhl":
            response = session.get(
                "https://api-web.nhle.com/v1/score/" + day.isoformat(),
                timeout=25,
            )
            response.raise_for_status()
            games = response.json().get("games")
            if not isinstance(games, list):
                raise ValueError(f"Malformed NHL schedule: {day}")
            if games:
                days.add(day)
        else:
            response = session.get(
                "https://statsapi.mlb.com/api/v1/schedule",
                params={"sportId": 1, "date": day.isoformat(),
                        "gameTypes": "S,R,F,D,L,W"},
                timeout=25,
            )
            response.raise_for_status()
            blocks = response.json().get("dates")
            if not isinstance(blocks, list):
                raise ValueError(f"Malformed MLB schedule: {day}")
            if any(block.get("games") for block in blocks):
                days.add(day)
    # Preserve any known upcoming game dates through transient schedule omissions.
    end = today + timedelta(days=horizon)
    for path in (cfg["archive"], cfg["feed"]):
        for game in load(path)["games"]:
            try:
                d = date.fromisoformat(game["date"])
            except (KeyError, TypeError, ValueError):
                continue
            if today - timedelta(days=1) <= d <= end:
                days.add(d)
    return days


def refresh(league, today=None, session=None):
    today = today or datetime.now(ET).date()
    days = fetch_days(league, today, session=session)
    path = Path(setting(league)["calendar"])
    updated = {"game_days": sorted(d.isoformat() for d in days)}
    if not path.exists() or load(path) != updated:
        path.write_text(json.dumps(updated, indent=2) + "\n",
                        encoding="utf-8")
        print(f"{league}: refreshed {len(days)} game dates")
    else:
        print(f"{league}: {len(days)} game dates unchanged")
    return updated


def should_poll(league, now=None, manual=False):
    if manual:
        return True
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(ET)
    days = set(load(setting(league)["calendar"])["game_days"])
    today = local.date()
    if (today.isoformat() in days or
            (local.hour < 3 and
             (today - timedelta(days=1)).isoformat() in days)):
        return True
    return bool(outstanding(league, today))


def heartbeat(league, now=None):
    now = now or datetime.now(timezone.utc)
    cfg = setting(league)
    path = Path(cfg["status"])
    previous = load(path) if path.exists() else {}
    recent = outstanding(league, now.astimezone(ET).date())
    older = outstanding(league, now.astimezone(ET).date(), max_age=None)
    previous_at = previous.get("last_checked_at")
    try:
        last = datetime.fromisoformat(previous_at.replace("Z", "+00:00"))
        fresh = timedelta(0) <= now - last < timedelta(minutes=40)
    except (ValueError, AttributeError):
        fresh = False
    changed = (len(recent) != previous.get("pending_recent") or
               len(older) != previous.get("pending_all"))
    if not fresh or changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"last_checked_at": now.isoformat(),
                   "pending_recent": len(recent),
                   "pending_all": len(older)}
        path.write_text(json.dumps(payload, indent=2) + "\n",
                        encoding="utf-8")
        print(f"{league}: heartbeat recorded; recent missing {len(recent)}")
    else:
        print(f"{league}: successful check; heartbeat still fresh")


def main():
    cli = argparse.ArgumentParser()
    cli.add_argument("action", choices=("refresh", "guard", "heartbeat"))
    cli.add_argument("league", choices=tuple(SETTINGS))
    args = cli.parse_args()
    league = args.league
    if args.action == "refresh":
        refresh(league)
    elif args.action == "heartbeat":
        heartbeat(league)
    else:
        manual = (os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and
                  os.environ.get("ADAPTIVE_MANUAL_SCAN") == "true")
        if should_poll(league, manual=manual):
            print(f"{league}: ACTIVE")
        else:
            print(f"{league}: IDLE, no game or recent missing report")
            raise SystemExit(3)


if __name__ == "__main__":
    main()
