"""Local accumulation of validated rolling series. Not a point-in-time archive."""
from pathlib import Path
import sqlite3
import pandas as pd
from history_logic import METRICS, OI, CVD, OPTIONS, series_for

DB=Path(__file__).resolve().parent/"data"/"history.sqlite3"
ROLLING={OI,CVD,OPTIONS}
# Bump the version if the definition of a rolling metric changes.
VERSION=1

def connect(path=DB):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    con=sqlite3.connect(path,timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS observations (metric TEXT, version INTEGER, ts TEXT, value REAL, first_seen TEXT, last_seen TEXT, PRIMARY KEY(metric,version,ts))")
    con.execute("CREATE TABLE IF NOT EXISTS sources (path TEXT PRIMARY KEY, fetched TEXT)")
    return con

def save_archive(path,doc,db=DB,now=None):
    if path not in ROLLING:raise ValueError("Not a rolling archive")
    seen=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    rows=[]
    for label,(p,*_) in METRICS.items():
        if p!=path:continue
        s=series_for(label,doc,seen)
        if s.empty:raise ValueError("Empty rolling archive")
        rows.extend((label,VERSION,t.isoformat(),float(v) if pd.notna(v) else None,seen.isoformat(),seen.isoformat()) for t,v in s.items())
    with connect(db) as con:
        con.executemany("""INSERT INTO observations VALUES (?,?,?,?,?,?)
            ON CONFLICT(metric,version,ts) DO UPDATE SET value=excluded.value,last_seen=excluded.last_seen
            WHERE excluded.last_seen>=observations.last_seen""",rows)
        con.execute("""INSERT INTO sources VALUES (?,?) ON CONFLICT(path) DO UPDATE SET fetched=excluded.fetched
            WHERE excluded.fetched>=sources.fetched""",(path,seen.isoformat()))

def saved_series(label,db=DB):
    if not Path(db).exists():return pd.Series(dtype=float,index=pd.DatetimeIndex([],tz="UTC"),name=label)
    with connect(db) as con:
        rows=con.execute("SELECT ts,value FROM observations WHERE metric=? AND version=? ORDER BY ts",(label,VERSION)).fetchall()
    if not rows:return pd.Series(dtype=float,index=pd.DatetimeIndex([],tz="UTC"),name=label)
    s=pd.Series([v for _,v in rows],index=pd.to_datetime([t for t,_ in rows],utc=True),dtype=float,name=label).sort_index()
    freq=METRICS[label][2]
    return s.reindex(pd.date_range(s.index.min(),s.index.max(),freq=freq)) if freq else s

def last_fetch(path,db=DB):
    if not Path(db).exists():return None
    with connect(db) as con:
        row=con.execute("SELECT fetched FROM sources WHERE path=?",(path,)).fetchone()
    return row[0] if row else None

def coverage(s,freq,now=None):
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    valid=s.dropna()
    return {"observations":len(valid),"gaps":int(s.isna().sum()) if freq else None,
            "first":valid.index[0].isoformat() if len(valid) else None,
            "last":valid.index[-1].isoformat() if len(valid) else None,
            "lag_days":round((now-valid.index[-1]).total_seconds()/86400,2) if len(valid) else None}
