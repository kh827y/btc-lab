import unittest
from datetime import date
import pandas as pd
from extended_history import parse_etf,parse_kote,parse_coin,select_binance
from history_logic import series_for

class ExtendedTest(unittest.TestCase):
    def test_etf_zero_and_scope(self):
        dates=pd.bdate_range("2026-10-01",periods=25)
        raw={"name":"US Spot Bitcoin ETF Daily Flows","units":"USD","license":"https://creativecommons.org/licenses/by/4.0/","days":[{"date":str(d.date()),"netFlowUsd":i-1} for i,d in enumerate(dates)]}
        doc=parse_etf(raw,date(2026,11,25))
        self.assertEqual(doc["series"]["net_flow_usd"]["2026-10-02"],0)
        s=series_for("ETF США · полная история TFTC",doc,pd.Timestamp("2026-11-25T00:00Z"))
        self.assertEqual(len(s),25)
        raw["days"].append(raw["days"][0])
        with self.assertRaises(ValueError):parse_etf(raw,date(2026,11,25))
    def test_kote_uses_named_field_and_excludes_current(self):
        rows=[{"t":f"2026-11-{i:02d}","mvrv":i/10,"usd":60000} for i in range(1,12)]
        doc=parse_kote({"success":True,"data":{"points":rows}},"mvrv",date(2026,11,11))
        self.assertEqual(len(doc["series"]["mvrv"]),10)
        self.assertEqual(doc["series"]["mvrv"]["2026-11-01"],.1)
        with self.assertRaises(ValueError):parse_kote({"success":True,"data":{"points":[{"t":x["t"],"usd":60000} for x in rows]}},"mvrv",date(2026,11,11))
    def test_coin_scope_and_close(self):
        market={"exchange":"X","symbol_on_exchange":"BTCUSDT","base_asset":"BTC","quote_asset":"USDT","is_perpetual":True,"margined":"STABLE","symbol":"M"}
        self.assertEqual(select_binance([{"code":"X","name":"Binance"}],[market]),"M")
        with self.assertRaises(ValueError):select_binance([{"code":"X","name":"Binance"}],[market,market])
        rows=[{"t":int(d.timestamp()),"c":i} for i,d in enumerate(pd.date_range("2026-11-01",periods=10,tz="UTC"))]
        self.assertEqual(len(parse_coin([{"symbol":"M","history":rows}],"M","open-interest-history",date(2026,11,10))["c"]),9)
        with self.assertRaises(ValueError):parse_coin([{"symbol":"OTHER","history":rows}],"M","open-interest-history",date(2026,11,10))
