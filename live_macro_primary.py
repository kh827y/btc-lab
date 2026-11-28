"""Current macro measurements from the original publishers; no historical backfill."""
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from live_macro import summarize

LIMIT=4*1024*1024
NY="https://markets.newyorkfed.org/api/rates/unsecured/effr/search.json"
TREASURY="https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
H10="https://www.federalreserve.gov/releases/h10/summary/jrxwtfb_nb.htm"
A="{http://www.w3.org/2005/Atom}"
D="{http://schemas.microsoft.com/ado/2007/08/dataservices}"
M="{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"

def fetch(url):
    with urlopen(Request(url,headers={"User-Agent":"BTC-Lab public data","Accept":"*/*"}),timeout=15) as r:
        a,b=urlsplit(url),urlsplit(r.geturl())
        if (a.scheme,a.netloc,a.path)!=(b.scheme,b.netloc,b.path):
            raise ValueError("Unexpected redirect")
        raw=r.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("Response exceeds limit")
    return raw

def number(v,positive=False):
    if isinstance(v,bool):
        raise ValueError("Boolean value")
    x=float(v)
    if not math.isfinite(x) or positive and x<=0:
        raise ValueError("Invalid numeric value")
    return x

def effr(raw,day):
    rows=json.loads(raw)["refRates"]
    if not isinstance(rows,list) or len(rows)>46:
        raise ValueError("Unexpected EFFR rows")
    out={}
    for row in rows:
        d=date.fromisoformat(row["effectiveDate"])
        if row["type"]!="EFFR" or not day-timedelta(days=45)<=d<=day or d in out:
            raise ValueError("Invalid EFFR date/type")
        out[d]=number(row["percentRate"])
    if not out:
        raise ValueError("No EFFR observations")
    return out

def treasury(raw,year,day):
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("XML declarations rejected")
    root=ET.fromstring(raw)
    if root.tag!=A+"feed":
        raise ValueError("Expected Treasury Atom feed")
    out={"DGS2":{},"DGS10":{}}
    seen=set()
    for entry in root.findall(A+"entry"):
        props=entry.find(A+"content/"+M+"properties")
        if props is None:
            raise ValueError("Missing Treasury properties")
        stamp=props.findtext(D+"NEW_DATE")
        if not stamp or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00(?:\.0+)?",stamp):
            raise ValueError("Unexpected Treasury date")
        d=date.fromisoformat(stamp[:10])
        if d.year!=year or d>day or d in seen:
            raise ValueError("Invalid/duplicate Treasury date")
        seen.add(d)
        if d<day-timedelta(days=45):
            continue
        for s,tag in (("DGS2","BC_2YEAR"),("DGS10","BC_10YEAR")):
            field=props.find(D+tag)
            if field is None:
                raise ValueError("Missing Treasury maturity")
            if field.attrib.get(M+"null")=="true" or not (field.text or "").strip():
                continue
            out[s][d]=number(field.text)
    if not seen:
        raise ValueError("No Treasury entries")
    return out

