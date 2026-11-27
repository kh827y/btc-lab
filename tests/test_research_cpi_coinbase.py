import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from research_cpi_coinbase import CUTOFF, request_url, parse, CandleCache, independent_event, differences
from research_prices import DAY
from binance_minute import MINUTE


def raw(rows):
    return json.dumps(rows).encode()


class CoinbaseTest(unittest.TestCase):
    def test_half_open_and_order(self):
        t=120000
        data=parse(raw([[180,99,101,100,100,1],[120,99,101,100,100,1],[60,99,101,100,100,1]]),
                   t,t+MINUTE,MINUTE)
        self.assertEqual(data,{t:(100.,100.)})

    def test_invalid(self):
        row=[120,99,101,100,100,1]
        with self.assertRaises(ValueError):
            parse(raw([row,row]),120000,180000,MINUTE)
        with self.assertRaises(ValueError):
            parse(raw([[120,102,101,100,100,1]]),120000,180000,MINUTE)
        with self.assertRaises(ValueError):
            request_url(CUTOFF,CUTOFF+MINUTE,MINUTE)

    def test_cache_and_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            fetcher=Mock(return_value=raw([[120,99,101,100,100,1]]))
            c=CandleCache(tmp,fetcher)
            a=c.get(120000,180000,MINUTE)
            self.assertEqual(a,c.get(120000,180000,MINUTE))
            fetcher.assert_called_once()
            p=next(Path(tmp).glob("*.json"))
            obj=json.loads(p.read_bytes());obj["raw"]="[]"
            p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"integrity"):
                c.get(120000,180000,MINUTE)

    def test_independent_reaction_and_exit(self):
        t=CUTOFF-40*DAY+13*60*MINUTE
        e={"id":"x","entry":t+31*MINUTE,"exit":t+31*MINUTE+7*DAY,
           "x":[0,0,0,.1],"y":.1}
        def get(start,stop,step):
            result={k:(100.,100.) for k in range(start,stop,step)}
            if start==t-MINUTE:
                result[t+29*MINUTE]=(100.,105.)
                result[t+30*MINUTE]=(100.,900.)
            if start==e["exit"]:
                result[start]=(110.,100.)
            return result
        cache=Mock();cache.get.side_effect=get
        r,missing=independent_event(e,cache)
        self.assertFalse(missing)
        self.assertAlmostEqual(r["x"][2],.05)
        self.assertAlmostEqual(r["y"],.1)
        self.assertEqual(r["x"][3],.1)
        self.assertEqual(e["x"][2],0)
        self.assertAlmostEqual(differences([e],[r])["reaction_30m"]["max_abs_difference_pp"],5.)

    def test_missing_not_filled(self):
        t=CUTOFF-40*DAY
        e={"entry":t+31*MINUTE,"exit":t+31*MINUTE+7*DAY,"x":[0,0,0,0]}
        c=Mock();c.get.return_value={}
        r,missing=independent_event(e,c)
        self.assertIsNone(r)
        self.assertEqual(len(missing),4)
