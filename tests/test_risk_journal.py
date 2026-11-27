import unittest
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from research_buy import DAY
from risk_journal import current,score_horizon,receipt_map,verify_record,VERSION
from forecast_journal import new_file

class RiskJournalTest(unittest.TestCase):
    def test_forecasts_and_maturity(self):
        t=date(2020,1,6);first=t-150*7*DAY
        p={first+i*DAY:(100.,110.,90.,105.,1.) for i in range(-100,(t-first).days-1)}
        f=current(p,t,first)
        for h in (7,28,90):
            r=f["horizons"][str(h)]
            self.assertLessEqual(date.fromisoformat(r["latest_train_origin"])+(h+1)*DAY,t-DAY)
            self.assertGreaterEqual(r["n_matured"],52)
            out=score_horizon(f,{"log_return":0.,"log_worst":-.1,"variance":0.},h)
            self.assertIn("crps_worst",out["scores"]["scaled_expanding"])
        p[t-DAY]=(100.,110.,90.,105.,1.)
        with self.assertRaises(ValueError):
            current(p,t,first)

    def test_receipt_and_no_rewrite(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);d=date(2026,11,30)
            s=new_file(root/"source.json",{"source":"test"})
            f={"version":VERSION,"origin":d.isoformat(),"source_sha256":s,
               "horizons":{str(h):{} for h in (7,28,90)}}
            target=root/"risk_forecast.json";sha=new_file(target,f)
            r={"origin":d.isoformat(),"sha256":sha,"created_utc":"2026-11-29T12:00:00Z",
               "comment_url":"https://github.com/kh827y/btc-lab/issues/2#issuecomment-123"}
            ledger=root/"ledger.json";ledger.write_text(json.dumps({"version":VERSION,"receipts":[r]}))
            self.assertEqual(receipt_map(ledger)[d],r)
            self.assertEqual(verify_record(target,d,r),f)
            with self.assertRaises(FileExistsError):
                new_file(target,f)
            (root/"source.json").write_text("changed")
            with self.assertRaises(ValueError):
                verify_record(target,d,r)
            ledger.write_text(json.dumps({"version":VERSION,"receipts":[r,r]}))
            with self.assertRaises(ValueError):
                receipt_map(ledger)