class Tables(HTMLParser):
    """Collect all rows, including tables nested in legacy layout tables."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[]
        self.tables=[]
        self.headings=[]
        self.heading=None
    def handle_starttag(self,tag,attrs):
        if tag=="h5":
            self.heading=[]
        if tag=="table":
            self.stack.append({"rows":[],"row":None,"cell":None})
        if not self.stack:
            return
        t=self.stack[-1]
        if tag=="tr":
            if t["row"] is not None:
                t["rows"].append(t["row"])
            t["row"]=[]
            t["cell"]=None
        if tag in ("td","th") and t["row"] is not None:
            if t["cell"] is not None:
                self.end_cell(t)
            t["cell"]=[]
    @staticmethod
    def end_cell(t):
        if t["cell"] is not None:
            t["row"].append(" ".join("".join(t["cell"]).split()))
            t["cell"]=None
    def handle_data(self,data):
        if self.heading is not None:
            self.heading.append(data)
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(data)
    def handle_endtag(self,tag):
        if tag=="h5" and self.heading is not None:
            self.headings.append(" ".join("".join(self.heading).split()))
            self.heading=None
        if not self.stack:
            return
        t=self.stack[-1]
        if tag in ("td","th"):
            self.end_cell(t)
        if tag in ("tr","table") and t["row"] is not None:
            self.end_cell(t)
            t["rows"].append(t["row"])
            t["row"]=None
        if tag=="table":
            self.tables.append(t["rows"])
            self.stack.pop()

def broad(raw,day):
    p=Tables()
    p.feed(raw.decode("utf-8"))
    if "Nominal Broad Dollar Index - Daily Index" not in p.headings:
        raise ValueError("Unexpected H.10 series heading")
    candidates=[]
    for table in p.tables:
        headers=[i for i,row in enumerate(table) if [x.casefold() for x in row]==["date","rate"]]
        if len(headers)==1:
            rows=table[headers[0]+1:]
            # Ignore layout/header tables, not missing or malformed observations.
            if any(len(row)==2 and re.fullmatch(r"\d{1,2}-[A-Za-z]{3}-\d{2}",row[0]) for row in rows):
                candidates.append(rows)
    if len(candidates)!=1:
        raise ValueError("Ambiguous H.10 table: "+str(len(candidates))+" data candidates in "+str(len(p.tables))+" tables")
    out={}
    seen=set()
    for row in candidates[0]:
        if not row or not any(row):
            continue
        if len(row)!=2:
            raise ValueError("Unexpected H.10 row")
        d=datetime.strptime(row[0],"%d-%b-%y").date()
        if d>day or d in seen:
            raise ValueError("Future/duplicate H.10 date")
        seen.add(d)
        if d<day-timedelta(days=45) or row[1] in ("","ND","N/A","."):
            continue
        out[d]=number(row[1],True)
    if not out:
        raise ValueError("No recent H.10 observations")
    return out

def collect(root,fetcher=fetch,clock=lambda:datetime.now(timezone.utc)):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    day=clock().date()
    items=[]
    def request(url,name,parser):
        raw=fetcher(url)
        if len(raw)>LIMIT:
            raise ValueError("Response exceeds limit")
        received=clock()
        with (root/name).open("xb") as f:
            f.write(raw)
        return parser(raw),{"source":url,"raw_path":name,
            "raw_sha256":hashlib.sha256(raw).hexdigest(),"retrieved_utc":received.isoformat()}
    def item(series,values,source,errors,eff=False):
        base=summarize(values,series,day) if values else {
            "id":series,"unit":"index" if series=="DTWEXBGS" else "percent",
            "status":"unavailable","value":None,"observed_at":None,"changes":{}}
        base.update(source_kind="official_primary",sources=source,errors=errors)
        if eff:
            base.update(id="NYFED_EFFR",comparison_key="NYFED|EFFR|business_day",
                note="NY Fed business-day EFFR, not seven-day DFF; no weekend filling.",
                attribution="Federal Reserve Bank of New York; subject to its Markets Data API terms.")
        else:
            base["comparison_key"]="official_primary|"+series
        items.append(base)
    url=NY+"?"+urlencode({"startDate":(day-timedelta(days=45)).isoformat(),"endDate":day.isoformat()})
    try:
        v,src=request(url,"effr.json",lambda raw:effr(raw,day))
        item("DFF",v,[src],[],True)
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as e:
        item("DFF",{},[],[{"url":url,"error":str(e)[:180]}],True)
    yields={"DGS2":{},"DGS10":{}}
    sources=[]
    errors=[]
    for year in sorted({day.year,(day-timedelta(days=45)).year}):
        url=TREASURY+"?"+urlencode({"data":"daily_treasury_yield_curve","field_tdr_date_value":year})
        try:
            v,src=request(url,"treasury-"+str(year)+".xml",lambda raw:treasury(raw,year,day))
            for s in yields:
                yields[s].update(v[s])
            sources.append(src)
        except (OSError,ValueError,KeyError,TypeError,OverflowError,ET.ParseError) as e:
            errors.append({"url":url,"error":str(e)[:180]})
    for s in yields:
        item(s,yields[s],sources,errors)
    try:
        v,src=request(H10,"h10.html",lambda raw:broad(raw,day))
        item("DTWEXBGS",v,[src],[])
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as e:
        item("DTWEXBGS",{},[],[{"url":H10,"error":str(e)[:180]}])
    return {"version":"live-macro-primary-v1","series":items,"limitations":[
        "Primary observations, not original release vintages. Retrieval time is not publication time.",
        "NY Fed EFFR business-day series is distinct from DFF calendar-day series.",
        "Treasury nominal par constant-maturity 2y/10y and Fed H.10 daily nominal broad dollar.",
        "Calendar freshness caps and bounded previous-date comparisons inherited from live_macro; no fill.",
        "Do not count upstream and primary measurements of the same underlying series twice."]}
