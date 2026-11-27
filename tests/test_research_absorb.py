import copy
import hashlib
import io
import json
import math
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np

import research_absorb as ra
from research_tools import ROOT as PROJECT, registry

UTC = timezone.utc


def bars_from(r, flow, qv):
    close = 100 * np.exp(np.cumsum(r))
    op = np.concatenate([[100.0], close[:-1]])
    return {"valid": np.ones(len(r), bool), "open": op, "close": close,
            "low": np.minimum(op, close) * 0.999, "qv": qv, "tbq": qv * (1 + flow) / 2}


def world(hours=38500, seed=7, impact=0.6):
    """Random walk whose hourly return loads on persistent signed flow; no state-dependent future."""
    rng = np.random.default_rng(seed)
    z = rng.standard_normal(hours)
    x = np.empty(hours)
    x[0] = z[0]
    for i in range(1, hours):
        x[i] = 0.3 * x[i - 1] + z[i]
    x /= x.std()
    r = 0.006 * (impact * x + math.sqrt(1 - impact ** 2) * rng.standard_normal(hours))
    qv = 1e6 * np.exp(0.3 * rng.standard_normal(hours))
    return bars_from(r, np.clip(0.05 * x - 0.01, -0.9, 0.9), qv), r


def minute_zip(day, hours, taker_share, skip=()):
    """One daily Binance-format archive; skip holds (hour, minute) pairs to omit."""
    start = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 1000
    lines = []
    for h in hours:
        for m in range(60):
            if (h, m) in skip:
                continue
            t = start + (h * 60 + m) * 60_000
            buy = 100 * taker_share[h]
            lines.append(f"{t},100,101,99,100.5,1,{t + 59_999},100,5,{buy / 100},{buy},0")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(f"BTCUSDT-1m-{day.isoformat()}.csv", "\n".join(lines) + "\n")
    return buf.getvalue()


def store(root, day, raw, sha=None):
    path = Path(root) / "daily" / f"BTCUSDT-1m-{day.isoformat()}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.with_suffix(".json").write_text(json.dumps({"sha256": sha or hashlib.sha256(raw).hexdigest()}))


class HourlyBarsTest(unittest.TestCase):
    def test_sign_gaps_and_development_boundary(self):
        d1, d2, d3 = (ra.BASE.date() + timedelta(days=i) for i in range(3))
        share = {h: 0.5 for h in range(24)}
        share[0], share[1] = 1.0, 0.0
        with TemporaryDirectory() as tmp:
            store(tmp, d1, minute_zip(d1, range(24), share))
            # Day two: one missing minute in hour 5, hour 7 absent entirely.
            store(tmp, d2, minute_zip(d2, [h for h in range(24) if h != 7], share, skip={(5, 30)}))
            store(tmp, d3, minute_zip(d3, range(24), share))
            stop = ra.BASE + timedelta(days=2)
            bars, data = ra.build_hourly(tmp, stop, progress=None)
            self.assertEqual(len(bars["valid"]), 48)       # day three lies beyond stop and is not loaded
            self.assertEqual(data["archives"], 2)
            self.assertEqual(int(bars["valid"].sum()), 46)
            self.assertFalse(bars["valid"][24 + 5] or bars["valid"][24 + 7])
            self.assertEqual(bars["qv"][24 + 5], 5900)     # partial hour is kept as observed, not filled
            feat = ra.hourly_features(bars)
            self.assertAlmostEqual(feat["q"][0], 6000)     # all volume taker-bought: positive flow
            self.assertAlmostEqual(feat["q"][1], -6000)    # none taker-bought: negative flow
            self.assertTrue(math.isnan(feat["q"][24 + 5]))
            self.assertEqual(data["manifest_sha256"], ra.build_hourly(tmp, stop, progress=None)[1]["manifest_sha256"])

    def test_rejects_changed_archive_and_missing_data(self):
        day = ra.BASE.date()
        with TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ra.build_hourly(tmp, ra.BASE + timedelta(days=1), progress=None)
            store(tmp, day, minute_zip(day, range(24), {h: 0.5 for h in range(24)}), sha="0" * 64)
            with self.assertRaises(ValueError):
                ra.build_hourly(tmp, ra.BASE + timedelta(days=1), progress=None)


class StateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars, cls.r = world()
        cls.feat = ra.hourly_features(cls.bars)
        cls.rows = ra.states(cls.bars, cls.feat)
        cls.n = len(cls.r)

    def test_point_in_time(self):
        row = [r for r in self.rows if r["status"] == "classified"][40]
        c = row["c"]
        bars = {k: v.copy() for k, v in self.bars.items()}
        rng = np.random.default_rng(1)
        bars["close"][c:] *= np.exp(rng.standard_normal(self.n - c))
        bars["tbq"][c:] = bars["qv"][c:] * rng.random(self.n - c)
        bars["valid"][c + 5:c + 400] = False
        again = ra.states(bars, ra.hourly_features(bars))
        before = [r for r in again if r["c"] <= c]
        self.assertEqual(before, [r for r in self.rows if r["c"] <= c])
        self.assertNotEqual(again, self.rows)

    def test_validity_gates_follow_relation_sign(self):
        good = ra.validity(self.bars, self.feat, self.rows)
        self.assertEqual(good["complete_years"], [2018, 2019, 2020, 2021])
        self.assertTrue(all(good["gates"].values()))
        self.assertGreater(good["flow_return_relation_by_year"]["2019"]["hourly_corr"], 0.4)
        self.assertLess(abs(good["placebo_corr_R_with_flow_4_weeks_earlier"]), 0.25)
        bad_bars, _ = world(impact=-0.6)
        feat = ra.hourly_features(bad_bars)
        bad = ra.validity(bad_bars, feat, ra.states(bad_bars, feat))
        self.assertFalse(bad["gates"]["positive_relation_every_complete_year"])

    def test_excess_flow_controls_price_move(self):
        cls = [r for r in self.rows if r["status"] == "classified"]
        e, r, f = (np.array([x[k] for x in cls]) for k in ("E", "R", "F"))
        self.assertLess(abs(ra.corr(e, r)), 0.2)      # orthogonal to the price move out of sample
        self.assertGreater(ra.corr(f, r), 0.4)        # raw flow is not
        a = ra.adequacy(self.rows, self.n)
        self.assertEqual(sum(a["group_counts"].values()), a["origins"])
        self.assertLess(abs(a["primary"]["balance_smd"]["R"]), 0.6)
        self.assertLess(a["primary"]["balance_smd"]["E"], -1.5)
        self.assertTrue(a["primary"]["floor_passed"])
        self.assertIn(a["primary"]["headline_estimate"], ("adjusted", "unadjusted"))

    def test_gap_weeks_are_dropped_not_filled(self):
        ok = [r for r in self.rows if r["status"] == "classified"]
        small, large = ok[20]["c"], ok[30]["c"]
        bars = {k: v.copy() for k, v in self.bars.items()}
        bars["valid"][small - 100:small - 95] = False
        bars["valid"][large - 100:large - 70] = False
        rows = {r["c"]: r for r in ra.states(bars, ra.hourly_features(bars))}
        self.assertEqual(rows[small]["hours"], 163)
        self.assertEqual(rows[large]["status"], "gap_or_warmup")
        self.assertNotIn("R", rows[large])

    def test_coverage_gate_fails_on_frequent_gaps(self):
        bars = {k: v.copy() for k, v in self.bars.items()}
        for r in [r for r in self.rows if r["status"] == "classified"][::6]:
            bars["valid"][r["c"] - 60:r["c"] - 30] = False
        feat = ra.hourly_features(bars)
        self.assertFalse(ra.validity(bars, feat, ra.states(bars, feat))["gates"]["coverage"])

    def test_outcomes_use_entry_and_exit_opens(self):
        rows = self.rows
        orig = ra.origins(rows, self.n)
        out = ra.outcome(self.bars, self.feat, orig[3], {r["c"]: r for r in rows})
        e = orig[3]["c"] + 24
        self.assertAlmostEqual(out["wait7"], math.log(self.bars["open"][e + 168] / self.bars["open"][e]))
        self.assertLessEqual(out["mae7"], 0.0)
        self.assertAlmostEqual(out["wait28"], math.log(self.bars["open"][e + 672] / self.bars["open"][e]))
        self.assertEqual(out["flow_next_week"], next(r for r in rows if r["c"] == orig[3]["c"] + 168)["F"])
        self.assertTrue(all(r["c"] + 24 + 168 < self.n for r in orig))
        bars = {k: v.copy() for k, v in self.bars.items()}
        bars["valid"][e] = False
        self.assertTrue(math.isnan(ra.outcome(bars, self.feat, orig[3], {})["wait7"]))

    def test_null_and_planted_effect(self):
        with patch.object(ra, "RESAMPLES", 400):
            null = ra.compare(self.bars, self.feat, self.rows)
            self.assertEqual(null["primary"]["reading"]["status"], "interval_includes_zero")
            # Same states, but prices drift up for a week after each D-heavy entry.
            r = self.r.copy()
            for row in ra.origins(self.rows, self.n):
                if row["group"] == "D-heavy":
                    r[row["c"] + 24:row["c"] + 192] += 0.15 / 168
            planted_bars = bars_from(r, np.zeros(self.n), self.bars["qv"])
            planted = ra.compare(planted_bars, {"r": r}, self.rows)
        p = planted["primary"]
        self.assertAlmostEqual(p["difference"] - null["primary"]["difference"], 0.15, places=6)
        self.assertGreater(p["ci90"][0], 0)
        self.assertEqual(p["reading"]["status"], "interval_excludes_zero")
        self.assertGreater(p["adjusted"]["difference"], 0.05)
        self.assertEqual(set(p["dose_response"]), {"D-heavy", "D-typical", "D-light"})
        self.assertEqual(len(planted["rows"]), planted["origins"])


