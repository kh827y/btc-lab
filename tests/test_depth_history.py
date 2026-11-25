import unittest
from datetime import date
import pandas as pd
from depth_history import depth_frame
from binance_daily import parse_klines,download_daily,DAY,START

NOW=pd.Timestamp("2026-11-25T10:00Z")
class DepthTest(unittest.TestCase):
    def test_bybit_band_and_clock(self):
        market="bybit_independent_linear"
        row={"source_type":"independent Bybit daily native snapshot","venue":market,"market":"perpetual","symbol":"BTCUSDT","ob_levels_declared":200,"time":"2026-11-23T00:00:02Z","bands":{"0.01":{"bid_coverage_complete":True,"ask_coverage_complete":True,"bid_usd":60,"ask_usd":40,"bid_share":.6}}}
        doc={"schema_version":1,"records":{market:{"2026-11-23":row,"2026-11-24":{**row,"time":"2026-11-24T01:00:00Z"}}}}
        s=depth_frame(doc,market,"0.01",NOW)
        self.assertEqual(s.iloc[0]["share"],60)
        self.assertTrue(pd.isna(s.iloc[1]["bid"]))
        row["bands"]["0.01"]["ask_coverage_complete"]=False
        self.assertTrue(pd.isna(depth_frame(doc,market,"0.01",NOW).iloc[0]["bid"]))
    def test_hft_reject_midnight_and_wrong_market(self):
        market="binance_spot"
        row={"source":"CryptoHFTData historical verified L2 snapshot","method":"first genuine complete vendor snapshot in UTC file (may follow unanchored updates); not a daily median","venue":market,"symbol":"BTCUSDT","market":"spot","quote":"USDT","file_path":"binance_spot/2026-11-23/00/test","sample_utc_hour":0,"time":"2026-11-23T00:00:01Z","bands":{"0.01":{"bid_coverage_complete":True,"ask_coverage_complete":True,"bid_usd":20,"ask_usd":80,"bid_share":.2}}}
        doc={"schema_version":2,"markets":{market:{"2026-11-23":{"status":"ok","data":row}}}}
        self.assertTrue(pd.isna(depth_frame(doc,market,"0.01",NOW).iloc[0]["bid"]))
        row.update(time="2026-11-23T12:05:00Z",sample_utc_hour=12,file_path="binance_spot/2026-11-23/12/test")
        self.assertEqual(depth_frame(doc,market,"0.01",NOW).iloc[0]["share"],20)
        row["symbol"]="ETHUSDT"
        self.assertTrue(pd.isna(depth_frame(doc,market,"0.01",NOW).iloc[0]["bid"]))
    def test_microsecond_candle(self):
        row=[START*1000,"1","2","1","1.5","10",(START+DAY)*1000-1,"100",8,"6","60","0"]
        out,last=parse_klines([row],START,START+DAY)
        self.assertEqual(last,START)
        self.assertEqual(list(out["net_quote_usdt"].values()),[20])
    def test_bad_day_is_gap_not_whole_download(self):
        def fetch(url,params):
            rows=[]
            for t in range(params["startTime"],params["endTime"]+1,DAY):
                rows.append([t,"1","2","1","1.5","10",t+DAY-1 if t!=START else t+1000,"100",8,"6","60","0"])
            return rows
        out=download_daily(fetch,now=date(2018,9,1))
        self.assertIsNone(out["series"]["close_usdt"]["2017-08-17"])
        self.assertEqual(len(out["rejected_days"]),1)
        self.assertEqual(out["series"]["net_quote_usdt"]["2017-08-18"],20)
