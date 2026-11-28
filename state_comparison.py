"""Compare two existing state packets. Descriptive changes, never a trading signal."""
import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from data_logic import parse_utc, is_real_number

LIMIT=256*1024

def observed(row):
    raw=row.get("observed_at")
    precision=row.get("time_precision")
    if precision=="date_only" and isinstance(raw,str):
        try:
            d=date.fromisoformat(raw)
            return d if d.isoformat()==raw else None
        except ValueError:
            return None
    if precision=="timestamp":
        return parse_utc(raw)
    return None

def records(packet):
    families=packet["families"]
    result={}
    for family,rows in families.items():
        for row in rows:
            key=(family,row["id"])
            if key in result:
                raise ValueError("Duplicate metric identity")
            result[key]=row
    return result

def identity(row):
    # Do not silently compare different sources, instruments, windows or units.
    keys=("unit","scope","comparison_key","source","source_field","time_precision")
    return tuple(row.get(k) for k in keys)

def compare(before,after):
    a,b=(parse_utc(p.get("assembled_utc")) for p in (before,after))
    if a is None or b is None or a>=b:
        raise ValueError("Expected distinct, chronological packet assembly timestamps")
    old,new=records(before),records(after)
    items=[]
    for key in sorted(old.keys()|new.keys()):
        x,y=old.get(key,{}),new.get(key,{})
        item={"family":key[0],"id":key[1],"status_before":x.get("status"),
              "status_after":y.get("status"),"observed_before":x.get("observed_at"),
              "observed_after":y.get("observed_at"),"unit":y.get("unit"),
              "delta":None,"status":"unavailable"}
        if not x or not y:
            item["status"]="metric_added_or_removed"
        elif identity(x)!=identity(y):
            item["status"]="incompatible_identity"
        elif x.get("status")!="usable" or y.get("status")!="usable":
            item["status"]="not_usable_in_both"
        elif not all(is_real_number(r.get("value")) for r in (x,y)):
            item["status"]="invalid_value"
        elif not all(isinstance(y.get(k),str) and y[k] for k in ("unit","scope","source","source_field")):
            item["status"]="unverified_identity"
        else:
            t,u=observed(x),observed(y)
            if t is None or u is None:
                item["status"]="invalid_observation_time"
            elif u<t:
                item["status"]="observation_regressed"
            elif u==t:
                item["status"]="same_observation" if x["value"]==y["value"] else "same_observation_revised"
            else:
                delta=y["value"]-x["value"]
                if is_real_number(delta):
                    item.update(status="new_observation",value_before=x["value"],value_after=y["value"],delta=delta,
                                observation_gap_days=(u-t).days if y["time_precision"]=="date_only" else None,
                                observation_gap_hours=(u-t).total_seconds()/3600 if y["time_precision"]=="timestamp" else None)
                else:
                    item["status"]="invalid_delta"
        items.append(item)
    counts={}
    for r in items:
        counts[r["status"]]=counts.get(r["status"],0)+1
    return {"version":"state-comparison-v1","before_assembled_utc":a.isoformat(),
            "after_assembled_utc":b.isoformat(),"counts":counts,"metrics":items,
            "limitations":["Usability at each original packet assembly, not current freshness.",
                "Only base metric families; no comparisons of derived breadth or separate primary macro block yet.",
                "Deltas are in original units, not relative returns, inflows or independent votes.",
                "Rolling windows overlap; change in window total is not intervening executed flow.",
                "Same observation time with changed value is a revision, not new evidence.",
                "Source identity is declared metadata, not proof that upstream methodology remained unchanged."]}

def read(path):
    with Path(path).open("rb") as f:
        raw=f.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("Packet exceeds limit")
    return json.loads(raw),hashlib.sha256(raw).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("before",type=Path)
    p.add_argument("after",type=Path)
    p.add_argument("output",type=Path)
    args=p.parse_args()
    a,ha=read(args.before)
    b,hb=read(args.after)
    r=compare(a,b)
    r.update(before_sha256=ha,after_sha256=hb)
    with args.output.open("x",encoding="utf-8") as f:
        json.dump(r,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps(r["counts"],ensure_ascii=False))

if __name__=="__main__":
    main()
