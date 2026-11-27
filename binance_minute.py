"""Verified local Binance BTCUSDT spot 1m archives, independent of the panel."""
import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

BASE = "https://data.binance.vision/data/spot"
ROOT = Path(__file__).resolve().parent / "data" / "binance_1m"
FIRST = date(2017, 8, 17)
MINUTE = 60_000
MAX_BYTES = 32 * 1024 * 1024
MAX_CSV = 32 * 1024 * 1024
SCHEMA = 1


def ms(day):
    return int(datetime.combine(day, datetime.min.time(), timezone.utc).timestamp()) * 1000


def next_month(day):
    return date(day.year + (day.month == 12), day.month % 12 + 1, 1)


def periods(start, stop):
    """Half-open date range; use monthly files where the calendar month is complete."""
    while start < stop:
        month = start.replace(day=1)
        end = next_month(month)
        if start == max(month, FIRST) and end <= stop:
            yield "monthly", month.isoformat()[:7], start, end
            start = end
        else:
            yield "daily", start.isoformat(), start, start + timedelta(days=1)
            start += timedelta(days=1)


def filename(label):
    return f"BTCUSDT-1m-{label}.zip"


def source(kind, label):
    return f"{BASE}/{kind}/klines/BTCUSDT/1m/{filename(label)}"


def fetch(url, limit):
    # Only fixed Binance URLs are supplied by this module.
    with urlopen(url, timeout=60) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Archive exceeds download limit")
    return data


def digest(data):
    return hashlib.sha256(data).hexdigest()


def expected_hash(raw, name):
    fields = raw.decode("ascii").strip().split()
    if (len(fields) != 2 or not re.fullmatch("[0-9a-fA-F]{64}", fields[0])
            or fields[1].lstrip("*") != name):
        raise ValueError("Invalid Binance checksum file")
    return fields[0].lower()


def iter_klines(raw, label, start, stop):
    """Yield 12 original fields, times normalized to integer UTC milliseconds.
    Reject an entire archive on malformed, duplicate or out-of-order rows.
    Missing minutes are allowed and counted separately; never synthesized.
    """
    name = filename(label).replace(".zip", ".csv")
    lo, hi = ms(start), ms(stop)
    previous = None
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        if len(entries) != 1 or entries[0].filename != name or entries[0].file_size > MAX_CSV:
            raise ValueError("Unexpected ZIP member or size")
        with archive.open(entries[0]) as member, io.TextIOWrapper(member, encoding="ascii", newline="") as stream:
            for row in csv.reader(stream):
                if len(row) != 12:
                    raise ValueError("Invalid kline column count")
                try:
                    t, close = int(row[0]), int(row[6])
                    if t >= 10**14 or close >= 10**14:
                        if not (t >= 10**14 and close >= 10**14 and t % 1000 == 0 and close % 1000 == 999):
                            raise ValueError("Invalid microsecond boundary")
                        t, close = t // 1000, close // 1000
                    if not (lo <= t < hi and t % MINUTE == 0 and close == t + MINUTE - 1):
                        raise ValueError("Invalid minute boundary or date")
                    if previous is not None and t <= previous:
                        raise ValueError("Duplicate or unordered minute")
                    o, h, l, c, v, q, buy_v, buy_q = (Decimal(row[i]) for i in (1, 2, 3, 4, 5, 7, 9, 10))
                    trades = int(row[8])
                    if not all(x.is_finite() for x in (o,h,l,c,v,q,buy_v,buy_q)):
                        raise ValueError("Non-finite numeric value")
                    if not (0 < l <= min(o,c) <= max(o,c) <= h and
                            0 <= buy_v <= v and 0 <= buy_q <= q and trades >= 0):
                        raise ValueError("Invalid OHLC/volume")
                except (InvalidOperation, ValueError) as exc:
                    raise ValueError(f"Invalid Binance candle at {row[0]}: {exc}") from exc
                previous = t
                row[0], row[6] = str(t), str(close)
                yield row


