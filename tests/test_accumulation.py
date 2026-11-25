import tempfile
import unittest
from pathlib import Path
import pandas as pd
from history_store import save_archive,saved_series,coverage
from history_logic import OPTIONS
from extended_history import merge_local
from binance_daily import parse_klines,DAY,START

class AccumulationTest(unittest.TestCase):
    def test_preserve_old_and_invalidate_overlap(self):
        label="Опционы · ATM IV 1M"
        now=pd.Timestamp("2026-11-25T10:00Z")
        a="2026-11-23T01:00:00Z";b="2026-11-23T02:00:00Z";c="2026-11-23T03:00:00Z"
        with tempfile.TemporaryDirectory() as d:
            db=Path(d)/"test.sqlite3"
            save_archive(OPTIONS,{a:{"1M":{"atm_iv_pct":40,"rr25_volpts":-1}},b:{"1M":{"atm_iv_pct":41,"rr25_volpts":-2}}},db,now)
            save_archive(OPTIONS,{b:{"1M":{"rr25_volpts":-2}},c:{"1M":{"atm_iv_pct":42,"rr25_volpts":-3}}},db,now+pd.Timedelta(minutes=1))
            s=saved_series(label,db)
            self.assertEqual(s.iloc[0],40)
            self.assertTrue(pd.isna(s.iloc[1]))
            self.assertEqual(s.iloc[-1],42)
            self.assertEqual(coverage(s,"h",now)["gaps"],1)
    def test_provider_merge(self):
        a={"schema":1,"source":"A","series":{"x":{"old":1,"overlap":2}}}
        b={"schema":1,"source":"A","series":{"x":{"overlap":None,"new":3}}}
        self.assertEqual(merge_local(a,b)["series"]["x"],{"old":1,"overlap":None,"new":3})
        with self.assertRaises(ValueError):merge_local(a,{**b,"source":"B"})
    def test_binance_net_and_close(self):
        row=[START,"1","2","1","1.5","10",START+DAY-1,"100",8,"6","60","0"]
        out,last=parse_klines([row],START,START+DAY)
        self.assertEqual(list(out["net_quote_usdt"].values()),[20])
        self.assertEqual(list(out["close_usdt"].values()),[1.5])
        row[10]="101"
        with self.assertRaises(ValueError):parse_klines([row],START,START+DAY)
