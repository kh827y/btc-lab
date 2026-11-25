import unittest
import pandas as pd
from history_logic import series_for, period_slice, OI_VENUES, CVD_VENUES

NOW=pd.Timestamp("2026-11-25T10:00:00Z")
class HistoryTest(unittest.TestCase):
    def test_price_gap_and_unclosed(self):
        doc={"instrument":{"venue":"Binance","symbol":"BTCUSDT","market":"spot"},"daily_closed":[{"day":"2026-11-21","close":10},{"day":"2026-11-23","close":12},{"day":"2026-11-25","close":99}]}
        s=series_for("Цена BTC · закрытие дня",doc,NOW)
        self.assertEqual(len(s),3)
        self.assertTrue(pd.isna(s.iloc[1]))
        self.assertEqual(s.iloc[-1],12)
    def test_oi_scope_and_partial_day(self):
        venues={k:10 for k in OI_VENUES}
        good={"hour":"2026-11-23T23:00:00Z","venues":venues,"five_venue_usd":50}
        bad={**good,"hour":"2026-11-24T22:00:00Z"}
        doc={"results":{"open_interest":{"venues":list(OI_VENUES),"daily_history":{"2026-11-23":good,"2026-11-24":bad,"2026-11-25":good}}}}
        s=series_for("Открытый интерес · 5 бирж",doc,NOW)
        self.assertEqual(s.iloc[0],50)
        self.assertTrue(pd.isna(s.iloc[1]))
        self.assertEqual(len(s),2)
    def test_cvd_requires_proof_and_fixed_basket(self):
        hour="2026-11-23T01:00:00Z"
        row={"buy":10,"sell":7,"net":3,"complete":True,"hour":hour,"quote":"USD","integrity":"id_continuous_verified"}
        doc={"hourly":{v:{hour:dict(row)} for v in CVD_VENUES}}
        doc["hourly"]["bitget"]={hour:{**row,"net":999}}
        self.assertEqual(series_for("CVD · нетто за час · 5 бирж",doc,NOW).iloc[0],15)
        del doc["hourly"]["coinbase"][hour]["integrity"]
        self.assertTrue(pd.isna(series_for("CVD · нетто за час · 5 бирж",doc,NOW).iloc[0]))
    def test_zero_not_missing_and_stale_window(self):
        doc={"mvrv":{"2026-10-01":0,"2026-10-03":1}}
        s=series_for("MVRV · исходный ончейн",doc,NOW)
        self.assertEqual(s.iloc[0],0)
        self.assertTrue(pd.isna(s.iloc[1]))
        self.assertTrue(period_slice(s,7,NOW).empty)
    def test_options_missing_hour(self):
        doc={"2026-11-23T01:00:00Z":{"1M":{"atm_iv_pct":40}},"2026-11-23T03:00:00Z":{"1M":{"atm_iv_pct":42}}}
        s=series_for("Опционы · ATM IV 1M",doc,NOW)
        self.assertEqual(len(s),3)
        self.assertTrue(pd.isna(s.iloc[1]))
    def test_etf_no_fake_weekend(self):
        doc={"etf":{"last_five_sessions":[{"date":"2026-11-20","net_flow_usd":0},{"date":"2026-11-23","net_flow_usd":-2}]}}
        s=series_for("ETF США · последние 5 сессий",doc,NOW)
        self.assertEqual(len(s),2)
        self.assertEqual(s.iloc[0],0)
