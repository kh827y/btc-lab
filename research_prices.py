"""Local UTC-aligned OHLC access for reproducible research, no network calls."""
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from binance_minute import MINUTE, FIRST, SCHEMA, digest, filename, iter_klines, ms, source

DAY = 1440 * MINUTE
FIELDS = {"open": 0, "high": 1, "low": 2, "close": 3}


def snapshot(audit):
    """Stable archive identity, independent of cache flags and download times."""
    if audit.get("schema") != SCHEMA or audit.get("complete_scan") is not True or audit.get("errors") != 0:
        raise ValueError("Run full download_minutes.bat successfully first")
    result = {k:audit[k] for k in ("schema","start","stop","rows","expected","missing_or_unavailable")}
    result.update(complete_scan=True, errors=0)
    result["archives"] = []
    for item in audit["archives"]:
        if "error" in item:
            raise ValueError("Failed archive in completed audit")
        result["archives"].append({k:item[k] for k in ("url","start","stop","sha256","rows","missing")})
    return result


def snapshot_hash(audit):
    return digest(json.dumps(snapshot(audit),sort_keys=True,separators=(",",":")).encode("utf-8"))


class MinutePrices:
    """Dense UTC minute grid; missing rows are NaN, never interpolated."""
    def __init__(self, start, stop, values):
        if start % MINUTE or stop <= start or stop % MINUTE:
            raise ValueError("Invalid price grid")
        if values.shape != ((stop-start)//MINUTE, 4):
            raise ValueError("Invalid OHLC shape")
        self.start, self.stop, self.values = start, stop, values

    @classmethod
    def load(cls, root, frozen=None):
        root = Path(root)
        audit = snapshot(json.loads((root / "audit.json").read_bytes()) if frozen is None else frozen)
        start, stop = map(date.fromisoformat, (audit["start"], audit["stop"]))
        n = (ms(stop)-ms(start))//MINUTE
        if start != FIRST or not 0 < n <= 20_000_000:
            raise ValueError("Expected complete history starting 2017-08-17")
        values = np.full((n, 4), np.nan, dtype=np.float64)
        cursor, total = start, 0
        for item in audit["archives"]:
            a, b = map(date.fromisoformat, (item["start"],item["stop"]))
            if a != cursor or not a < b <= stop or "error" in item:
                raise ValueError("Archive intervals overlap, are missing or unordered")
            candidates = [(kind,label) for kind,label in
                          (("daily",a.isoformat()),("monthly",a.isoformat()[:7]))
                          if item["url"] == source(kind,label)]
            if len(candidates) != 1:
                raise ValueError("Unexpected archive source")
            kind,label = candidates[0]
            from binance_minute import next_month
            if kind == "daily" and b != a+timedelta(days=1):
                raise ValueError("Invalid daily archive bounds")
            if kind == "monthly" and (a != max(a.replace(day=1),FIRST) or b != next_month(a)):
                raise ValueError("Invalid monthly archive bounds")
            raw = (root/kind/filename(label)).read_bytes()
            if digest(raw) != item["sha256"]:
                raise ValueError("Local archive hash mismatch: "+label)
            count = 0
            for row in iter_klines(raw,label,a,b):
                i = (int(row[0])-ms(start))//MINUTE
                values[i,:] = [float(row[j]) for j in (1,2,3,4)]
                if not np.isfinite(values[i]).all() or (values[i] <= 0).any():
                    raise ValueError("Invalid float OHLC")
                count += 1
            if count != item["rows"] or (ms(b)-ms(a))//MINUTE-count != item["missing"]:
                raise ValueError("Local archive count mismatch: "+label)
            cursor, total = b,total+count
        if cursor != stop or total != audit["rows"] or n != audit["expected"] or n-total != audit["missing_or_unavailable"]:
            raise ValueError("Audit totals mismatch")
        if not total:
            raise ValueError("No usable prices")
        prices = cls(ms(start),ms(stop),values)
        prices.provenance = {"snapshot_sha256":snapshot_hash(audit),"start":start.isoformat(),
                             "stop_exclusive":stop.isoformat(),"rows":total,
                             "expected":n,"missing":n-total}
        return prices

    def point(self, t, field):
        if t % MINUTE:
            raise ValueError("Unaligned minute")
        if not self.start <= t < self.stop:
            return None
        x = self.values[(t-self.start)//MINUTE,FIELDS[field]]
        return float(x) if np.isfinite(x) else None

    def window(self, start, stop, field):
        """Complete half-open interval; return None if any minute unavailable."""
        if start % MINUTE or stop % MINUTE or stop <= start:
            raise ValueError("Invalid window")
        if not self.start <= start < stop <= self.stop:
            return None
        x = self.values[(start-self.start)//MINUTE:(stop-self.start)//MINUTE,FIELDS[field]]
        return x if np.isfinite(x).all() else None

    def reaction(self, t, minutes=30):
        """Previous close through the last fully closed bar at t+minutes."""
        x = self.window(t-MINUTE,t+minutes*MINUTE,"close")
        return None if x is None else float(x[-1]/x[0]-1)

    def prior_state(self, t, days=28):
        """Only previous closed UTC days; use exactly days+1 daily closes."""
        boundary = t//DAY*DAY
        closes = [self.point(boundary-i*DAY-MINUTE,"close") for i in range(days,-1,-1)]
        if any(x is None for x in closes):
            return None,None
        x = np.asarray(closes)
        daily = x[1:]/x[:-1]-1
        return float(x[-1]/x[0]-1),float(np.std(daily,ddof=1))

    def outcome(self, entry, days):
        """Open-to-open return and worst excursion from entry through exit.
        Endpoint return can be known despite an internal gap; excursion cannot.
        """
        exit_time = entry+days*DAY
        a,b = self.point(entry,"open"),self.point(exit_time,"open")
        ret = None if a is None or b is None else b/a-1
        lows = self.window(entry,exit_time,"low")
        worst = None if a is None or b is None or lows is None else min(0.0,float(min(lows.min(),b)/a-1))
        return ret,worst
