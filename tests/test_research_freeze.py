import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import patch,Mock

from binance_minute import FIRST,MINUTE,ms,filename,source,digest
from research_prices import snapshot,snapshot_hash,MinutePrices
from research_cpi import development_groups,read_cpi,MEMBERS,METRICS


class FrozenDataTest(unittest.TestCase):
    def fixture(self,root):
        start=FIRST
        stop=start+timedelta(days=1)
        label=start.isoformat()
        t=ms(start)
        row=",".join(map(str,[t,100,101,99,100,1,t+MINUTE-1,100,1,0.5,50,0]))
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,"w") as z:
            z.writestr(filename(label).replace(".zip",".csv"),row+"\n")
        raw=buf.getvalue()
        p=root/"daily"/filename(label)
        p.parent.mkdir()
        p.write_bytes(raw)
        a={"schema":2,"complete_scan":True,"errors":0,
           "start":start.isoformat(),"stop":stop.isoformat(),"rows":1,
           "expected":1440,"missing_or_unavailable":1439,
           "archives":[{"url":source("daily",label),"start":start.isoformat(),
             "stop":stop.isoformat(),"sha256":digest(raw),"rows":1,"missing":1439,
             "cached":False,"downloaded_utc":"old"}]}
        return a,p

    def test_snapshot_stability_and_loader(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,p=self.fixture(root)
            h=snapshot_hash(a)
            a["archives"][0]["cached"]=True
            a["archives"][0]["downloaded_utc"]="new"
            self.assertEqual(snapshot_hash(a),h)
            self.assertEqual(snapshot_hash(snapshot(a)),h)
            # A newer or broken live audit cannot alter an already frozen study.
            (root/"audit.json").write_text("{}")
            prices=MinutePrices.load(root,frozen=snapshot(a))
            self.assertEqual(prices.provenance["snapshot_sha256"],h)
            self.assertEqual(prices.point(ms(FIRST),"open"),100.)
            self.assertIsNone(prices.point(ms(FIRST)+MINUTE,"open"))
            p.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError,"hash mismatch"):
                MinutePrices.load(root,frozen=a)
            a["archives"][0]["sha256"]=digest(b"changed")
            self.assertNotEqual(snapshot_hash(a),h)

    def test_incomplete_audit_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            a,p=self.fixture(Path(tmp))
            a["complete_scan"]=False
            with self.assertRaises(ValueError):
                snapshot(a)

    def test_final_events_never_prepared(self):
        e={"event_id":"reserved","release_time_utc":"2024-01-11T13:30:00Z"}
        with patch("research_cpi.prepare_event") as f:
            groups,coverage=development_groups([e],{},Mock())
            f.assert_not_called()
            self.assertEqual(dict(groups),{})

    def test_synthetic_cpi_reader_and_postrelease_rejection(self):
        def table(rows):
            b=io.StringIO(newline="")
            w=csv.DictWriter(b,fieldnames=list(rows[0]))
            w.writeheader();w.writerows(rows)
            return b.getvalue().encode()
        e={"event_id":"e","release_time_utc":"2023-01-12T13:30:00Z",
           "release_time_et":"2023-01-12T08:30:00-05:00","release_date_et":"2023-01-12",
           "forecast_cutoff_utc":"2023-01-12T13:30:00Z","early_partial_time_utc":"",
           "monthly_pair_available":"1","standard_intraday_timing_and_pair":"1"}
        f={"event_id":"e","forecast_id":"f","published_earliest_utc":"2023-01-11T12:00:00Z",
           "published_latest_utc":"2023-01-11T12:00:00Z"}
        for m in METRICS:
            e.update({m+"_first_pct":"0.3",m+"_expected_pct":"0.2",
                      m+"_surprise_pp":"0.1",m+"_forecast_id":"f"})
            f[m+"_pct"]="0.2"
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"input.zip"
            def create():
                files={n:b"" for n in MEMBERS}
                files.update({"cpi_releases.csv":table([e]),"cpi_expectations.csv":table([f]),
                              "bls_first_prints.csv":table([{"event_id":"e"}])})
                manifest="".join(digest(v)+"  "+k+"\n" for k,v in sorted(files.items())).encode()
                with zipfile.ZipFile(path,"w") as z:
                    for k,v in files.items():z.writestr(k,v)
                    z.writestr("SHA256SUMS",manifest)
                return digest(manifest)
            h=create()
            events,alts,_=read_cpi(path,manifest_hash=h,counts=(1,1,1,1))
            self.assertEqual(len(events),1)
            self.assertEqual(len(alts["e"]),1)
            f["published_latest_utc"]="2023-01-12T13:30:00Z"
            h=create()
            with self.assertRaisesRegex(ValueError,"Post-release"):
                read_cpi(path,manifest_hash=h,counts=(1,1,1,1))

    def test_migration_preserves_dev_removes_only_generated_test(self):
        import research_cpi as mod
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            a,_=self.fixture(root)
            frozen=snapshot(a)
            out=root/"prepared";out.mkdir()
            groups={s:{k:[{"id":s,"kind":k}] for k in
                      ("features","outcomes","controls","delayed_features")}
                    for s in ("train","development")}
            payloads={f"{s}_{k}.csv":mod.csv_bytes(v)
                      for s,g in groups.items() for k,v in g.items()}
            hashes={n:digest(v) for n,v in payloads.items()}
            for n,v in payloads.items():(out/n).write_bytes(v)
            for n in mod.LEGACY_TEST_FILES:(out/n).write_bytes(b"DO NOT READ")
            (out/"development_report.json").write_bytes(b"previous report")
            legacy={"complete":True,"protocol":"cpi-v1-preparation","cpi_sha256":"fixture",
                    "file_sha256":hashes}
            (out/"coverage.json").write_text(json.dumps(legacy))
            prices=Mock()
            prices.provenance={"snapshot_sha256":snapshot_hash(frozen)}
            events=[{"release_time_utc":"2024-01-11T13:30:00Z"}]
            with patch.multiple(mod,CPI_HASH="fixture",PRICE_HASH=snapshot_hash(frozen),
                                EXPECTED_DEV_HASHES=hashes), \
                 patch.object(mod,"read_cpi",return_value=(events,{},"fixture")), \
                 patch.object(mod.MinutePrices,"load",return_value=prices), \
                 patch.object(mod,"development_groups",return_value=(groups,{})) as compute:
                (root/"audit.json").write_text(json.dumps(a))
                # Mismatched data do not destroy any prior files.
                target=out/"train_features.csv"
                target.write_bytes(b"changed")
                with self.assertRaisesRegex(ValueError,"Legacy development file changed"):
                    mod.build("unused",root,out)
                self.assertTrue(all((out/n).exists() for n in mod.LEGACY_TEST_FILES))
                target.write_bytes(payloads[target.name])
                report=mod.build("unused",root,out)
                self.assertFalse(report["test_generated"])
                self.assertEqual(report["test_events_reserved"],1)
                self.assertFalse(any((out/n).exists() for n in mod.LEGACY_TEST_FILES))
                self.assertEqual((out/"development_report.json").read_bytes(),b"previous report")
                self.assertEqual({n:(out/n).read_bytes() for n in hashes},payloads)
                (root/"audit.json").write_text("{}")
                self.assertEqual(mod.build("unused",root,out),report)
                compute.assert_called_once()
                target.write_bytes(b"changed again")
                with self.assertRaisesRegex(ValueError,"Prepared file changed"):
                    mod.build("unused",root,out)