class RegimeTest(unittest.TestCase):
    def test_baseline_flow_drift_does_not_set_the_state(self):
        # The venue's baseline taker imbalance steps down by two hourly SDs and stays there.
        bars, _ = world()
        shift = 20000
        bars["tbq"][shift:] -= 0.05 * bars["qv"][shift:]
        rows = ra.states(bars, ra.hourly_features(bars))
        later = [r for r in rows if r["status"] == "classified" and r["c"] > shift + ra.TRANSITION_H]
        heavy = sum(r["tercile"] == "heavy" for r in later[:52]) / 52
        self.assertTrue(0.15 < heavy < 0.55, heavy)

    def test_regime_separated_groups_are_not_comparable(self):
        def row(i, group, year, depth):
            c, k = ra.hidx(datetime(year, 1, 7, tzinfo=UTC)) + 168 * i, i % 20
            return {"status": "classified", "c": c, "time": ra.iso(c), "group": group, "R": -1.0 - 0.01 * k,
                    "F": 0.1 * k, "E": 0.1 * k, "log_sigma": -5.0 + 0.01 * k, "depth": depth - 0.01 * k,
                    "hours": 168, "reference_weeks": 104}
        n = ra.hidx(datetime(2024, 1, 1, tzinfo=UTC))
        spread = [row(i, "D-heavy", 2019 + i % 4, -0.3) for i in range(16)]
        mixed = spread + [row(i + 20, "D-light", 2019 + i % 4, -0.3) for i in range(16)]
        self.assertTrue(ra.adequacy(mixed, n)["primary"]["comparable_groups"])
        one_year = spread + [row(i + 20, "D-light", 2022, -0.3) for i in range(16)]
        self.assertFalse(ra.adequacy(one_year, n)["primary"]["comparable_groups"])
        deep = spread + [row(i + 20, "D-light", 2019 + i % 4, -0.9) for i in range(16)]
        result = ra.adequacy(deep, n)["primary"]
        self.assertTrue(result["floor_passed"])
        self.assertGreater(abs(result["balance_smd"]["depth"]), ra.SMD_OVERLAP)
        self.assertFalse(result["comparable_groups"])

    def test_transition_weeks_excluded(self):
        n = ra.hidx(datetime(2023, 9, 1, tzinfo=UTC))
        rng = np.random.default_rng(3)
        bars = {"valid": np.ones(n, bool), "close": np.full(n, 100.0)}
        feat = {"rho": rng.standard_normal(n), "phi": rng.standard_normal(n), "sigma": np.ones(n)}
        rows = ra.weekly(bars, feat)
        flagged = [r["c"] for r in rows if r["status"] == "fee_transition"]
        for b in (ra.hidx(x) for x in ra.FEE_BOUNDARIES):
            inside = [r["c"] for r in rows if b < r["c"] < b + ra.TRANSITION_H]
            self.assertEqual(len(inside), 5)
            self.assertTrue(set(inside) <= set(flagged))
        self.assertEqual(len(flagged), 10)
        self.assertTrue(all(ra.htime(r["c"]).weekday() == 6
                            and ra.htime(r["c"]).hour == 0 for r in rows))
        self.assertEqual(ra.htime(ra.cutoffs(n, 1)[0]).weekday(), 0)


class LockTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars, _ = world()
        cls.data = {"manifest_sha256": "a" * 64}

    def test_preflight_then_single_locked_outcome_run(self):
        with TemporaryDirectory() as tmp, patch.object(ra, "RESAMPLES", 100), \
                patch.object(ra, "build_hourly", return_value=(self.bars, self.data)):
            root = Path(tmp)
            report = ra.run_preflight(root)
            self.assertFalse(report["outcomes_scored"])
            self.assertTrue(report["outcomes_permitted"])
            raw = (root / "absorb_preflight.json").read_bytes()
            text = raw.decode("utf-8")
            for word in ("wait7", "mae7", "wait28", "flow_next_week"):
                self.assertNotIn(word, text)
            sha = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                ra.run_preflight(root)
            with self.assertRaises(ValueError):
                ra.run_outcomes("0" * 64, root)
            with patch.object(ra, "build_hourly", return_value=(self.bars, {"manifest_sha256": "b" * 64})):
                with self.assertRaises(ValueError):
                    ra.run_outcomes(sha, root)
            other, _ = world(seed=8)
            with patch.object(ra, "build_hourly", return_value=(other, self.data)):
                with self.assertRaises(ValueError):
                    ra.run_outcomes(sha, root)
            self.assertFalse((root / "absorb_outcomes.json").exists())
            result = ra.run_outcomes(sha, root)
            self.assertEqual(result["preflight_sha256"], sha)
            self.assertEqual(len(result["sensitivity_weekday_phase"]), 6)
            self.assertIn("closure_scope", result)
            with self.assertRaises(ValueError):
                ra.run_outcomes(sha, root)

    def test_outcomes_refused_when_preflight_does_not_permit(self):
        short = {k: v[:20000] for k, v in self.bars.items()}
        with TemporaryDirectory() as tmp, patch.object(ra, "build_hourly", return_value=(short, self.data)):
            root = Path(tmp)
            report = ra.run_preflight(root)
            self.assertFalse(report["outcomes_permitted"])
            sha = hashlib.sha256((root / "absorb_preflight.json").read_bytes()).hexdigest()
            with self.assertRaises(ValueError):
                ra.run_outcomes(sha, root)
            self.assertEqual(ra.main(["outcomes", "--preflight-sha256", sha]), 1)


class SmallStatisticsTest(unittest.TestCase):
    def test_helpers(self):
        self.assertAlmostEqual(ra.smd([0, 1, 2], [1, 2, 3]), -1.0)
        self.assertIsNone(ra.smd([1], [1, 2]))
        self.assertEqual(ra.reading([0.01, 0.02])["status"], "interval_excludes_zero")
        wide = ra.reading([-0.02, 0.025])
        self.assertEqual(wide["status"], "interval_includes_zero")
        self.assertEqual(wide["rules_out_absolute_difference_of_at_least"], {"1%": False, "3%": True, "5%": True})
        a, b = ra.block_indices(50, 4, 20), ra.block_indices(50, 4, 20)
        self.assertEqual(a.shape, (20, 50))
        self.assertTrue((a == b).all() and a.max() < 50)
        self.assertTrue(((a[:, 1] - a[:, 0]) % 50 == 1).all())
        self.assertEqual(ra.clean({"x": np.float64("nan"), "y": np.int64(2), "z": (np.bool_(True),)}),
                         {"x": None, "y": 2, "z": [True]})
        y = np.array([1.0, 2.0, 3.0, 5.0, math.nan])
        g = np.array(["D-heavy", "D-heavy", "D-light", "D-light", "D-heavy"])
        self.assertAlmostEqual(ra.mean_diff(y, g, ra.PRIMARY), -2.5)

    def test_registry_entry_is_complete_and_descriptive(self):
        obj, rows = registry(PROJECT)
        entry = rows["ABSORB-001"]
        self.assertTrue(set(obj["new_study_policy"]["required"]) <= set(entry))
        self.assertTrue(entry["kind"].startswith("descriptive"))
        self.assertIn("prior_exposure", entry)
        self.assertEqual(entry["implementation_files"], ["research_absorb.py"])
        self.assertTrue((PROJECT / entry["protocol_files"][0]).exists())


if __name__ == "__main__":
    unittest.main()
