"""Payoff-target/actual execution identity and strictly past monthly labels."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_payoff_v12 as v
from test_research_scalp_seasonal_v10 import stamp


def synthetic():
    t=np.arange(stamp(2021),stamp(2022,2),3600);phase=2*np.pi*(t%86400)/86400
    rng=np.random.default_rng(104);lag=rng.normal(size=len(t))
    basis=np.c_[np.ones(len(t)),np.sin(phase),np.cos(phase),np.sin(2*phase),np.cos(2*phase)]
    opp=dict(known=t,basis=basis,lag=lag,index=np.arange(len(t)),unit=np.full(len(t),3.),
             close=np.full(len(t),100.),atr=np.full(len(t),2.))
    probs=np.c_[.55+.2*np.cos(phase),.55-.2*np.cos(phase)]
    payoff=np.where(rng.random((len(t),2))<probs,.77,-1.02)
    available=np.repeat((t+7320)[:,None],2,axis=1)
    return opp,payoff,available


class PayoffChecks(unittest.TestCase):
    def test_reference_and_monthly_candidate_have_identical_money_inputs(self):
        opp,_,_=synthetic();i=9000
        for buy in (True,False):
            a=v.make_candidate(opp,i,buy);b=v.make_candidate(opp,i,buy,29,stamp(2022))
            money=[0,1,2,18,19,20,21,22]
            np.testing.assert_array_equal(a[money],b[money])
            self.assertEqual(b[1]-b[37],60)
            self.assertLessEqual(b[12],b[0])

    def test_labels_equal_serial_execution_after_costs_and_wait_full_horizon(self):
        at=stamp(2022,1,3)+12*3600
        opp=dict(known=np.array([at]),unit=np.array([2.]),close=np.array([100.]),
                 atr=np.array([4/3]),index=np.array([0]))
        market=np.array([[at+60,100,104,96,100]],float)
        payoff,available,risk,_=v.build_labels(opp,market)
        for side,buy in enumerate((True,False)):
            c=v.make_candidate(opp,0,buy,29,stamp(2022))
            trades,_=v.execution.run_serial(c[None,:],market,dict(sources=[29]),v.w.COSTS[1])
            r=trades[0];self.assertEqual(r['reason'],'STOP');self.assertEqual(r['ambiguous_minutes'],1)
            self.assertEqual(payoff[0,side],r['r']);self.assertEqual(risk[0,side],r['risk'])
            self.assertEqual(available[0,side],at+7320)
            self.assertLess(payoff[0,side],-1.)

    def test_current_and_purged_labels_cannot_change_monthly_entry_decisions(self):
        opp,payoff,available=synthetic();start=stamp(2022);stop=stamp(2022,2)
        raw,models,pred=v.candidates(opp,payoff,available,start,stop)
        changed=payoff.copy();changed[np.any(available>=start-7200,axis=1)]=np.nan
        actual,other,forecast=v.candidates(opp,changed,available,start,stop)
        np.testing.assert_array_equal(raw,actual);np.testing.assert_array_equal(pred,forecast)
        self.assertEqual(models,other);self.assertGreater(len(raw),0)
        self.assertTrue(np.all(raw[:,8]>=55));self.assertTrue(np.all(raw[:,33]>0))
        for m in models:
            self.assertLess(m['last_train_label_known'],m['month']-7200)

    def test_logistic_probability_and_training_transform_are_stable(self):
        rng=np.random.default_rng(58);x=np.c_[np.ones(5000),rng.normal(size=5000)]
        prob=1/(1+np.exp(-(.3+.8*x[:,1])));y=(rng.random(len(x))<prob).astype(float)
        model=v.logistic_fit(x,y);before={k:a.copy() if isinstance(a,np.ndarray) else a for k,a in model.items()}
        out=v.logistic_predict(model,np.array([[1.,-2.],[1.,2.],[1.,-1e8],[1.,1e8]]))
        self.assertTrue(model['converged']);self.assertLess(out[0],.3);self.assertGreater(out[1],.8)
        self.assertTrue(np.all((out>0)&(out<1)))
        for k,a in model.items():
            if isinstance(a,np.ndarray):np.testing.assert_array_equal(a,before[k])

    def test_calendar_interaction_and_global_control_match_frozen_feature_sizes(self):
        opp,payoff,available=synthetic();raw,models,pred=v.candidates(opp,payoff,available,stamp(2022),stamp(2022,2))
        for m,size in zip(models,(5,10,2)):
            self.assertEqual(len(m['sides'][0]['net']['beta']),size)
            self.assertEqual(len(m['sides'][0]['win']['beta']),size)
        # Direction can be selected without observing either current outcome.
        missing=payoff.copy();missing[opp['known']>=stamp(2022)]=1e8
        other,_,otherpred=v.candidates(opp,missing,available,stamp(2022),stamp(2022,2))
        np.testing.assert_array_equal(raw,other);np.testing.assert_array_equal(pred,otherpred)


if __name__=='__main__':unittest.main()
