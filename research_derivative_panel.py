"""Build an hourly historical spot/perpetual/OI panel, no outcome scoring."""
import json
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from binance_minute import digest, ms, next_month, fetch
from forecast_journal import new_file
from research_absorb import build_hourly, hidx, UTC
from research_derivative_sources import ROOT, FIRST, END, HOUR, FAMILIES, cached, parse_hours, parse_metrics

AUDIT_SHA = "961e715769370f2368767198f49cb89c043a6179a49f8ee3c765b474e3ce9e24"
DAY = timedelta(days=1)
ERRORS = (OSError, ValueError, KeyError, TypeError, IndexError, zipfile.BadZipFile)


def oi_hour(samples, t):
    """Require exact timestamps, no filling or selecting a later observation."""
    a = datetime.fromtimestamp(t/1000, UTC)
    b = a + timedelta(minutes=55)
    return {"oi_start": samples[a][0] if a in samples else None,
            "oi_last_55": samples[b][0] if b in samples else None,
            "oi_start_notional": samples[a][1] if a in samples else None,
            "oi_last_55_notional": samples[b][1] if b in samples else None}


def join_hour(t, spot, fut, premium, oi):
    i = hidx(datetime.fromtimestamp(t/1000, UTC))
    s = None
    if spot["valid"][i]:
        q = float(spot["qv"][i])
        s = {"open": float(spot["open"][i]), "close": float(spot["close"][i]),
             "low": float(spot["low"][i]), "quote": q,
             "signed_quote": float(2*spot["tbq"][i]-q)}
    return {"hour_open_utc_ms": t, "spot": s, "perpetual": fut.get(t),
            "premium": premium.get(t), **oi_hour(oi, t)}


def run(root=ROOT, fetcher=fetch):
    root = Path(root)
    audit_raw = (root/"source_audit.json").read_bytes()
    if digest(audit_raw) != AUDIT_SHA:
        raise ValueError("Source audit differs from reviewed bytes")
    audit = json.loads(audit_raw)
    target = root/"hourly_panel.json"
    report_path = root/"panel_coverage.json"
    if target.exists() or report_path.exists():
        raise ValueError("Panel or report already exists; preserve originals")
    spot, spot_info = build_hourly()
    if spot_info["manifest_sha256"] != audit["spot_manifest"]["manifest_sha256"]:
        raise ValueError("Spot manifest differs from reviewed audit")
    panel, days, errors, months = [], [], [], []
    for m in audit["months"]:
        d = datetime.strptime(m["month"], "%Y-%m").date()
        stop = next_month(d)
        series = {}
        for family in FAMILIES:
            raw, info = cached(root, family, d, fetcher)
            if info["sha256"] != m[family]["sha256"]:
                raise ValueError("Reviewed monthly archive changed")
            series[family] = parse_hours(raw, family, d)
            if len(series[family]) != m[family]["valid_hours"]:
                raise ValueError("Reviewed monthly coverage changed")
        samples = {}
        day = d
        while day < stop:
            try:
                raw, info = cached(root, "metrics", day, fetcher)
                if day == d and info["sha256"] != m["metrics_first_day"]["sha256"]:
                    raise RuntimeError("Reviewed sample OI archive changed")
                quality, valid = parse_metrics(raw, day, series["klines"], include_samples=True)
                if day == d and any(quality[k] != m["metrics_first_day"][k] for k in quality):
                    raise RuntimeError("Reviewed sample OI quality changed")
                samples.update(valid)
                days.append({"date": day.isoformat(), **info, **quality})
            except ERRORS as exc:
                errors.append({"date": day.isoformat(), "reason": str(exc)})
            day += DAY
        rows = [join_hour(t, spot, series["klines"], series["premiumIndexKlines"], samples)
                for t in range(ms(d), ms(stop), HOUR)]
        joint = sum(all(r[k] is not None for k in ("spot","perpetual","premium")) for r in rows)
        if joint != m["joint_hours"]:
            raise ValueError("Reviewed spot/perpetual/premium coverage changed")
        months.append({"month":m["month"],"hours":len(rows),"joint_market_hours":joint,
                       "oi_start_hours":sum(r["oi_start"] is not None for r in rows),
                       "oi_last_55_hours":sum(r["oi_last_55"] is not None for r in rows),
                       "all_fields_hours":sum(all(r[k] is not None for k in
                           ("spot","perpetual","premium","oi_start","oi_last_55")) for r in rows)})
        panel.extend(rows)
        print(m["month"], "hours:", len(rows), "all fields:", months[-1]["all_fields_hours"],
              "unavailable metric files:",len(errors),flush=True)
    expected = (END-FIRST).days*24
    if len(panel) != expected or len(days)+len(errors) != (END-FIRST).days:
        raise ValueError("Calendar mismatch")
    # The coverage report and panel are linked by the actual panel byte hash.
    # A separate attempt is required if an incomplete panel later needs repair.
    doc = {"version":"derivative-hourly-v1","audit_sha256":AUDIT_SHA,
           "spot_manifest_sha256":spot_info["manifest_sha256"],"rows":panel}
    root.mkdir(parents=True,exist_ok=True)
    panel_sha = new_file(target,doc)
    report = {"kind":"historical_panel_coverage_only","audit_sha256":AUDIT_SHA,
              "panel_sha256":panel_sha,"spot_manifest_sha256":spot_info["manifest_sha256"],
              "expected_days":(END-FIRST).days,"parsed_days":len(days),
              "expected_hours":expected,"months":months,"days":days,"errors":errors,
              "all_fields_hours":sum(m["all_fields_hours"] for m in months),
              "limitations":["No outcomes, state rules or performance scoring.",
                "OI uses exact :00 and :55 observations only. Neither is the next hour's observation.",
                "Naive timestamp UTC and historical original publication not established.",
                "OI is quantity in source units, not net long exposure or observed liquidations.",
                "Hourly OHLC and flows are complete only after the hour closes.",
                "Missing fields are null, never filled. Single venue BTCUSDT."]}
    sha = new_file(report_path,report)
    print("Send:",report_path,"SHA-256:",sha,flush=True)


if __name__ == "__main__":
    run()
