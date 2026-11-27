"""ABSORB-001: price response to executed spot selling. Descriptive only; see ABSORB_PROTOCOL.md.

preflight: measurement validity and sample adequacy, never forward outcomes.
outcomes:  one locked run, only against a reviewed preflight hash.
"""
import argparse
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from binance_minute import FIRST, MINUTE, ROOT as MINUTE_ROOT, digest, filename, iter_klines, periods
from forecast_journal import encode, new_file

VERSION = "ABSORB-001-descriptive-v1"
ROOT = Path(__file__).resolve().parent / "data" / "research" / "absorb_v1"
UTC = timezone.utc
BASE = datetime(2017, 8, 17, tzinfo=UTC)
DEV_END = datetime(2024, 1, 1, tzinfo=UTC)  # exclusive; later bars are never loaded
HOUR_MS = 3_600_000
SCALE_H, SCALE_MIN = 672, 538     # 28 days of hours, at least 80% valid
WEEK_H, WEEK_MIN = 168, 160
REF_WEEKS, REF_MIN = 104, 52
DEPTH_H = 8760
ENTRY_LAG_H = 24                  # Sunday 00:00 cutoff, Monday 00:00 entry (lab convention)
# Binance zero-fee BTC spot programme: start, and end for BTCUSDT (official announcements).
FEE_BOUNDARIES = (datetime(2022, 7, 8, 14, tzinfo=UTC), datetime(2023, 3, 22, tzinfo=UTC))
TRANSITION_H = WEEK_H + SCALE_H   # weeks whose scaling windows straddle a boundary
BLOCK_WEEKS, BLOCK_SENSITIVITY, RESAMPLES, SEED = 4, 13, 10_000, 20261127
FLOOR_N, FLOOR_YEARS = 10, 3
SMD_LIMIT = 0.25
MDE_Z = 1.645 + 0.842             # two-sided 10% test, 80% power
PRIMARY, SECONDARY = ("D-heavy", "D-light"), ("N-heavy", "N-light")
MAGNITUDES = (0.01, 0.03, 0.05)


