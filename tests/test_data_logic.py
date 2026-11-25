import unittest
from datetime import datetime, timezone
from data_logic import (at, average_usable, cvd_value, formatted, hours_since, human_time, label, local_tz,
                        metric_value, orderbook_rows, pct_distance, validate_brief)


def sample():
    return {
        "as_of_utc": "2026-11-23T15:00:00Z",
        "btc_technicals": {"latest_spot_price_usdt": 61000},
        "metric_quality": {"checks": {
            "price.live_spot_quote": {"status": "usable", "reason": None},
            "spot_cvd.original_five.24h": {"status": "usable", "reason": None},
            "spot_cvd.original_five.720h": {"status": "incomplete", "reason": "missing interval"},
            "live_depth.binance_spot.0.2": {"status": "usable"},
            "live_depth.okx_spot.0.2": {"status": "incomplete"},
        }},
        "spot_cvd": {"windows": {
            "24h": {"net_usd_approx": 200_000_000, "complete": True},
            "720h": {"net_usd_approx": None, "complete": False, "complete_venue_subset": {"net_usd_approx": 999_000_000}},
        }},
        "orderbook_live": {"venues": {
            "binance_spot": {"bands": {"0.2": {"bid_usd": 100, "ask_usd": 50, "complete": True}}},
            "okx_spot": {"bands": {"0.2": {"bid_usd": 200, "ask_usd": 100, "complete": False}}},
        }},
    }


class TestLogic(unittest.TestCase):
    def test_number_zero_and_null_are_different(self):
        self.assertEqual(formatted(0, "usd"), "$0.00")
        self.assertEqual(formatted(None, "usd"), "—")
        self.assertEqual(formatted(False, "usd"), "—")

    def test_cvd_complete_window(self):
        r = cvd_value(sample(), "24h")
        self.assertEqual(r["value"], 200_000_000)
        self.assertEqual(r["status"], "usable")

    def test_cvd_incomplete_not_substituted(self):
        r = cvd_value(sample(), "720h")
        self.assertIsNone(r["value"])
        self.assertEqual(r["status"], "incomplete")

    def test_quality_blocks_number(self):
        d=sample()
        d["btc_technicals"]["latest_spot_price_usdt"] = 42
        d["metric_quality"]["checks"]["price.live_spot_quote"]["status"] = "stale"
        r=metric_value(d,"btc_technicals.latest_spot_price_usdt","price.live_spot_quote")
        self.assertIsNone(r["value"])
        self.assertEqual(r["status"], "stale")

    def test_depth_only_complete_and_verified(self):
        rows=orderbook_rows(sample(),"0.2","Спот")
        self.assertEqual(len(rows),2)
        self.assertEqual(next(r for r in rows if r["Биржа"] == "binance_spot")["Спрос, USD"],100)
        self.assertIsNone(next(r for r in rows if r["Биржа"] == "okx_spot")["Спрос, USD"])

    def test_timestamps_require_utc_info(self):
        self.assertAlmostEqual(hours_since("2026-11-23T15:00:00+00:00", datetime(2026,11,23,16,tzinfo=timezone.utc)),1)
        with self.assertRaises(ValueError):
            validate_brief({"as_of_utc":"2026-11-23T15:00:00", "btc_technicals":{},"metric_quality":{}})

    def test_missing_does_not_imply_zero(self):
        self.assertIsNone(at(sample(),"derivatives.oi_five_venue_usd"))
        self.assertEqual(metric_value(sample(),"derivatives.oi_five_venue_usd")["status"],"missing")

    def test_signs_are_explicit(self):
        self.assertEqual(formatted(1.5, "pct"), "+1.50%")
        self.assertEqual(formatted(-1.5, "pct"), "-1.50%")
        self.assertEqual(formatted(-669_162_059, "usd_m"), "−$669.2 млн")

    def test_distance_needs_both_values(self):
        ok = pct_distance({"value": 90, "status": "usable"}, {"value": 100, "status": "usable"})
        self.assertAlmostEqual(ok["value"], -10)
        bad = pct_distance({"value": 90, "status": "usable"}, {"value": None, "status": "stale", "reason": "x"})
        self.assertIsNone(bad["value"])
        self.assertEqual(bad["status"], "stale")

    def test_average_refuses_partial_set(self):
        self.assertAlmostEqual(average_usable([{"value": 1}, {"value": 3}])["value"], 2)
        self.assertIsNone(average_usable([{"value": 1}, {"value": None}])["value"])

    def test_labels_translate_and_fall_back(self):
        self.assertEqual(label("breakout20", "within_prev20_range"), "внутри диапазона 20 дней")
        self.assertEqual(label("trend", "brand_new_code"), "brand new code")
        self.assertEqual(label("trend", None), "—")

    def test_human_time_local_zone(self):
        tz = local_tz("Asia/Tomsk")
        now = datetime(2026, 11, 23, 17, 0, tzinfo=timezone.utc)
        self.assertEqual(human_time("2026-11-23T15:00:00Z", tz, now), "23 ноя 22:00 · 2 ч назад")
        self.assertEqual(human_time("2026-11-21", tz, now), "данные за 21 ноя")
        self.assertEqual(human_time(None, tz, now), "")


if __name__ == "__main__":
    unittest.main()
