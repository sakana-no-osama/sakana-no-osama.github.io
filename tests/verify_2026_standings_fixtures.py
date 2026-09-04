"""Verify 2026 standings, aliases, and internal league invariants."""
from __future__ import annotations
import csv
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MATCHES = DATA / "matches_2026.csv"
MASTER = DATA / "team_master_2026.csv"
ALIASES = DATA / "team_name_alias_2026.csv"
OUTPUTS = {"1部": DATA/"league_standings_2026_div1.csv", "2部": DATA/"league_standings_2026_div2.csv"}
FIELDS = ["rank","team","division","played","wins","draws","losses","goals_for","goals_against","goal_difference","points","note"]
NUMERIC = ["rank","played","wins","draws","losses","goals_for","goals_against","goal_difference","points"]

def read(path: Path) -> tuple[list[str], list[dict[str,str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]

def integer(value: str, label: str, signed: bool=False) -> int:
    text=(value or "").strip()
    digits=text[1:] if signed and text.startswith("-") else text
    if not digits.isdigit():
        raise ValueError(f"invalid integer: {label}={text!r}")
    return int(text)

def load_names() -> tuple[dict[str,set[str]], dict[tuple[str,str],str]]:
    _, master_rows=read(MASTER)
    masters={"1部":set(),"2部":set()}
    for row in master_rows:
        division=(row.get("division") or "").strip(); team=(row.get("team") or "").strip()
        if (row.get("year") or "").strip()!="2026" or division not in masters or not team or team in masters[division]:
            raise ValueError(f"invalid master row: {row}")
        masters[division].add(team)
    if any(len(teams)!=8 for teams in masters.values()):
        raise ValueError(f"team master counts: { {d:len(t) for d,t in masters.items()} }")
    _, alias_rows=read(ALIASES)
    aliases={}
    for row in alias_rows:
        division=(row.get("division") or "").strip(); raw=(row.get("raw_team") or "").strip(); canonical=(row.get("canonical_team") or "").strip()
        if not raw or division not in masters or canonical not in masters[division] or (division,raw) in aliases:
            raise ValueError(f"invalid alias row: {row}")
        aliases[(division,raw)]=canonical
    return masters,aliases

def expected(division: str, matches: list[dict[str,str]], masters: dict[str,set[str]], aliases: dict[tuple[str,str],str]) -> tuple[list[dict[str,str]],int,int]:
    stats: dict[str,dict[str,int]]={}
    ids=set(); match_count=0; alias_uses=0
    def get(team): return stats.setdefault(team,defaultdict(int))
    for match in matches:
        if (match.get("status") or "").strip()!="played" or (match.get("division") or "").strip()!=division: continue
        match_count+=1; match_id=(match.get("match_id") or "").strip()
        if not match_id or match_id in ids: raise ValueError(f"blank or duplicate match_id: {match_id!r}")
        ids.add(match_id)
        names=[]
        for field in ("home_team","away_team"):
            raw=(match.get(field) or "").strip(); canonical=aliases.get((division,raw),raw)
            if canonical not in masters[division]: raise ValueError(f"team not in master after alias: {division} {raw!r}")
            alias_uses+=canonical!=raw; names.append(canonical)
        home,away=names
        if home==away: raise ValueError(f"same team: {match_id}")
        hs=integer(match.get("home_score") or "",match_id+".home_score"); aws=integer(match.get("away_score") or "",match_id+".away_score")
        h,a=get(home),get(away); h["played"]+=1; a["played"]+=1
        h["goals_for"]+=hs; h["goals_against"]+=aws; a["goals_for"]+=aws; a["goals_against"]+=hs
        if hs>aws: h["wins"]+=1; a["losses"]+=1
        elif hs<aws: a["wins"]+=1; h["losses"]+=1
        else: h["draws"]+=1; a["draws"]+=1
    if set(stats)!=masters[division]: raise ValueError(f"{division} team set mismatch")
    result=[]
    for team,values in stats.items():
        values["goal_difference"]=values["goals_for"]-values["goals_against"]; values["points"]=values["wins"]*3+values["draws"]
        result.append({"rank":"0","team":team,"division":division,**{f:str(values[f]) for f in FIELDS[3:-1]},"note":""})
    result.sort(key=lambda r:(-int(r["points"]),-int(r["goal_difference"]),-int(r["goals_for"])))
    keys=[(r["points"],r["goal_difference"],r["goals_for"]) for r in result]; ties={k for k,c in Counter(keys).items() if c>1}
    previous=None; rank=0
    for position,row in enumerate(result,1):
        key=(row["points"],row["goal_difference"],row["goals_for"])
        if key!=previous: rank=position; previous=key
        row["rank"]=str(rank); row["note"]="tied_hold" if key in ties else ""
    return result,match_count,alias_uses

def invariants(division: str, rows: list[dict[str,str]], matches: int) -> None:
    n=[{f:integer(r[f],r["team"]+"."+f,f=="goal_difference") for f in NUMERIC} for r in rows]
    if any(r["played"]!=r["wins"]+r["draws"]+r["losses"] for r in n): raise ValueError(division+": WDL mismatch")
    if sum(r["wins"] for r in n)!=sum(r["losses"] for r in n): raise ValueError(division+": wins/losses mismatch")
    if sum(r["draws"] for r in n)%2: raise ValueError(division+": odd draw total")
    if sum(r["goals_for"] for r in n)!=sum(r["goals_against"] for r in n): raise ValueError(division+": GF/GA mismatch")
    if sum(r["played"] for r in n)!=matches*2: raise ValueError(division+": played total mismatch")
    if any(r["goal_difference"]!=r["goals_for"]-r["goals_against"] for r in n): raise ValueError(division+": GD mismatch")
    if any(r["points"]!=r["wins"]*3+r["draws"] for r in n): raise ValueError(division+": points mismatch")

def main() -> int:
    try:
        masters,aliases=load_names(); _,matches=read(MATCHES)
        for division,path in OUTPUTS.items():
            expected_rows,match_count,alias_uses=expected(division,matches,masters,aliases)
            header,actual=read(path)
            if header!=FIELDS: raise ValueError(f"{path.name}: invalid columns")
            if actual!=expected_rows: raise ValueError(f"{division}: output mismatch")
            invariants(division,actual,match_count)
            print(f"{division}: teams={len(actual)} matches={match_count} alias_uses={alias_uses} tied_hold={sum(r['note']=='tied_hold' for r in actual)}")
        print("fixtures=NOT_IMPLEMENTED_PHASE1")
        print("VERDICT=PASS"); return 0
    except (OSError,csv.Error,ValueError) as exc:
        print(f"VERDICT=FAIL\nFAIL_REASON={exc}",file=sys.stderr); return 1

if __name__=="__main__":
    raise SystemExit(main())