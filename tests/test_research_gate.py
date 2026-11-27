import unittest
import numpy as np
from research_buy_risk import logistic
from research_gate import oracle,world,batch_logistic,replay,wilson,H,WARM

class GateTest(unittest.TestCase):
    def test_oracle(self):
        for r in (0,1):
            self.assertAlmostEqual(oracle(r,-1,0.),oracle(r,1,0.))
            self.assertGreater(oracle(r,1,.1),oracle(r,-1,.1))
        self.assertEqual(oracle(0,1,.1,0,2,2),1.)
        self.assertEqual(oracle(0,1,.1,0,0,2),0.)

    def test_batch_parity(self):
        rng=np.random.default_rng(12)
        x=rng.normal(size=(3,60,3));x[:,:,2]=1.
        y=rng.integers(0,2,size=(3,60)).astype(float)
        cur=rng.normal(size=(3,3));cur[:,2]=1.
        expected=[logistic(a,b,c) for a,b,c in zip(x,y,cur)]
        np.testing.assert_allclose(batch_logistic(x,y,cur),expected,atol=1e-10,rtol=1e-10)

    def test_null_oracles_and_seed(self):
        a=world(12,0.,reps=4,n=120);b=world(12,0.,reps=4,n=120)
        for x,y in zip(a,b):
            np.testing.assert_array_equal(x,y)
        np.testing.assert_allclose(a[2],a[3],atol=1e-12)

    def test_future_label_not_used(self):
        x,y,b,f=world(12,.1,reps=3,n=120)
        a=replay(x,y,b,f,warm=WARM,n=1)
        yy=y.copy()
        # Alter only labels not matured at origin, leaving its scored outcome.
        yy[:,WARM-H+1:WARM]=1-yy[:,WARM-H+1:WARM]
        z=replay(x,yy,b,f,warm=WARM,n=1)
        np.testing.assert_array_equal(a["gain"],z["gain"])

    def test_wilson(self):
        self.assertEqual(wilson(0,128)[0],0.)
        self.assertGreater(wilson(0,128)[1],0.)
