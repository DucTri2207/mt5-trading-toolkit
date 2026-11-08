"""Monthly label availability and past-only transforms for the seasonal models."""
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_seasonal_v10 as v


def stamp(y, m=1, d=1):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp())


def synthetic():
    t = np.arange(stamp(2021), stamp(2022, 2), 3600)
    rng = np.random.default_rng(15); lag = rng.normal(0, 1, len(t)); phase = 2*np.pi*(t % 86400)/86400
    basis = np.c_[np.ones(len(t)), np.sin(phase), np.cos(phase), np.sin(2*phase), np.cos(2*phase)]
    opp = dict(known=t, basis=basis, lag=lag, index=np.arange(len(t)), unit=np.full(len(t), 3.),
               close=np.full(len(t), 100.), atr=np.full(len(t), 2.))
    target = .4*np.sin(phase)-.3*lag*np.cos(phase)+rng.normal(0, .3, len(t))
    return opp, target, t+7260


class SeasonalChecks(unittest.TestCase):
    def test_periodic_features_only_from_closed_contiguous_bars(self):
        t = stamp(2021, 10, 26)+np.arange(250)*300
        close = 100+np.arange(250)*.01
        gold = np.c_[t, close, close+1, close-1, close]
        opp = v.opportunities(gold)
        self.assertTrue(np.all(opp['known'] % 1800 == 0))
        self.assertTrue(np.all(opp['known'] % 86400 >= 7200))
        self.assertTrue(np.all(opp['known'] % 86400 < 18*3600))
        self.assertAlmostEqual(opp['lag'][0], .06/3., places=12)
        gold[100:, 0] += 300
        missing = v.opportunities(gold)
        self.assertFalse(np.any((missing['index'] >= 100) & (missing['index'] <= 105)))

    def test_fixed_time_training_label_respects_latency_and_gaps(self):
        at = stamp(2021, 10, 26)+8*3600
        times = at+np.arange(200)*60; prices = 100+np.arange(200)*.01
        market = np.c_[times, prices, prices, prices, prices]
        opp = dict(known=np.array([at, at+600]), unit=np.array([3., 3.]))
        y, end = v.labels(opp, market)
        np.testing.assert_allclose(y, [.4, .4]); np.testing.assert_array_equal(end, opp['known']+7260)
        market = np.delete(market, 15, axis=0)
        self.assertTrue(np.all(np.isnan(v.labels(opp, market)[0])))

    def test_model_transforms_and_predictions_ignore_future_target_labels(self):
        opp, y, end = synthetic(); start = stamp(2022); stop = stamp(2022, 2)
        before, models = v.candidates(opp, y, end, start, stop)
        changed = y.copy(); changed[end >= start-7200] += 10000
        after, other = v.candidates(opp, changed, end, start, stop)
        np.testing.assert_allclose(before, after, rtol=0, atol=0)
        self.assertEqual(models, other); self.assertGreater(len(before), 0)
        for m in models:
            self.assertLess(m['last_train_label_end'], m['month']-7200)
        self.assertTrue(np.all(before[:, 1]-before[:, 0] == 360))
        self.assertTrue(np.all(before[:, 37]+60 == before[:, 1]))
        self.assertTrue(np.all(before[:, 12] <= before[:, 37]))
        for c in before:
            self.assertAlmostEqual(abs(c[21]-c[19]), 3.)

    def test_ridge_fits_return_direction_and_keeps_transforms_fixed(self):
        rng = np.random.default_rng(9); x = np.c_[np.ones(4000), rng.normal(size=4000)]
        y = .2-.5*x[:, 1]+rng.normal(0, .1, 4000)
        model = v.fit(x, y, np.arange(4000)//100)
        pred, error = v.predict(model, np.array([[1., -2.], [1., 2.]]))
        self.assertGreater(pred[0], 1.); self.assertLess(pred[1], -.7)
        self.assertTrue(np.all(np.isfinite(error))); self.assertTrue(np.all(error >= 0))
        before = {k: a.copy() for k, a in model.items()}
        v.predict(model, np.array([[1., 1e9]]))
        for k in model:
            np.testing.assert_array_equal(model[k], before[k])

    def test_global_control_has_no_calendar_or_usd_input(self):
        opp, _, _ = synthetic(); x = v.design(opp, 23)
        self.assertEqual(x.shape[1], 2)
        np.testing.assert_array_equal(x[:, 1], opp['lag'])
        self.assertEqual(v.design(opp, 21).shape[1], 5)
        self.assertEqual(v.design(opp, 22).shape[1], 10)


if __name__ == '__main__':
    unittest.main()
