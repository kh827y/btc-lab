"""Source readiness only: Binance spot/perpetual flow, premium, and timed OI.
No return outcomes, state thresholds or forecasting. Fixed 2020-09..2023-12.
"""
import csv
import io
import json
import math
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from binance_minute import fetch, digest, expected_hash, atomic_write, json_write, ms, next_month
from research_absorb import build_hourly, hidx, UTC
from research_oi import ROOT as OI_ROOT
from forecast_journal import new_file

ROOT = Path(__file__).resolve().parent / "data/research/derivative_source_v1"
FIRST, END = date(2020, 9, 1), date(2024, 1, 1)
BASE = "https://data.binance.vision/data/futures/um"
HOUR = 3600000
LIMIT = 2 * 1024 * 1024
FAMILIES = ("klines", "premiumIndexKlines")


def source(family, d):
    if family == "metrics":
        name = f"BTCUSDT-metrics-{d.isoformat()}.zip"
        return f"{BASE}/daily/metrics/BTCUSDT/{name}", name
    if family not in FAMILIES:
        raise ValueError("Unknown source")
    name = f"BTCUSDT-1h-{d.isoformat()[:7]}.zip"
    return f"{BASE}/monthly/{family}/BTCUSDT/1h/{name}", name


def cached(root, family, d, fetcher=fetch):
    url, name = source(family, d)
    p = root / "cache" / family / name
    # Reuse earlier OI archives read-only, when both original files exist.
    old = OI_ROOT / "cache" / name
    if family == "metrics" and old.exists() and old.with_suffix(".json").exists():
        p = old
    meta = p.with_suffix(".json")
    if p.exists() and meta.exists():
        raw, info = p.read_bytes(), json.loads(meta.read_bytes())
        if info["url"] != url or info["sha256"] != digest(raw):
            raise ValueError("Cached archive identity mismatch")
    else:
        sha = expected_hash(fetcher(url + ".CHECKSUM", 4096), name)
        raw = fetcher(url, LIMIT)
        if digest(raw) != sha:
            raise ValueError("ZIP checksum mismatch")
        info = {"url": url, "sha256": sha, "retrieved_utc": datetime.now(UTC).isoformat()}
        atomic_write(p, raw)
        json_write(meta, info)
    return raw, info


def csv_rows(raw, name):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = z.infolist()
        if len(members) != 1 or members[0].filename != name[:-4] + ".csv" or members[0].file_size > LIMIT:
            raise ValueError("Unexpected ZIP member")
        with z.open(members[0]) as f:
            return list(csv.reader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))


def finite(x):
    x = float(x)
    if not math.isfinite(x):
        raise ValueError("Nonfinite number")
    return x


def parse_hours(raw, family, d):
    _, name = source(family, d)
    rows = csv_rows(raw, name)
    if rows and rows[0][0] in ("open_time", "openTime"):
        rows = rows[1:]
    out = {}
    lo, hi = ms(d), ms(next_month(d))
    previous = -1
    for row in rows:
        if len(row) != 12:
            raise ValueError("Unexpected candle columns")
        t, close = int(row[0]), int(row[6])
        if not lo <= t < hi or t % HOUR or close != t + HOUR - 1 or t <= previous:
            raise ValueError("Invalid hourly time/order")
        previous = t
        o, h, l, c = map(finite, row[1:5])
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid candle OHLC")
        if family == "klines":
            q, buy = finite(row[7]), finite(row[10])
            if l <= 0 or not 0 <= buy <= q:
                raise ValueError("Invalid futures price/flow")
            if q > 0:
                out[t] = {"open": o, "high": h, "low": l, "close": c, "quote": q, "signed_quote": 2*buy-q}
        else:
            # Premium index is a signed dimensionless ratio, not a traded price.
            out[t] = {"open": o, "high": h, "low": l, "close": c}
    if not out:
        raise ValueError("No valid hourly candles")
    return out


