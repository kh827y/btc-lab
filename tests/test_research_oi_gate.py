import unittest
import numpy as np
from research_oi_gate import (world,oracle,probs,PATHS,TOTAL,MINIMUM,BARRIER,price_features,
                              mature_bounds,replay,preflight,evaluate,FIRST)

class OIGateTest(unittest.TestCase):
    def test_probability_and_paths(self):
        np.testing.assert_allclose(PATHS.sum(axis=1),TOTAL)
        for r in (0,1):
            for x in (-1,1):
                p=probs(r,x,.22)
                self.assertTrue(np.all(p>0))
                self.assertAlmostEqual(float(p.sum()),1.)
                self.assertTrue(0<=oracle(r,x,.22)<=1)
        self.assertAlmostEqual(oracle(0,-1,0),oracle(0,1,0))
        self.assertAlmostEqual(oracle(1,-1,0),oracle(1,1,0))

    def test_null_and_confounding(self):
        w=world(12,0,reps=8,n=140)
        np.testing.assert_allclose(w["base_oracle"],w["full_oracle"],atol=1e-12)
        X=w["features"][:,FIRST:]
        proxy=X[:,:,5]-.8*X[:,:,4]/.12
        np.testing.assert_allclose(np.abs(proxy),1.)
        self.assertTrue(np.all(w["worst"]<=0))
        np.testing.assert_array_equal(w["labels"],w["worst"]<=BARRIER)

    def test_future_price_excluded(self):
        t=40
        rng=np.random.default_rng(1)
        c=np.cumsum(rng.normal(0,.03,(3,400)),axis=1)
        a=price_features(c,t)
        c[:,t*7-1:]+=1000
        np.testing.assert_array_equal(a,price_features(c,t))
        self.assertEqual(mature_bounds(136),(28,132))

    def test_replay_small(self):
        w=world(123,.16,reps=3,n=144)
        r=replay(w,warm=136,n=3)
        self.assertEqual(r["gain"].shape,(3,3))
        np.testing.assert_allclose(r["gain"],r["baseline_loss"]-r["challenger_loss"])
        self.assertTrue(np.isfinite(r["scaled_loss"]).all())
        self.assertGreaterEqual(preflight(w,n=3)["oracle_expected_gain"],0)

    def test_detection_not_practical_threshold(self):
        def scenario(gain,oracle_gain):
            a=np.full((256,3),gain)
            return {"gain":a,"baseline_loss":np.full_like(a,.2),
                    "challenger_loss":.2-a,"frequency_loss":np.full_like(a,.22),
                    "scaled_loss":np.full_like(a,.21),"oracle_gain":np.full_like(a,oracle_gain),
                    "oracle_expected":np.full_like(a,oracle_gain)}
        s={"calibration_null":scenario(.001,0),"validation_null":scenario(0,0),
           "planted":scenario(.005,.015),"strong":scenario(.02,.03)}
        r=evaluate(s,sizes=(3,))["3"]
        self.assertAlmostEqual(r["threshold"],.001)
        self.assertTrue(r["detection_check"])
        self.assertFalse(r["mean_gain_check"])
        self.assertFalse(r["synthetic_diagnostic_pass"])
