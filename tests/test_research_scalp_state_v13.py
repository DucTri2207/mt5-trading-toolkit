"""Causal state features and quarterly nonlinear estimator isolation."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_state_v13 as v
from test_research_scalp_payoff_v12 import synthetic
from test_research_scalp_seasonal_v10 import stamp


def fixture():
    at=stamp(2022,1,3);i=np.arange(1000);close=100+.001*i+.2*np.sin(i)
    gold=np.c_[at+i*300,close,close+.5,close-.5,close]
    j=np.arange(160);hc=100+.001*j
    h1=np.c_[at+(j-70)*3600,hc,hc+.2,hc-.2,hc]
    return gold,np.ones(1000)*100,h1


class StateChecks(unittest.TestCase):
    def test_feature_prefix_and_h1_future_perturbations(self):
        gold,volume,h1=fixture();indices=np.arange(60,900,6)
        full,known=v.state_features(gold,volume,h1,indices);cut=gold[600,0]
        keep=gold[indices,0]+300<=cut
        pg=gold[gold[:,0]+300<=cut];ph=h1[h1[:,0]+3600<=cut]
        prefix,k=v.state_features(pg,volume[:len(pg)],ph,indices[keep])
        np.testing.assert_array_equal(prefix,full[keep]);np.testing.assert_array_equal(k,known[keep])
        changed=h1.copy();changed[changed[:,0]+3600>cut,1:]*=10
        actual,_=v.state_features(gold,volume,changed,indices)
        np.testing.assert_array_equal(actual[keep],full[keep])
        self.assertTrue(np.all(known[keep]<=gold[indices[keep],0]+300))

    def test_gap_stale_h1_and_quote_activity_definition(self):
        gold,volume,h1=fixture();indices=np.array([300])
        volume[295:301]=200;row,_=v.state_features(gold,volume,h1,indices)
        self.assertAlmostEqual(row[0,10],np.log(2.))
        gold[280:,0]+=300;row,_=v.state_features(gold,volume,h1,indices)
        self.assertTrue(np.all(np.isnan(row)))
        gold,volume,h1=fixture();old=h1[h1[:,0]+3600<gold[300,0]-3600]
        self.assertTrue(np.all(np.isnan(v.state_features(gold,volume,old,indices)[0])))

    def test_feature_groups_require_exact_fx_known_time(self):
        gold,volume,h1=fixture();opp=v.v.seasonal.opportunities(gold)
        fx=np.zeros((len(gold),14));fx[:,0]=gold[:,0]+300
        xs,_=v.inputs(opp,gold,volume,h1,fx)
        self.assertEqual(xs[31].shape[1],16);self.assertEqual(xs[32].shape[1],20);self.assertEqual(xs[33].shape[1],24)
        i=60;at=opp['known'][i];fx[opp['index'][i],0]=at+300
        actual,_=v.inputs(opp,gold,volume,h1,fx)
        self.assertTrue(np.all(np.isnan(actual[33][i,-4:])))
        np.testing.assert_array_equal(xs[31],actual[31])

    def test_nonlinear_bundle_learns_interaction_on_separate_synthetic_samples(self):
        rng=np.random.default_rng(517);x=rng.normal(size=(8000,4));win=x[:,0]*x[:,1]>0
        y=np.c_[np.where(win,.77,-1.02),np.where(~win,.77,-1.02)]
        bundle=v.fit_bundle(x[:6000],y[:6000]);f=v.predict(bundle,x[6000:])
        correct=(f[:,2]>.5)==win[6000:]
        self.assertGreater(correct.mean(),.85);self.assertTrue(np.all((f[:,2:]>=0)&(f[:,2:]<=1)))

    def test_future_outcomes_cannot_change_quarterly_models_or_entries(self):
        opp,payoff,available=synthetic();x=np.c_[opp['lag'],opp['basis'][:,1:]]
        xs={k:x for k in v.NAMES};start=stamp(2022);end=stamp(2022,2)
        raw,records,pred=v.candidates(opp,payoff,available,xs,start,end)
        changed=payoff.copy();changed[np.any(available>=start-7200,axis=1)]=np.nan
        actual,other,forecast=v.candidates(opp,changed,available,xs,start,end)
        np.testing.assert_array_equal(raw,actual);np.testing.assert_array_equal(pred,forecast);self.assertEqual(records,other)
        for r in records:
            self.assertLess(r['last_train_label_known'],r['quarter']-7200)
        self.assertGreater(len(raw),0);self.assertTrue(np.all(raw[:,8]>=55));self.assertTrue(np.all(raw[:,33]>0))


if __name__=='__main__':unittest.main()
