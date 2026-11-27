"""Fixed historical FOMC document packages for EVENT-FACT-PILOT-v1, no model calls."""
import base64
import json
import re
import time
from datetime import date,datetime,timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request,urlopen
from zoneinfo import ZoneInfo

from binance_minute import digest
from forecast_journal import new_file

ROOT=Path(__file__).resolve().parent/"data"/"research"/"event_fact_v1"
BASE="https://www.federalreserve.gov"
DATES=("20221214","20230201","20230322","20230503","20230614","20230726",
       "20230920","20231101","20231213")
LIMIT=2*1024*1024
NY=ZoneInfo("America/New_York")


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]
        self.hidden=0

    def handle_starttag(self,tag,attrs):
        if tag in ("script","style","noscript"):
            self.hidden+=1
        elif not self.hidden and tag in ("p","div","li","h1","h2","h3","h4","br","blockquote"):
            self.parts.append(" ")

    def handle_endtag(self,tag):
        if tag in ("script","style","noscript") and self.hidden:
            self.hidden-=1
        elif not self.hidden:
            self.parts.append(" ")

    def handle_data(self,data):
        if not self.hidden:
            self.parts.append(data)


def visible(raw):
    parser=Visible()
    parser.feed(raw.decode("utf-8-sig"))
    return " ".join("".join(parser.parts).split())


def event_date(s):
    return datetime.strptime(s,"%Y%m%d").date()


def release(d):
    local=datetime.combine(event_date(d),datetime.min.time(),NY).replace(hour=14)
    return local.isoformat(),local.astimezone(timezone.utc).isoformat()


def address(d,kind):
    if d not in DATES or kind not in ("statement","note","meeting"):
        raise ValueError("Source outside fixed pilot")
    if kind=="meeting":
        return BASE+"/monetarypolicy/fomcpresconf"+d+".htm"
    return BASE+"/newsevents/pressreleases/monetary"+d+("a1" if kind=="note" else "a")+".htm"


def extract(raw,d,kind):
    text=visible(raw)
    dt=event_date(d)
    day=dt.strftime("%B")+r"\s+0?"+str(dt.day)+r",\s+"+str(dt.year)
    if kind=="meeting":
        # Only evidence of simultaneous publication; do not expose whole meeting page.
        clock=r"\(Released\s+"+day+r"\s+at\s+2:00\s+p\.m\.\)"
        note=re.search(r"Implementation Note\s*"+clock,text,re.I)
        statement=re.search(r"FOMC Meeting Statement\s*:[\s\S]{0,100}?"+clock,text,re.I)
        if not note or not statement:
            raise ValueError("Meeting page does not establish same-time release")
        return {"statement_release_evidence":statement.group(0),"note_release_evidence":note.group(0)}
    title="Federal Reserve issues FOMC statement" if kind=="statement" else r"Implementation Note issued "+day
    start=re.search(day+r"\s+"+title,text,re.I)
    if not start:
        raise ValueError("Missing expected release title/date")
    tail=text[start.end():].strip()
    stop=re.search(r"For media inquiries|Last Update\s*:",tail,re.I)
    if not stop:
        raise ValueError("Missing release body boundary")
    body=tail[:stop.start()].strip()
    if kind=="statement":
        expected=datetime.fromisoformat(release(d)[0]).astimezone(NY).tzname()
        time_match=re.match(r"For release at 2:00 p\.m\.\s+"+expected+r"\b",body,re.I)
        if not time_match or "Voting for the monetary policy action" not in body or "target range" not in body:
            raise ValueError("Unverified statement time or body")
        body=body[time_match.end():].strip()
        # Related-link text sometimes follows body before contact line.
        body=re.split(r"Implementation Note issued "+day,body,maxsplit=1,flags=re.I)[0].strip()
    elif "Decisions Regarding Monetary Policy Implementation" not in body or "target range" not in body:
        raise ValueError("Missing implementation note body")
    if len(body)<300 or len(body)>20000:
        raise ValueError("Unexpected document body length")
    return body


def fetch(url):
    req=Request(url,headers={"User-Agent":"BTC-Lab research","Accept":"text/html"})
    with urlopen(req,timeout=25) as response:
        if response.geturl()!=url:
            raise ValueError("Unexpected redirect")
        raw=response.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("Response exceeds limit")
    return raw


def document(root,d,kind,fetcher=fetch):
    url=address(d,kind)
    target=Path(root)/"cache"/(d+"_"+kind+".json")
    if target.exists():
        saved=json.loads(target.read_bytes())
        raw=base64.b64decode(saved["raw_base64"],validate=True)
        if saved["url"]!=url or digest(raw)!=saved["sha256"]:
            raise ValueError("Cached source identity mismatch")
    else:
        raw=fetcher(url)
        if len(raw)>LIMIT:
            raise ValueError("Response exceeds limit")
        extract(raw,d,kind)
        saved={"url":url,"raw_base64":base64.b64encode(raw).decode("ascii"),
               "sha256":digest(raw),"retrieved_utc":datetime.now(timezone.utc).isoformat()}
        target.parent.mkdir(parents=True,exist_ok=True)
        new_file(target,saved)
        time.sleep(.3)
    local,utc=release(d)
    return {"date":event_date(d).isoformat(),"kind":kind,"url":url,
            "source_sha256":saved["sha256"],"retrieved_utc":saved["retrieved_utc"],
            "published_local":local,"published_utc":utc,"text":extract(raw,d,kind)}


def run(root=ROOT,fetcher=fetch):
    root=Path(root)
    target=root/"fomc_2023_packages.json"
    if target.exists():
        raise ValueError("Completed package exists; preserve original")
    records=[];errors=[]
    for prev,d in zip(DATES,DATES[1:]):
        print("FOMC",d,flush=True)
        try:
            old=document(root,prev,"statement",fetcher)
            current=document(root,d,"statement",fetcher)
            timing=document(root,d,"meeting",fetcher)
            note=document(root,d,"note",fetcher)
            records.append({"event_date":event_date(d).isoformat(),
               "cutoff_utc":current["published_utc"],"documents":[old,current,note],
               "publication_evidence":timing,"expectations":"unknown_not_in_packet"})
        except (OSError,ValueError,KeyError,TypeError) as exc:
            errors.append({"event_date":event_date(d).isoformat(),"error":str(exc)})
    report={"version":"event-fact-2023-packages-v1","calendar":"https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            "expected_events":8,"complete_events":len(records),"errors":errors,"packages":records,
            "limitations":["Retrospective retrieval, not proof of original publication vintage.",
                "Only extracted official statements and implementation notes; meeting page used only for timing.",
                "No projections, press conferences, minutes, market data or expectations.",
                "No model calls or scoring. Missing events are not replaced."]}
    root.mkdir(parents=True,exist_ok=True)
    if errors:
        # Preserve failed attempts; allow a later retry using cached validated documents.
        stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target=root/("incomplete_"+stamp+".json")
    new_file(target,report)
    print("Complete",len(records),"/ 8. Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