def parse_metrics(raw, d, futures, *, include_samples=False):
    _, name = source("metrics", d)
    rows = csv_rows(raw, name)
    if not rows or len(set(rows[0])) != len(rows[0]):
        raise ValueError("Invalid metrics header")
    header = rows[0]
    cols = [header.index(k) for k in ("create_time", "symbol", "sum_open_interest", "sum_open_interest_value")]
    seen, conflicts, rejected, dup = {}, set(), 0, 0
    for row in rows[1:]:
        if len(row) != len(header) or row[cols[1]] != "BTCUSDT":
            raise ValueError("Wrong metrics row/contract")
        stamp = row[cols[0]]
        if len(stamp) == 10:
            rejected += 1
            continue
        t = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        t = t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)
        if t.date() != d:
            raise ValueError("Metrics timestamp outside date")
        try:
            q, v = finite(row[cols[2]]), finite(row[cols[3]])
            if min(q, v) <= 0:
                raise ValueError("Nonpositive OI")
            pair = (q, v)
        except ValueError:
            pair = None
        if t in seen:
            dup += 1
            if seen[t] != pair:
                conflicts.add(t)
        seen[t] = pair
    good = []
    samples = {}
    unmatched = 0
    for t, pair in sorted(seen.items()):
        if pair is None or t in conflicts:
            rejected += 1
            continue
        hour = int(t.timestamp()) // 3600 * HOUR
        bar = futures.get(hour)
        if bar is None or not .9*bar["low"] <= pair[1]/pair[0] <= 1.1*bar["high"]:
            unmatched += 1
            continue
        good.append(t)
        if include_samples:
            samples[t] = pair
    gaps = [(b-a).total_seconds()/60 for a,b in zip(good,good[1:])]
    quality = {"rows": len(rows)-1, "valid_timed": len(good), "duplicates": dup,
            "conflicts": len(conflicts), "rejected": rejected, "unit_or_hour_mismatch": unmatched,
            "hours_covered": len({t.hour for t in good}),
            "five_minute_slots_covered": len({t.hour*12+t.minute//5 for t in good}),
            "max_gap_minutes": max(gaps, default=None),
            "first": good[0].isoformat() if good else None, "last": good[-1].isoformat() if good else None}
    return (quality, samples) if include_samples else quality


def run(root=ROOT, fetcher=fetch):
    root = Path(root)
    target = root / "source_audit.json"
    if target.exists():
        raise ValueError("Audit already exists; preserve original")
    spot, spot_info = build_hourly(progress=None)
    months = []
    d = FIRST
    errors = []
    while d < END:
        result = {"month": d.isoformat()[:7], "expected_hours": (ms(next_month(d))-ms(d))//HOUR}
        series = {}
        for family in FAMILIES:
            try:
                raw, info = cached(root, family, d, fetcher)
                series[family] = parse_hours(raw, family, d)
                result[family] = {**info, "valid_hours": len(series[family])}
            except (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile) as exc:
                errors.append({"month":result["month"], "family":family, "reason":str(exc)})
                series[family] = {}
        both = series["klines"].keys() & series["premiumIndexKlines"].keys()
        result["joint_hours"] = sum(bool(spot["valid"][hidx(datetime.fromtimestamp(t/1000, UTC))]) for t in both)
        # Fixed first day of every month, not chosen from price or OI outcomes.
        try:
            raw, info = cached(root, "metrics", d, fetcher)
            result["metrics_first_day"] = {**info, **parse_metrics(raw, d, series["klines"])}
        except (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile) as exc:
            errors.append({"month":result["month"],"family":"metrics","reason":str(exc)})
        months.append(result)
        print(result["month"], "matched hours",result["joint_hours"],"errors so far",len(errors),flush=True)
        d = next_month(d)
    report = {"kind":"source_readiness_only","start":FIRST.isoformat(),"end_exclusive":END.isoformat(),
              "spot_manifest":spot_info,"months":months,"errors":errors,
              "expected_hours":sum(m["expected_hours"] for m in months),
              "joint_hours":sum(m["joint_hours"] for m in months),
              "metrics_sample_days":len(months),"metrics_days_with_all_24_hours":sum(m.get("metrics_first_day",{}).get("hours_covered")==24 for m in months),
              "limitations":["Metrics sampled on first day of each month only; not full historical OI coverage.",
                 "Naive metrics timestamps interpreted as UTC; historical time convention and original publication unverified.",
                 "Notional/quantity check uses contemporaneous futures hourly price range, not proof of contract semantics.",
                 "Premium index is not funding or exact futures-minus-spot basis.",
                 "No future outcomes, causal classification, or signal assessment."]}
    root.mkdir(parents=True,exist_ok=True)
    sha = new_file(target, report)
    print("Send:",target,"SHA-256:",sha,flush=True)


if __name__ == "__main__":
    run()