def hidx(t):
    return int((t - BASE).total_seconds() // 3600)


def htime(i):
    return BASE + timedelta(hours=int(i))


def iso(i):
    return htime(i).strftime("%Y-%m-%dT%H:%MZ")


def clean(x):
    """JSON-safe: numpy scalars to Python, non-finite numbers to None."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [clean(v) for v in x]
    if isinstance(x, (np.bool_, bool)):
        return bool(x)
    if isinstance(x, (np.integer, int)):
        return int(x)
    if isinstance(x, (np.floating, float)):
        return float(x) if math.isfinite(x) else None
    return x


# ---------- data: verified local minute archives -> hourly bars ----------

def archive_files(minute_root, stop):
    """Local archives covering [FIRST, stop). A monthly file may be replaced by its daily files."""
    root = Path(minute_root)
    found, missing = [], []
    for kind, label, a, b in periods(FIRST, stop.date()):
        path = root / kind / filename(label)
        if path.exists():
            found.append((label, a, b, path))
            continue
        days = [a + timedelta(days=d) for d in range((b - a).days)] if kind == "monthly" else [a]
        for day in days:
            p = root / "daily" / filename(day.isoformat())
            if p.exists():
                found.append((day.isoformat(), day, day + timedelta(days=1), p))
            else:
                missing.append(day.isoformat())
    return found, missing


def build_hourly(minute_root=MINUTE_ROOT, stop=DEV_END, progress=print):
    """Aggregate accepted 1m rows to UTC hours. Missing minutes are never filled."""
    found, missing = archive_files(minute_root, stop)
    if not found:
        raise ValueError(f"No Binance minute archives under {minute_root}; run download_minutes.bat first")
    n = hidx(stop)
    count = np.zeros(n, np.int16)
    qv, tbq = np.zeros(n), np.zeros(n)
    op, cl, lo = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.inf)
    base_ms = int(BASE.timestamp()) * 1000
    manifest = []
    for label, a, b, path in found:
        raw = path.read_bytes()
        meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if digest(raw) != meta["sha256"]:
            raise ValueError(f"Archive {path.name} does not match its recorded SHA-256")
        manifest.append({"file": path.name, "sha256": meta["sha256"]})
        for row in iter_klines(raw, label, a, b):
            t = int(row[0])
            i = (t - base_ms) // HOUR_MS
            if not 0 <= i < n:
                continue
            m = (t // MINUTE) % 60
            count[i] += 1
            qv[i] += float(row[7])
            tbq[i] += float(row[10])
            lo[i] = min(lo[i], float(row[3]))
            if m == 0:
                op[i] = float(row[1])
            if m == 59:
                cl[i] = float(row[4])
        if progress:
            progress(f"read {path.name}", flush=True)
    valid = (count == 60) & (qv > 0)
    bars = {"valid": valid, "open": op, "close": cl, "low": lo, "qv": qv, "tbq": tbq}
    data = {"archives": len(manifest), "missing_archive_days": len(missing),
            "missing_archive_examples": missing[:10], "hours": n, "valid_hours": int(valid.sum()),
            "end_exclusive": stop.isoformat(),
            "manifest_sha256": hashlib.sha256(encode(manifest)).hexdigest()}
    return bars, data


# ---------- point-in-time features ----------

def hourly_features(bars):
    """Within-hour return and signed taker quote flow, scaled by strictly prior 28 days."""
    v = bars["valid"]
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(v, np.log(bars["close"] / bars["open"]), np.nan)
    q = np.where(v, 2 * bars["tbq"] - bars["qv"], np.nan)
    n = len(r)
    sigma, sq = np.full(n, np.nan), np.full(n, np.nan)
    for h in range(SCALE_H, n):
        w = v[h - SCALE_H:h]
        if w.sum() < SCALE_MIN:
            continue
        x = r[h - SCALE_H:h][w]
        s_r, s_q = math.sqrt(float(np.mean(x * x))), float(np.std(q[h - SCALE_H:h][w]))
        if s_r > 0 and s_q > 0:
            sigma[h], sq[h] = s_r, s_q
    return {"r": r, "q": q, "sigma": sigma, "sq": sq, "rho": r / sigma, "phi": q / sq}


def cutoffs(n, phase=0):
    """Weekly cutoff hour indices: 00:00 UTC, Sunday + phase days."""
    first = (6 - BASE.weekday()) % 7 * 24 + 24 * phase
    return range(first, n, WEEK_H)


def weekly(bars, feat, phase=0):
    """Standardized 7-day return R and net taker flow F from hours strictly before each cutoff."""
    v, n = bars["valid"], len(bars["valid"])
    boundaries = [hidx(b) for b in FEE_BOUNDARIES]
    rows = []
    for c in cutoffs(n, phase):
        row = {"c": c, "time": iso(c), "status": "gap_or_warmup"}
        rows.append(row)
        if c < WEEK_H:
            continue
        if any(b < c < b + TRANSITION_H for b in boundaries):
            row["status"] = "fee_transition"
            continue
        rho, phi = feat["rho"][c - WEEK_H:c], feat["phi"][c - WEEK_H:c]
        ok = v[c - WEEK_H:c] & np.isfinite(rho) & np.isfinite(phi)
        k = int(ok.sum())
        if k < WEEK_MIN or not math.isfinite(feat["sigma"][c]):
            continue
        row.update(status="ok", hours=k, R=float(rho[ok].sum() / math.sqrt(k)),
                   F=float(phi[ok].sum() / math.sqrt(k)), log_sigma=math.log(feat["sigma"][c]),
                   depth=depth(bars, c))
    return rows


def depth(bars, c):
    """Log distance of the last valid close from the trailing 365-day closing high; None if unknown."""
    if c < DEPTH_H:
        return None
    w = bars["valid"][c - DEPTH_H:c]
    if w.mean() < 0.8 or not w[-WEEK_H:].any():
        return None
    closes = bars["close"][c - DEPTH_H:c][w]
    return float(math.log(closes[-1] / closes.max()))


def classify(rows):
    """Down state and excess-flow tercile against the prior 104 weeks on the same clock."""
    for i, row in enumerate(rows):
        if row["status"] != "ok":
            continue
        ref = [x for x in rows[max(0, i - REF_WEEKS):i] if "R" in x]
        if len(ref) < REF_MIN:
            row["status"] = "reference_short"
            continue
        rr, fr = np.array([x["R"] for x in ref]), np.array([x["F"] for x in ref])
        if rr.std() == 0:
            row["status"] = "reference_short"
            continue
        g, a = np.polyfit(rr, fr, 1)
        low, high = np.percentile(fr - (a + g * rr), [100 / 3, 200 / 3])
        e = row["F"] - (a + g * row["R"])
        down = row["R"] <= np.percentile(rr, 100 / 3)
        tercile = "heavy" if e <= low else "light" if e >= high else "typical"
        row.update(status="classified", E=float(e), down=bool(down), tercile=tercile,
                   group=("D-" if down else "N-") + tercile, reference_weeks=len(ref))
    return rows


def states(bars, feat, phase=0):
    return classify(weekly(bars, feat, phase))


def origins(rows, n, lag=ENTRY_LAG_H):
    """Classified weeks whose 7-day outcome window lies inside the loaded period (calendar only)."""
    return [r for r in rows if r["status"] == "classified" and r["c"] + lag + WEEK_H < n]


# ---------- small statistics ----------

def corr(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 3 or x[ok].std() == 0 or y[ok].std() == 0:
        return None
    return float(np.corrcoef(x[ok], y[ok])[0, 1])


def smd(a, b):
    """Standardized mean difference with pooled SD."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if len(a) < 2 or len(b) < 2:
        return None
    s = math.sqrt((a.var(ddof=1) + b.var(ddof=1)) / 2)
    return float((a.mean() - b.mean()) / s) if s > 0 else None


def mean_diff(y, g, pair):
    a, b = y[(g == pair[0]) & np.isfinite(y)], y[(g == pair[1]) & np.isfinite(y)]
    return float(a.mean() - b.mean()) if len(a) and len(b) else math.nan


def adjusted_diff(y, g, cov, pair):
    """Group coefficient from OLS of y on group, R, log volatility and drawdown depth."""
    keep = np.isin(g, pair) & np.isfinite(y) & np.isfinite(cov).all(axis=1)
    x = np.column_stack([np.ones(keep.sum()), g[keep] == pair[0], cov[keep]])
    if len(x) < x.shape[1] + 2 or np.linalg.matrix_rank(x) < x.shape[1]:
        return math.nan
    return float(np.linalg.lstsq(x, y[keep], rcond=None)[0][1])


def block_indices(n, block, resamples, seed=SEED):
    """Circular moving-block bootstrap over the chronological origin sequence."""
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(resamples, math.ceil(n / block)))
    return ((starts[:, :, None] + np.arange(block)) % n).reshape(resamples, -1)[:, :n]


