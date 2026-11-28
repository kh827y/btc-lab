import unittest
from datetime import datetime, timedelta, timezone
from spot_breadth import BASKETS, SYMBOLS, calculate

END=datetime(2026,11,28,11,tzinfo=timezone.utc)
NOW=END+timedelta(hours=2)

def fixture():
    state={"hourly":{}}
    for venue,(symbol,quote) in SYMBOLS.items():
        rows={}
        for i in range(168,0,-1):
            key=(END-timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z")
            net=1 if i>24 else -2
            rows[key]={"complete":True,"hour":key,"buy":100+net,"sell":100,
                       "net":net,"source":"CryptoHFTData","symbol":symbol,"quote":quote}
            if venue=="coinbase":
                rows[key].update(source="Coinbase Exchange public REST BTC-USD validated ID-continuous scan",
                    integrity="id_continuous_verified",time_basis="exchange_trade_time")
        state["hourly"][venue]=rows
    demand={"spot":{k:{"status":"usable","observed_end_utc":END.isoformat(),
            "venues":list(v),"last_24h_usd_approx":-240,"prior_144h_usd_approx":720}
            for k,v in BASKETS.items()}}
    return state,demand

class SpotBreadthTest(unittest.TestCase):
    def test_nonoverlapping_days_and_venues(self):
        state,demand=fixture()
        r=calculate(state,demand,NOW)["baskets"]["original_five"]
        self.assertEqual(r["status"],"usable")
        self.assertEqual(r["daily_net_usd_approx"],[120]*6+[-240])
        self.assertEqual(r["days"],{"positive":6,"negative":1,"zero":0})
        self.assertEqual(r["last_24h_venue_signs"]["negative"],5)
        self.assertEqual(r["full_168h_venue_signs"]["positive"],5)

    def test_missing_proof_does_not_contaminate_other_basket(self):
        state,demand=fixture()
        del next(iter(state["hourly"]["coinbase"].values()))["integrity"]
        r=calculate(state,demand,NOW)["baskets"]
        self.assertEqual(r["original_five"]["invalid_hours"]["coinbase"],1)
        self.assertNotIn("days",r["original_five"])
        self.assertEqual(r["ex_coinbase"]["status"],"usable")

    def test_missing_hour_mismatched_totals_and_stale(self):
        state,demand=fixture()
        del state["hourly"]["binance"][next(iter(state["hourly"]["binance"]))]
        r=calculate(state,demand,NOW)["baskets"]
        self.assertTrue(all(x["status"]=="unavailable" for x in r.values()))
        state,demand=fixture()
        demand["spot"]["original_five"]["prior_144h_usd_approx"]=721
        self.assertEqual(calculate(state,demand,NOW)["baskets"]["original_five"]["reason"],
                         "hourly_totals_disagree_with_brief")
        self.assertTrue(all(x["status"]=="unavailable" for x in
            calculate(state,demand,END+timedelta(hours=5))["baskets"].values()))
