"""Offline archive task. Executed inside an offline Docker container only.

Initial task: verify two local archives, then report coverage. No forward
outcomes, no downloads, no write to the archive.
"""
import json
from datetime import date, timedelta
from pathlib import Path
import sys

sys.path.insert(0, "/app")
from binance_minute import digest, inspect, next_month, FIRST

ARCHIVE=Path("/archive")

def run():
    checks=[]
    for kind in ("daily","monthly"):
        choices=sorted((ARCHIVE/kind).glob("BTCUSDT-1m-*.zip"),reverse=True)
        p=next((p for p in choices if p.with_suffix(".json").is_file()),None)
        if p is None:
            checks.append({"kind":kind,"status":"unavailable"})
            continue
        try:
            label=p.stem.removeprefix("BTCUSDT-1m-")
            start=max(date.fromisoformat(label+"-01" if kind=="monthly" else label),FIRST)
            stop=next_month(start) if kind=="monthly" else start+timedelta(days=1)
            if p.stat().st_size>32*1024**2:
                raise ValueError("Archive too large")
            raw=p.read_bytes()
            meta=json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))
            sha=digest(raw)
            if sha!=meta.get("sha256"):
                raise ValueError("SHA-256 mismatch")
            quality=inspect(raw,label,start,stop)
            checks.append({"kind":kind,"status":"ok","label":label,"sha256":sha,
                           "rows":quality["rows"],"expected":quality["expected"],
                           "missing":quality["missing"],"rejected_rows":quality["rejected_rows"]})
        except Exception as exc:
            checks.append({"kind":kind,"status":"error","error":type(exc).__name__+": "+str(exc)[:250]})
    return {"version":"docker-archive-v1","status":"ok" if all(x["status"]=="ok" for x in checks) else "error",
            "checks":checks,"scope":"Two sampled BTCUSDT spot minute archives; not a full history audit."}

if __name__=="__main__":
    report=run()
    print("BTC_LAB_REPORT "+json.dumps(report,ensure_ascii=True,allow_nan=False),flush=True)