def interval(stat, n, block=BLOCK_WEEKS):
    resamples = RESAMPLES
    values = np.array([stat(i) for i in block_indices(n, block, resamples)])
    good = values[np.isfinite(values)]
    if len(good) < resamples / 2:
        return {"ci90": None, "discarded_resamples": int(len(values) - len(good))}
    return {"ci90": [float(v) for v in np.percentile(good, [5, 95])],
            "discarded_resamples": int(len(values) - len(good))}


def reading(ci):
    """Pre-committed wording; magnitudes are log-return sizes the interval rules out."""
    if ci is None:
        return {"status": "no_interval"}
    lo, hi = ci
    return {"status": "interval_excludes_zero" if lo > 0 or hi < 0 else "interval_includes_zero",
            "rules_out_absolute_difference_of_at_least":
                {f"{m:.0%}": bool(-m < lo and hi < m) for m in MAGNITUDES}}


def describe(y):
    y = y[np.isfinite(y)]
    if not len(y):
        return {"n": 0}
    return {"n": int(len(y)), "mean": float(y.mean()), "median": float(np.median(y)),
            "q25": float(np.percentile(y, 25)), "q75": float(np.percentile(y, 75)),
            "sd": float(y.std(ddof=1)) if len(y) > 1 else None, "share_positive": float((y > 0).mean())}


# ---------- stage A: measurement validity (no forward outcomes) ----------

def complete_years(n):
    return [y for y in range(BASE.year + 1, htime(n).year + 1)
            if hidx(datetime(y + 1, 1, 1, tzinfo=UTC)) <= n]


