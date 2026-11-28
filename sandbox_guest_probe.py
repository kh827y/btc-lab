"""One-time offline isolation/readiness probe; runs ONLY inside Sandbox."""
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path

ARCHIVE=Path(r"C:\btc_archive")
CANARY=Path(r"C:\btc_canary")
OUT=Path(r"C:\btc_output")

def main():
    report={"version":"sandbox-probe-v1","python":sys.version.split()[0],
            "archive_read":False,"archive_hash_match":False,
            "readonly_canary":False,"archive_file":None,"errors":[]}
    try:
        if (CANARY/"read-me.txt").read_text(encoding="utf-8")!="BTC-Lab isolation probe":
            raise ValueError("Wrong canary contents")
        try:
            with (CANARY/"unexpected-write.txt").open("x",encoding="utf-8") as f:
                f.write("Only a disposable test file, never archive data.")
            report["errors"].append("Read-only test folder unexpectedly writable")
        except PermissionError:
            report["readonly_canary"]=True
    except Exception as exc:
        report["errors"].append("canary: "+type(exc).__name__+": "+str(exc)[:180])
    try:
        candidates=sorted(ARCHIVE.glob("daily/BTCUSDT-1m-*.zip"),reverse=True)
        candidates+=sorted(ARCHIVE.glob("monthly/BTCUSDT-1m-*.zip"),reverse=True)
        path=next((p for p in candidates if p.with_suffix(".json").is_file()),None)
        if path is None:
            raise ValueError("No existing archive with provenance sidecar")
        report["archive_file"]=path.relative_to(ARCHIVE).as_posix()
        if path.stat().st_size>32*1024*1024:
            raise ValueError("Unexpected archive size")
        raw=path.read_bytes()
        meta=json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        report["archive_sha256"]=hashlib.sha256(raw).hexdigest()
        report["archive_hash_match"]=report["archive_sha256"]==meta.get("sha256")
        if not report["archive_hash_match"]:
            raise ValueError("Archive SHA-256 does not match sidecar")
        with zipfile.ZipFile(path) as z:
            entries=z.infolist()
            if len(entries)!=1 or entries[0].file_size>32*1024*1024:
                raise ValueError("Unexpected ZIP contents")
            with z.open(entries[0]) as f:
                if not f.readline(4096):
                    raise ValueError("Empty archive")
        report["archive_read"]=True
    except Exception as exc:
        report["errors"].append("archive: "+type(exc).__name__+": "+str(exc)[:180])
    report["status"]="ok" if all(report[k] for k in ("archive_read","archive_hash_match","readonly_canary")) and not report["errors"] else "error"
    with (OUT/"probe.json").open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2,ensure_ascii=False)
    print(report["status"],flush=True)

if __name__=="__main__":
    main()