def inspect(raw, label, start, stop):
    cursor = ms(start)
    gaps = []
    count = 0
    for row in iter_klines(raw, label, start, stop):
        t = int(row[0])
        if t > cursor:
            gaps.append([cursor, t])
        cursor = t + MINUTE
        count += 1
    if not count:
        raise ValueError("Empty minute archive")
    if cursor < ms(stop):
        gaps.append([cursor, ms(stop)])
    missing = sum((b-a)//MINUTE for a,b in gaps)
    return {"rows": count, "expected": (ms(stop)-ms(start))//MINUTE,
            "missing": missing, "gaps_utc_ms": gaps}


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def json_write(path, obj):
    atomic_write(path, json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"))


def ensure_archive(root, kind, label, start, stop, fetcher=fetch, refresh=False):
    """Save original ZIP plus provenance only after checksum and full CSV validation."""
    url = source(kind, label)
    path = root / kind / filename(label)
    meta_path = path.with_suffix(".json")
    identity = {"schema": SCHEMA, "url": url, "start": start.isoformat(), "stop": stop.isoformat()}
    if not refresh and path.exists() and meta_path.exists():
        try:
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            if all(old.get(k) == v for k,v in identity.items()) and digest(path.read_bytes()) == old["sha256"]:
                return {**old, "cached": True}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
    want = expected_hash(fetcher(url + ".CHECKSUM", 4096), path.name)
    raw = fetcher(url, MAX_BYTES)
    if digest(raw) != want:
        raise ValueError("SHA-256 mismatch")
    quality = inspect(raw, label, start, stop)
    meta = {**identity, **quality, "sha256": want,
            "downloaded_utc": datetime.now(timezone.utc).isoformat()}
    atomic_write(path, raw)
    json_write(meta_path, meta)
    return {**meta, "cached": False}


def download(root, start, stop, fetcher=fetch, refresh=False):
    root = Path(root)
    results = []
    def one(kind, label, a, b):
        try:
            result = ensure_archive(root, kind, label, a, b, fetcher, refresh)
        except HTTPError as exc:
            if kind == "monthly" and exc.code == 404:
                for d in range((b-a).days):
                    day = a + timedelta(days=d)
                    one("daily", day.isoformat(), day, day+timedelta(days=1))
                return
            result = {"url": source(kind,label), "start": a.isoformat(),
                      "stop": b.isoformat(), "error": f"HTTP {exc.code}"}
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            result = {"url": source(kind,label), "start": a.isoformat(),
                      "stop": b.isoformat(), "error": str(exc)}
        results.append(result)
        print(label, result.get("error") or
              f"{result['rows']} rows, missing {result['missing']}, cached={result['cached']}", flush=True)
        # Update checkpoint after every archive; a crash does not invalidate older ZIPs.
        json_write(root / "audit.json", {"schema": SCHEMA, "start": start.isoformat(),
                   "stop": stop.isoformat(), "complete_scan": False, "archives": results})
    for kind, label, a, b in periods(start, stop):
        one(kind,label,a,b)
    errors = sum("error" in x for x in results)
    rows = sum(x.get("rows",0) for x in results)
    expected = (ms(stop)-ms(start))//MINUTE
    report = {"schema": SCHEMA, "start": start.isoformat(), "stop": stop.isoformat(),
              "complete_scan": True, "archives": results, "errors": errors,
              "rows": rows, "expected": expected, "missing_or_unavailable": expected-rows}
    json_write(root / "audit.json", report)
    print(f"Verified {rows}/{expected} minutes; {errors} failed archives. Audit: {root / 'audit.json'}", flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, default=FIRST)
    parser.add_argument("--through", type=date.fromisoformat,
                        default=datetime.now(timezone.utc).date()-timedelta(days=1))
    parser.add_argument("--refresh", action="store_true", help="Recheck upstream archives")
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()
    if not FIRST <= args.start <= args.through < today:
        parser.error("Range must start on/after 2017-08-17 and end before today UTC")
    result = download(ROOT, args.start, args.through+timedelta(days=1), refresh=args.refresh)
    return int(bool(result["errors"] or result["missing_or_unavailable"]))


if __name__ == "__main__":
    sys.exit(main())