def validity(bars, feat, rows):
    n = len(bars["valid"])
    year = np.array([htime(i).year for i in range(0, n, 24)]).repeat(24)[:n]
    rho, phi = feat["rho"], feat["phi"]
    ok = np.isfinite(rho) & np.isfinite(phi)
    days = n // 24
    day_ok = ok[:days * 24].reshape(days, 24).sum(axis=1) >= 23
    day_r = np.where(day_ok, np.nansum(rho[:days * 24].reshape(days, 24), axis=1), np.nan)
    day_f = np.where(day_ok, np.nansum(phi[:days * 24].reshape(days, 24), axis=1), np.nan)
    day_year = year[:days * 24:24]
    week = [r for r in rows if "R" in r]
    week_year = np.array([htime(r["c"] - 1).year for r in week])
    wr, wf = np.array([r["R"] for r in week]), np.array([r["F"] for r in week])
    years = complete_years(n)
    by_year = {}
    for y in sorted(set(year.tolist())):
        h = ok & (year == y)
        slope = float(np.polyfit(phi[h], rho[h], 1)[0]) if h.sum() > 2 and phi[h].std() > 0 else None
        w = week_year == y
        by_year[str(y)] = {
            "valid_scaled_hours": int(h.sum()), "hourly_corr": corr(rho[h], phi[h]), "hourly_slope": slope,
            "daily_corr": corr(day_r[day_year == y], day_f[day_year == y]),
            "weekly_n": int(w.sum()), "weekly_corr": corr(wr[w], wf[w]),
            "weekly_R_mean_sd": [float(wr[w].mean()), float(wr[w].std())] if w.sum() > 1 else None,
            "weekly_F_mean_sd": [float(wf[w].mean()), float(wf[w].std())] if w.sum() > 1 else None}
    sign_ok = bool(years) and all((by_year[str(y)]["hourly_corr"] or 0) > 0
                                  and (by_year[str(y)]["weekly_corr"] or 0) > 0 for y in years)

    # Coverage from the first classified week; fee transitions are excluded by design.
    first = next((i for i, r in enumerate(rows) if r["status"] == "classified"), None)
    cover = {"overall": None, "by_year": {}}
    if first is not None:
        tail = [r for r in rows[first:] if r["status"] != "fee_transition"]
        cover["overall"] = sum(r["status"] == "classified" for r in tail) / len(tail)
        for y in years:
            sub = [r for r in tail if htime(r["c"] - 1).year == y]
            if sub:
                cover["by_year"][str(y)] = sum(r["status"] == "classified" for r in sub) / len(sub)
    coverage_ok = bool(cover["overall"] is not None and cover["overall"] >= 0.95
                       and all(v >= 0.90 for v in cover["by_year"].values()))

    cls = [r for r in rows if r["status"] == "classified"]
    e, cr, cf = (np.array([r[k] for r in cls]) for k in ("E", "R", "F"))
    ortho = {"corr_E_R": corr(e, cr), "corr_E_F": corr(e, cf)}
    ortho["warning_price_control_weak"] = bool(ortho["corr_E_R"] is not None and abs(ortho["corr_E_R"]) > 0.3)

    fee = {}
    b0, b1 = (hidx(b) for b in FEE_BOUNDARIES)
    with np.errstate(invalid="ignore", divide="ignore"):
        raw_imbalance = feat["q"] / bars["qv"]
    for name, a, b in (("year_before", b0 - DEPTH_H, b0), ("zero_fee", b0, b1), ("year_after", b1, b1 + DEPTH_H)):
        a, b = max(a, 0), min(b, n)
        if b - a > WEEK_H and ok[a:b].sum() > WEEK_H:
            s = slice(a, b)
            fee[name] = {"hours": int(ok[s].sum()), "hourly_corr": corr(rho[s], phi[s]),
                         "sd_raw_imbalance": float(np.nanstd(raw_imbalance[s])),
                         "sd_scaled_flow": float(np.nanstd(phi[s]))}
    return {"gates": {"positive_relation_every_complete_year": sign_ok, "coverage": coverage_ok},
            "complete_years": years, "flow_return_relation_by_year": by_year,
            "weekly_status_counts": dict(Counter(r["status"] for r in rows)),
            "classification_coverage": cover, "price_orthogonality_out_of_sample": ortho,
            "placebo_corr_R_with_flow_4_weeks_earlier": corr(wr[4:], wf[:-4]) if len(week) > 8 else None,
            "fee_regime": fee}


