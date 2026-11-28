import unittest
from datetime import datetime, timezone, timedelta

from market_state import packet, age, perpetual_context

NOW = datetime(2026, 11, 28, 11, tzinfo=timezone.utc)


def fixture():
    def q(obs, status="usable"):
        return {"status":status,"observed_at":obs,"scope":"fixture","comparison_key":"fixture"}
    return {
        "as_of_utc":"2026-11-28T10:30:00Z",
        "btc_technicals":{"latest_spot_price_usdt":60000,"latest_closed_day_price_usdt":61000,
                          "daily_change_pct":{"7d":2},"swings":{"classification":"LH_LL"}},
        "sources":{k:{"status":"fresh","original":"test"} for k in
                   ("price_technical","spot_cvd","derivatives","macro_etf","onchain","options")},
        "metric_quality":{"checks":{
            "price.live_spot_quote":q("2026-11-28T10:00:00Z"),
            "price.closed_daily_weekly":q("2026-11-27"),
            "spot_cvd.original_five.24h":q("2026-11-28T09:00:00Z"),
            "spot_cvd.original_five.720h":q("2026-11-28T09:00:00Z","incomplete"),
            "spot_cvd.fixed_ex_coinbase.720h":q("2026-11-28T09:00:00Z"),
            "derivatives.oi_five":q("2026-11-28T10:00:00Z"),
            "macro.treasury_yields":q("2026-11-27")
        }},
        "spot_cvd":{"windows":{"24h":{"net_usd_approx":0},
            "720h":{"net_usd_approx":100,"fixed_five_ex_coinbase":{"net_usd_approx":-25}}}},
        "derivatives":{"oi_five_venue_usd":12345,"oi_1d_7d_30d_pct":{"7d":-3}},
        "macro":{"fred":{"treasury_2y_pct":{"value":4,"date":"2026-11-25","status":"usable"}}}
    }


def item(p, family, name):
    return next(x for x in p["families"][family] if x["id"]==name)


class MarketStateTest(unittest.TestCase):
    def test_baskets_never_substituted_and_zero_is_real(self):
        p=packet(fixture(),NOW)
        self.assertEqual(item(p,"spot","original_five_24h")["value"],0)
        self.assertIsNone(item(p,"spot","original_five_720h")["value"])
        self.assertEqual(item(p,"spot","ex_coinbase_720h")["value"],-25)
        self.assertEqual(p["technical_context"]["classification"],"LH_LL")

    def test_old_snapshot_and_future_observation(self):
        p=packet(fixture(),NOW+timedelta(hours=4))
        self.assertIsNone(item(p,"price","spot_quote")["value"])
        self.assertIsNone(p["technical_context"]["classification"])
        d=fixture()
        d["metric_quality"]["checks"]["price.live_spot_quote"]["observed_at"]="2026-11-28T10:45:00Z"
        self.assertEqual(item(packet(d,NOW),"price","spot_quote")["status"],"future_observation")
        with self.assertRaises(ValueError):
            packet(d,NOW-timedelta(hours=1))

    def test_missing_quality_and_stale_source(self):
        d=fixture()
        d["sources"]["derivatives"]["status"]="stale"
        p=packet(d,NOW)
        self.assertIsNone(item(p,"derivatives","oi_notional")["value"])
        self.assertIsNone(item(p,"price","ma20")["value"])
        self.assertEqual(item(p,"price","daily_close")["time_precision"],"date_only")

    def test_series_date_and_units(self):
        p=packet(fixture(),NOW)
        self.assertEqual(item(p,"macro","treasury_2y_pct")["observed_at"],"2026-11-25")
        self.assertEqual(item(p,"derivatives","oi_notional_change_7d")["unit"],"percent USD notional")
        self.assertEqual(age("2026-11-29",NOW,NOW),(None,"future_observation"))


class PerpetualContextTest(unittest.TestCase):
    def test_independent_source_and_partial_windows(self):
        d={"version":"live-derivatives-readiness-v1",
           "market":"Binance USD-M BTCUSDT perpetual",
           "observed_end_utc":"2026-11-28T10:00:00Z",
           "retrieved_utc":"2026-11-28T10:50:00Z",
           "oi_latest_checked_btc":90,"premium_last_closed_fraction":-0.001,
           "windows":{"1":{"oi_start_btc":100,"oi_end_btc":90,
                    "oi_checked_points":2,"oi_expected_points":25,
                    "premium_expected_hours":24,"premium_valid_hours":23,
                    "premium_mean_close_fraction":-0.001}}}
        p={x["id"]:x for x in perpetual_context(d,NOW)}
        self.assertEqual(p["oi_quantity"]["value"],90)
        self.assertAlmostEqual(p["oi_quantity_change_1d"]["value"],-10)
        self.assertEqual(p["oi_quantity_change_1d"]["coverage"]["valid"],2)
        self.assertIsNone(p["premium_mean_1d"]["value"])
        self.assertIsNone(p["oi_quantity_change_7d"]["value"])
        self.assertTrue(all(x["value"] is None for x in perpetual_context(d,NOW+timedelta(hours=4))))
        self.assertTrue(all(x["value"] is None for x in perpetual_context({},NOW)))
