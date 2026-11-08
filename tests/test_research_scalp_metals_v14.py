"""Exact silver alignment, causal calibration, rule state and model label isolation."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_metals_v14 as v
from test_research_scalp_payoff_v12 import synthetic
from test_research_scalp_seasonal_v10 import stamp


def market_fixture():
    rng=np.random.default_rng(991);i=np.arange(8500);at=stamp(2021)
    silver=25+np.cumsum(rng.normal(0,.006,len(i)))
    gold=1500+np.cumsum(rng.normal(0,.08,len(i)))+20*(silver-25)
    make=lambda c,width:np.c_[at+i*300,c,c+width,c-width,c]
    return make(gold,.2),make(silver,.012)


class MetalChecks(unittest.TestCase):
    def test_raw_silver_calibration_and_model_feature_prefix(self):
        gold,silver=market_fixture();opp=v.v.seasonal.opportunities(gold)
        control=np.ones((len(opp['known']),24));full,picked,calibrated,_=v.metal_inputs(gold,silver,opp,control)
        cut=int(gold[7000,0]);keep=opp['known']<=cut
        po={k:a[keep] for k,a in opp.items()}
        actual,pp,pc,_=v.metal_inputs(gold[gold[:,0]+300<=cut],silver[silver[:,0]+300<=cut],po,control[keep])
        for k in v.MODEL_IDS:np.testing.assert_array_equal(actual[k],full[k][keep])
        np.testing.assert_array_equal(pp,picked[keep]);np.testing.assert_array_equal(pc,calibrated[gold[:,0]+300<=cut])
        valid=np.isfinite(picked[:,0]);self.assertGreater(valid.sum(),50)
        self.assertTrue(np.all(picked[valid,9]<=picked[valid,0]-900))

    def test_missing_exact_quote_prior_gap_and_matched_model_rows(self):
        gold,silver=market_fixture();opp=v.v.seasonal.opportunities(gold);control=np.ones((len(opp['known']),24))
        full,picked,_,_=v.metal_inputs(gold,silver,opp,control)
        valid=np.where(np.all(np.isfinite(full[37]),axis=1))[0];self.assertGreater(len(valid),0)
        row=valid[10];i=opp['index'][row]
        missing=np.delete(silver,i,axis=0);actual,p,_,_=v.metal_inputs(gold,missing,opp,control)
        self.assertTrue(np.isnan(p[row]).all());self.assertTrue(np.isnan(actual[36][row]).all())
        missing=np.delete(silver,i-30,axis=0);actual,_,_,_=v.metal_inputs(gold,missing,opp,control)
        self.assertTrue(np.isnan(actual[37][row]).all())
        control[row,2]=np.nan;actual,_,_,_=v.metal_inputs(gold,silver,opp,control)
        self.assertTrue(np.isnan(actual[37][row]).all())
        np.testing.assert_array_equal(np.isfinite(actual[36]).all(axis=1),np.isfinite(actual[37]).all(axis=1))
        np.testing.assert_array_equal(actual[36],actual[37][:,:24])

    def test_first_crossing_rearm_directions_gap_and_known_close(self):
        known=stamp(2022,1,3)+np.array([0,1800,3600,5400,9000]);n=len(known)
        opp=dict(known=known,close=np.ones(n)*100,unit=np.ones(n)*2,atr=np.ones(n),index=np.arange(n))
        f=np.zeros((n,14));f[:,0]=known;f[:,3]=[2.1,2.5,1,-2.2,-2.3];f[:,6]=[-2.1,-2.4,0,2.2,2.3];f[:,5]=1
        raw=v.rule_candidates(opp,f,start=known[0],end=known[-1]+1)
        for family in (34,35):
            rows=raw[raw[:,36]==family];np.testing.assert_array_equal(rows[:,37],known[[0,3,4]])
            np.testing.assert_array_equal(rows[:,2],[1,0,0]);np.testing.assert_array_equal(rows[:,1],rows[:,37]+60)
            np.testing.assert_array_equal(rows[:,0],rows[:,37]-300)
        f[:,5]=-1;raw=v.rule_candidates(opp,f,start=known[0],end=known[-1]+1)
        self.assertFalse(np.any(raw[:,36]==35))

    def test_future_purged_labels_cannot_change_quarterly_forecasts(self):
        opp,payoff,available=synthetic();x=np.c_[opp['lag'],opp['basis'][:,1:]]
        xs={36:x,37:np.c_[x,x[:,0]**2]};start=stamp(2022);end=stamp(2022,2)
        raw,records,pred=v.model_candidates(opp,payoff,available,xs,start,end)
        changed=payoff.copy();changed[np.any(available>=start-7200,axis=1)]=np.nan
        actual,other,forecast=v.model_candidates(opp,changed,available,xs,start,end)
        np.testing.assert_array_equal(raw,actual);np.testing.assert_array_equal(pred,forecast);self.assertEqual(records,other)
        self.assertGreater(len(raw),0)
        for r in records:self.assertLess(r['last_train_label_known'],r['quarter']-7200)


if __name__=='__main__':unittest.main()