# ---------- stage B: sample adequacy and covariate balance (no forward outcomes) ----------

def adequacy(rows, n):
    orig = origins(rows, n)
    groups = Counter(r["group"] for r in orig)
    by_year = {}
    for r in orig:
        by_year.setdefault(r["group"], Counter())[str(htime(r["c"]).year)] += 1

    def column(group, k):
        return np.array([math.nan if r[k] is None else r[k] for r in orig if r["group"] == group], float)

    def balance(pair):
        return {k: smd(column(pair[0], k), column(pair[1], k)) for k in ("R", "log_sigma", "depth", "E")}

    def means(pair):
        return {g: {k: float(np.nanmean(column(g, k))) if np.isfinite(column(g, k)).any() else None
                    for k in ("R", "F", "E", "log_sigma", "depth")} for g in pair}

    def size(pair):
        na, nb = groups[pair[0]], groups[pair[1]]
        years = [len(by_year.get(g, {})) for g in pair]
        share = [max(by_year[g].values()) / groups[g] if groups[g] else None for g in pair]
        mde = MDE_Z * math.sqrt(1 / na + 1 / nb) if na and nb else None
        scale = [math.exp(r["log_sigma"]) * math.sqrt(WEEK_H) for r in orig if r["group"] in pair]
        return {"n": [na, nb], "calendar_years": years, "largest_year_share": share,
                "minimum_detectable_difference_sigma_units": mde,
                "minimum_detectable_log_return_approx": mde * float(np.median(scale)) if mde and scale else None,
                "floor_passed": bool(min(na, nb) >= FLOOR_N and min(years) >= FLOOR_YEARS)}

    primary, bal = size(PRIMARY), balance(PRIMARY)
    imbalanced = [k for k in ("R", "log_sigma", "depth") if bal[k] is not None and abs(bal[k]) > SMD_LIMIT]
    return {"origins": len(orig), "group_counts": dict(groups),
            "group_counts_by_year": {g: dict(c) for g, c in by_year.items()},
            "primary": {**primary, "balance_smd": bal, "group_means": means(PRIMARY),
                        "imbalanced_covariates": imbalanced,
                        "headline_estimate": "adjusted" if imbalanced else "unadjusted"},
            "secondary": {**size(SECONDARY), "balance_smd": balance(SECONDARY), "group_means": means(SECONDARY)},
            "mde_assumption": "Standardized 7-day outcome SD of about 1; two-sided 10%, 80% power. "
                              "Planning figure, not a significance test."}


def origin_rows(rows, n):
    keys = ("time", "group", "R", "F", "E", "log_sigma", "depth", "hours", "reference_weeks")
    return [{k: r[k] for k in keys} for r in origins(rows, n)]


def origin_hash(rows, n):
    return hashlib.sha256(encode(clean([[r["time"], r["group"]] for r in origins(rows, n)]))).hexdigest()


def preflight_report(bars, data):
    feat = hourly_features(bars)
    rows = states(bars, feat)
    n = len(bars["valid"])
    val, adq = validity(bars, feat, rows), adequacy(rows, n)
    permitted = all(val["gates"].values()) and adq["primary"]["floor_passed"]
    return clean({
        "protocol": VERSION, "kind": "measurement_validity_and_sample_adequacy",
        "confirmation_authorized": False, "outcomes_scored": False, "data": data,
        "validity": val, "adequacy": adq, "outcomes_permitted": permitted,
        "origins_sha256": origin_hash(rows, n), "origin_rows": origin_rows(rows, n),
        "limitations": [
            "No forward return, risk or flow outcome is computed in this report.",
            "Single venue (Binance BTCUSDT spot); taker side is impatience, not identity or intent.",
            "Low price response to selling is compatible with spot bids, arbitrage against perpetual longs, "
            "support from other venues, or measurement noise; it is not evidence of persistent demand.",
            "Weekly origins share market cycles; counts are not independent observations.",
            "Development-period prices were already used by earlier BTC-Lab studies."]})


# ---------- stage C: forward outcomes (locked) ----------

