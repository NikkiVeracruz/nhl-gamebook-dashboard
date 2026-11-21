#!/usr/bin/env python3
"""Incrementally backfill previous/current seasons into archive.json, without touching live feeds."""
import json, os, sys, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests
from monitor import get_games, HEADERS

LEAGUE = os.environ["ARCHIVE_LEAGUE"]
START = {"nba":"2025-09-01","nhl":"2025-09-01","mlb":"2025-02-01"}[LEAGUE]
ARCHIVE = Path("archive.json")
CURSOR = Path("archive-progress.json")
END = date.today()
BATCH = 3
def main():
    previous = json.loads(ARCHIVE.read_text()) if ARCHIVE.exists() else {"games":[]}
    records = {str(g.get("id") or g.get("slug") or (g.get("date"),g.get("label"))):g for g in previous.get("games",[])}
    progress = json.loads(CURSOR.read_text()) if CURSOR.exists() else {}
    day = date.fromisoformat(progress.get("next_date",START))
    session = requests.Session()
    session.headers.update(HEADERS)
    processed = 0
    while day <= END and processed < BATCH:
        try:
            if LEAGUE == "mlb":
                response=session.get("https://statsapi.mlb.com/api/v1/schedule",params={"sportId":1,"date":day.isoformat(),"hydrate":"team","gameTypes":"S,R,F,D,L,W"},timeout=25)
                response.raise_for_status()
                games=[]
                for block in response.json().get("dates",[]):
                    for game in block.get("games",[]):
                        pk=game.get("gamePk")
                        if not isinstance(pk,int):continue
                        teams=game.get("teams",{})
                        away=teams.get("away",{}).get("team",{}).get("name","Away")
                        home=teams.get("home",{}).get("team",{}).get("name","Home")
                        status=game.get("status",{})
                        g={"id":str(pk),"date":day.isoformat(),"label":f"{away} @ {home}","status":status.get("detailedState","Scheduled")}
                        if status.get("abstractGameState") in ("Live","Final"):
                            base=f"https://www.mlb.com/gameday/{pk}"
                            g.update(box_url=base+"/box-score",plays_url=base+"/play-by-play")
                        games.append(g)
            elif LEAGUE == "nba":
                games=games_on(session,day)
            else:
                games=get_games(session,day)
        except (requests.RequestException,ValueError,KeyError) as exc:
            print(f"Could not process {day}: {exc}",file=sys.stderr)
            raise
        for g in games:
            key=str(g.get("id") or g.get("slug") or (g.get("date"),g.get("label")))
            old=records.get(key,{})
            records[key]={**old,**{k:v for k,v in g.items() if v is not None}}
        print(f"{day}: {len(games)} games; total {len(records)}")
        day+=timedelta(days=1)
        processed+=1
    previous["games"]=sorted(records.values(),key=lambda g:(g.get("date",""),g.get("label","")),reverse=True)
    previous["updated_at"]=datetime.now(timezone.utc).isoformat()
    ARCHIVE.write_text(json.dumps(previous,indent=2,ensure_ascii=False)+"\n")
    CURSOR.write_text(json.dumps({"next_date":day.isoformat(),"complete":day>END,"updated_at":previous["updated_at"]},indent=2)+"\n")
if __name__=="__main__":
    main()
