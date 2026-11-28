import unittest
from live_derivatives import parse_oi,parse_bars,summarize,HOUR

class LiveDerivativesTest(unittest.TestCase):
    def test_exact_quantity_and_gaps(self):
        end=700*HOUR
        a=end-24*HOUR
        oi={a:(100,6000000),end:(90,5400000)}
        mark={t-HOUR:(60000,60100,59900,60000) for t in oi}
        p=summarize(oi,mark,{},end)
        self.assertAlmostEqual(p["windows"]["1"]["oi_change_pct"],-10)
        self.assertEqual(p["windows"]["1"]["oi_checked_points"],2)
        self.assertIsNone(p["windows"]["1"]["premium_mean_close_fraction"])
        self.assertIsNone(p["windows"]["7"]["oi_change_pct"])
        oi[end]=(90,54)
        self.assertIsNone(summarize(oi,mark,{},end)["oi_latest_checked_btc"])

    def test_parser(self):
        r={"symbol":"BTCUSDT","timestamp":HOUR,"sumOpenInterest":"100","sumOpenInterestValue":"6000000"}
        self.assertEqual(parse_oi([r],0,HOUR)[HOUR],(100,6000000))
        with self.assertRaises(ValueError):
            parse_oi([r,r],0,HOUR)
        with self.assertRaises(ValueError):
            parse_oi([{**r,"symbol":"ETHUSDT"}],0,HOUR)
        row=[0,"-0.001","0.001","-0.002","0",0,HOUR-1,0,0,0,0,0]
        self.assertEqual(parse_bars([row],0,HOUR)[0][3],0)
        with self.assertRaises(ValueError):
            parse_bars([row],0,HOUR,True)