def outcome(bars, feat, row, rows_by_c, lag=ENTRY_LAG_H):
    v, n = bars["valid"], len(bars["valid"])
    e, end = row["c"] + lag, row["c"] + lag + WEEK_H
    out = dict.fromkeys(("wait7", "wait7_std", "mae7", "rv_ratio", "wait28", "flow_next_week"), math.nan)
    if end >= n or not (v[e] and v[end]):
        return out
    p0 = bars["open"][e]
    unit = math.exp(row["log_sigma"]) * math.sqrt(WEEK_H)
    out["wait7"] = math.log(bars["open"][end] / p0)
    out["wait7_std"] = out["wait7"] / unit
    w = v[e:end]
    if w.sum() >= WEEK_MIN:
        out["mae7"] = float(np.log(bars["low"][e:end][w] / p0).min())
        r = feat["r"][e:end][w]
        out["rv_ratio"] = math.log(math.sqrt(float((r * r).sum()) * WEEK_H / w.sum()) / unit)
    if e + 4 * WEEK_H < n and v[e + 4 * WEEK_H]:
        out["wait28"] = math.log(bars["open"][e + 4 * WEEK_H] / p0)
    nxt = rows_by_c.get(row["c"] + WEEK_H)
    if nxt is not None and "F" in nxt:
        out["flow_next_week"] = nxt["F"]
    return out


def compare(bars, feat, rows, lag=ENTRY_LAG_H, full=True):
    """Outcome table for one weekly clock. full=False keeps only the primary contrast."""
    n = len(bars["valid"])
    orig = origins(rows, n, lag)
    m = len(orig)
    if not m:
        return {"origins": 0}
    by_c = {r["c"]: r for r in rows}
    outs = [outcome(bars, feat, r, by_c, lag) for r in orig]
    g = np.array([r["group"] for r in orig])
    cov = np.array([[r["R"], r["log_sigma"], math.nan if r["depth"] is None else r["depth"]] for r in orig])
    y = {k: np.array([o[k] for o in outs]) for k in outs[0]}

    def contrast(key, pair, block=BLOCK_WEEKS):
        d = mean_diff(y[key], g, pair)
        ci = interval(lambda i: mean_diff(y[key][i], g[i], pair), m, block)
        return {"difference": d, **ci, "reading": reading(ci["ci90"]),
                "groups": {p: describe(y[key][g == p]) for p in pair}}

    primary = contrast("wait7", PRIMARY)
    if not full:
        return {"origins": m, "primary": primary}
    adj = adjusted_diff(y["wait7"], g, cov, PRIMARY)
    adj_ci = interval(lambda i: adjusted_diff(y["wait7"][i], g[i], cov[i], PRIMARY), m)
    primary.update(
        ci90_block_13_weeks=interval(lambda i: mean_diff(y["wait7"][i], g[i], PRIMARY), m, BLOCK_SENSITIVITY)["ci90"],
        adjusted={"difference": adj, **adj_ci, "reading": reading(adj_ci["ci90"]),
                  "covariates": ["R", "log_sigma", "depth"]},
        dose_response={p: describe(y["wait7"][g == p]) for p in ("D-heavy", "D-typical", "D-light")})
    down = np.array([p.startswith("D-") for p in g])
    return {"origins": m, "missing_wait7": int((~np.isfinite(y["wait7"])).sum()), "primary": primary,
            "secondary_contrast_not_down": contrast("wait7", SECONDARY),
            "secondary_outcomes_primary_groups": {k: contrast(k, PRIMARY) for k in y if k != "wait7"},
            "price_only_benchmark": {"all": describe(y["wait7"]), "down": describe(y["wait7"][down]),
                                     "not_down": describe(y["wait7"][~down])},
            "rows": [{"time": r["time"], "group": r["group"], **o} for r, o in zip(orig, outs)]}


