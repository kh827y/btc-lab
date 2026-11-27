"""DELEVER-001 frozen preflight only. No forward outcome scoring."""
import json
import math
import statistics
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from binance_minute import digest, ms
from forecast_journal import new_file
from research_derivative_sources import ROOT, FIRST, END, HOUR

PANEL_SHA = "485143815dfaa44054b90bfeee284ca513aea1deafd917126d50e3709f6e90cc"
COVERAGE_SHA = "229a8a7d7a0ab65b9cfd0927b9420309e7022720f4327cc4f25c1aa6d87058b5"
VERSION = "DELEVER-001-descriptive-v1"
SHOCK_RATIO = 0.95
OI_RATIO = 0.95


def positive(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def boundary_ratio(rows, field):
    first, last = rows[0].get(field), rows[-1].get(field)
    a = first.get("open") if first else None
    b = last.get("close") if last else None
    return b/a if positive(a) and positive(b) else None


def complete_flow(rows, field):
    bars = [r.get(field) for r in rows]
    if any(b is None for b in bars):
        return None
    total = sum(b["quote"] for b in bars)
    return sum(b["signed_quote"] for b in bars)/total if total > 0 else None


def day_features(rows, prior):
    ratio = boundary_ratio(rows, "spot")
    a, b = rows[0].get("oi_start"), rows[-1].get("oi_last_55")
    oi = b/a if positive(a) and positive(b) else None
    spot = [r.get("spot") for r in rows]
    premium = [r.get("premium") for r in rows]
    p = all(v is not None for v in premium)
    history = [math.log(v) for v in prior if v is not None]
    valid_history = len(prior) == len(history) == 28
    return {"price_change": ratio-1 if ratio is not None else None,
            "oi_change": oi-1 if oi is not None else None,
            "group": "contraction" if oi is not None and oi <= OI_RATIO else
                     "other" if oi is not None else "unknown",
            "drop_band": "10plus" if ratio is not None and ratio <= .9 else "5to10",
            "spot_flow_share": complete_flow(rows, "spot"),
            "perpetual_flow_share": complete_flow(rows, "perpetual"),
            "spot_low_from_open": min(v["low"] for v in spot)/spot[0]["open"]-1 if all(v is not None for v in spot) else None,
            "premium_change": premium[-1]["close"]-premium[0]["open"] if p else None,
            "premium_mean_close": statistics.mean(v["close"] for v in premium) if p else None,
            "prior28_log_intraday_sum": sum(history) if valid_history else None,
            "prior28_log_intraday_sd": statistics.stdev(history) if valid_history else None,
            "valid_hours": {k: sum(r.get(k) is not None for r in rows) for k in ("spot","perpetual","premium")}}


def select(rows):
    """Chronological first eligible price-only shocks; unknown boundaries censor."""
    if len(rows) % 24:
        raise ValueError("Incomplete calendar")
    episodes, missing, counts = [], [], Counter()
    prior, next_day = [], 0
    for i in range(0, len(rows), 24):
        day, block = i//24, rows[i:i+24]
        stamp = block[0]["hour_open_utc_ms"]
        date = datetime.fromtimestamp(stamp/1000, timezone.utc).date().isoformat()
        ratio = boundary_ratio(block, "spot")
        if ratio is None:
            missing.append(date)
        if day < next_day:
            counts["cooldown_days"] += 1
        elif ratio is None:
            counts["unknown_eligible_days"] += 1
            next_day = day+7
        elif ratio <= SHOCK_RATIO:
            counts["selected_shocks"] += 1
            next_day = day+7
            features = day_features(block, prior[-28:])
            entry = stamp+25*HOUR
            # Calendar only. No lookup of any forward numeric data.
            episodes.append({"shock_date":date,"entry_utc_ms":entry,
                             "calendar_eligible7": i+25+168 < len(rows), **features})
        else:
            counts["eligible_nonshock_days"] += 1
        prior.append(ratio)
    return episodes, missing, dict(counts)


def summary(episodes):
    eligible = [r for r in episodes if r["calendar_eligible7"]]
    groups = {}
    for group in ("contraction","other","unknown"):
        subset = [r for r in eligible if r["group"] == group]
        item = {"n":len(subset),"years":dict(Counter(r["shock_date"][:4] for r in subset)),
                "bands":dict(Counter(r["drop_band"] for r in subset))}
        for key in ("price_change","oi_change","prior28_log_intraday_sum","prior28_log_intraday_sd",
                    "spot_flow_share","perpetual_flow_share","premium_change","premium_mean_close","spot_low_from_open"):
            v = [r[key] for r in subset if r[key] is not None]
            item[key] = {"n":len(v),"median":statistics.median(v) if v else None,
                         "min":min(v) if v else None,"max":max(v) if v else None}
        groups[group] = item
    a,b = groups["contraction"],groups["other"]
    common = [k for k in ("5to10","10plus") if min(a["bands"].get(k,0),b["bands"].get(k,0)) >= 5]
    return {"groups":groups,"common_bands_with_five_each":common,
            "reporting_floor_met":min(a["n"],b["n"]) >= 10 and bool(common),
            "outcomes_authorized":False}


def run(root=ROOT):
    root = Path(root)
    target = root/"delever_preflight.json"
    if target.exists():
        raise ValueError("Preflight already exists; preserve original")
    raw = (root/"hourly_panel.json").read_bytes()
    if digest(raw) != PANEL_SHA or digest((root/"panel_coverage.json").read_bytes()) != COVERAGE_SHA:
        raise ValueError("Reviewed input hash mismatch")
    panel = json.loads(raw)
    rows = panel["rows"]
    if panel["version"] != "derivative-hourly-v1" or len(rows) != (END-FIRST).days*24:
        raise ValueError("Panel version or length mismatch")
    for i,r in enumerate(rows):
        if r["hour_open_utc_ms"] != ms(FIRST)+i*HOUR:
            raise ValueError("Noncontiguous calendar")
    episodes,missing,counts = select(rows)
    report = {"protocol":VERSION,"panel_sha256":PANEL_SHA,"coverage_sha256":COVERAGE_SHA,
              "kind":"descriptive_preflight_only","forward_outcomes_computed":False,
              "counts":counts,"missing_boundary_dates":missing,
              "episodes":episodes,"summary":summary(episodes),
              "limitations":["One venue; OI contraction is not liquidation proof.",
                             "Price history already exposed; no confirmation.",
                             "Seven-day spacing avoids overlapping primary windows but not dependence.",
                             "Reporting floor is not a statistical power test."]}
    sha = new_file(target, report)
    print("Send:",target,"SHA-256:",sha,flush=True)


if __name__ == "__main__":
    run()
