import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from research_cpi_development import replay, summary, load_split, predict
from research_prices import DAY


def row(i,y=0.05):
    return {"id":str(i),"entry":i*30*DAY,"known":i*30*DAY-60000,
            "exit":i*30*DAY+7*DAY,"x":[0.1,0.03,0.02,0.1],"y":y}


class DevelopmentTest(unittest.TestCase):
    def test_not_read_test(self):
        with patch("research_cpi_development.read_table") as read:
            with self.assertRaises(ValueError):
                load_split(Path("."),"test",{})
            read.assert_not_called()

    def test_future_outcome_excluded(self):
        train=[row(i) for i in range(40)]
        target=row(40)
        train[-1]["exit"]=target["known"]+1
        a=replay(train,[target])[0]
        train[-1]["y"]=999.
        target["y"]=-0.7
        b=replay(train,[target])[0]
        self.assertEqual(a["training_count"],39)
        self.assertEqual(a["predictions"],b["predictions"])

    def test_expanding_past_and_constant_features(self):
        train=[row(i) for i in range(40)]
        r=replay(train,[row(40),row(41)])
        self.assertEqual([x["training_count"] for x in r],[40,41])
        self.assertAlmostEqual(r[0]["predictions"]["market_plus_cpi"],0.05)
        self.assertAlmostEqual(summary(r)["scores"]["market_plus_cpi"]["rmse_pp"],0.0)

    def test_purchase_gain_not_return_sum(self):
        r=[{"y":-0.2,"predictions":dict.fromkeys(("zero","historical_mean","market_before","market_after","market_plus_cpi"),-0.1)}]
        self.assertAlmostEqual(summary(r)["scores"]["market_after"]["mean_btc_quantity_gain_vs_buy_now_pct"],25.0)

if __name__=="__main__":
    unittest.main()