def outcome_report(bars, data, preflight, preflight_sha):
    feat = hourly_features(bars)
    rows = states(bars, feat)
    n = len(bars["valid"])
    if origin_hash(rows, n) != preflight["origins_sha256"]:
        raise ValueError("Recomputed origins differ from the reviewed preflight")
    main = compare(bars, feat, rows)
    phases = {}
    for p in range(1, 7):
        c = compare(bars, feat, states(bars, feat, p), full=False)
        phases[f"cutoff_plus_{p}_days"] = c.get("primary", c)
    headline = preflight["adequacy"]["primary"]["headline_estimate"]
    return clean({
        "protocol": VERSION, "kind": "descriptive_state_comparison", "confirmation_authorized": False,
        "preflight_sha256": preflight_sha, "data": data, "headline_estimate": headline,
        "units": "Natural-log returns; wait7 > 0 means buying 7 days later cost more.",
        "bootstrap": {"type": "circular moving block over weekly origins", "block_weeks": BLOCK_WEEKS,
                      "resamples": RESAMPLES, "seed": SEED, "interval": "percentile 90%"},
        **main,
        "sensitivity_entry_at_cutoff": compare(bars, feat, rows, lag=0, full=False).get("primary"),
        "sensitivity_weekday_phase": phases,
        "closure_scope": "Closes only this contrast: Binance BTCUSDT spot, 7-day excess taker-flow tercile "
                         "within standardized down weeks, 7-day wait cost, 2018-2023. It does not test other "
                         "venues, horizons, forced-selling events, derivatives context or prospective use, "
                         "and an interval that includes zero while not ruling out large differences is "
                         "unresolved rather than negative.",
        "limitations": [
            "Descriptive; one run; not a significance test and not a trading rule.",
            "Weekly origins share market cycles and volatility regimes; intervals are approximate.",
            "Price outcomes for 2018-2023 were already known to earlier BTC-Lab studies.",
            "Low price response to selling does not identify persistent demand."]})


# ---------- commands ----------

def run_preflight(root=ROOT, minute_root=MINUTE_ROOT, stop=DEV_END):
    root, target = Path(root), Path(root) / "absorb_preflight.json"
    if target.exists():
        raise ValueError("Preflight already exists; preserve the original")
    bars, data = build_hourly(minute_root, stop)
    report = preflight_report(bars, data)
    root.mkdir(parents=True, exist_ok=True)
    sha = new_file(target, report)
    v, a = report["validity"], report["adequacy"]
    print("Validity gates:", v["gates"], flush=True)
    print("Primary groups", PRIMARY, "n =", a["primary"]["n"], "balance SMD", a["primary"]["balance_smd"], flush=True)
    print("Approx. minimum detectable log return:", a["primary"]["minimum_detectable_log_return_approx"], flush=True)
    print("Outcomes permitted:", report["outcomes_permitted"], flush=True)
    print("Preflight SHA-256:", sha, flush=True)
    print("Send:", target, flush=True)
    return report


def run_outcomes(preflight_sha, root=ROOT, minute_root=MINUTE_ROOT, stop=DEV_END):
    root = Path(root)
    source, target = root / "absorb_preflight.json", root / "absorb_outcomes.json"
    if target.exists():
        raise ValueError("Outcome report already exists; one run only")
    raw = source.read_bytes()
    if digest(raw) != preflight_sha.strip().lower():
        raise ValueError("Preflight SHA-256 does not match the reviewed report")
    preflight = json.loads(raw)
    if preflight.get("protocol") != VERSION or preflight.get("outcomes_permitted") is not True:
        raise ValueError("Preflight does not permit outcomes")
    bars, data = build_hourly(minute_root, stop)
    if data["manifest_sha256"] != preflight["data"]["manifest_sha256"]:
        raise ValueError("Minute archives differ from the preflight data")
    report = outcome_report(bars, data, preflight, preflight_sha.strip().lower())
    sha = new_file(target, report)
    p = report["primary"]
    print("Primary difference (D-heavy minus D-light, 7-day log wait cost):", p["difference"], "CI90", p["ci90"], flush=True)
    print("Adjusted:", p["adjusted"]["difference"], "CI90", p["adjusted"]["ci90"],
          "headline:", report["headline_estimate"], flush=True)
    print("Outcome SHA-256:", sha, flush=True)
    print("Send:", target, flush=True)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("preflight", help="validity and adequacy; no forward outcomes")
    out = sub.add_parser("outcomes", help="one locked outcome run")
    out.add_argument("--preflight-sha256", required=True, help="hash of the reviewed absorb_preflight.json")
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            run_preflight()
        else:
            run_outcomes(args.preflight_sha256)
    except (OSError, ValueError, KeyError) as exc:
        print("ABSORB-001 stopped:", exc, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
