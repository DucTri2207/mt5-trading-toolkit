"""Availability, calibration, independent controls and two-sided assay cost checks."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import research_scalp_intermarket_v9 as v

AT = 1635253200  # Tuesday,13:00 in numeric feed hours.


def fixture(n=250):
    rng = np.random.default_rng(71)
    x = np.cumsum(rng.normal(0, .001, n))
    y = -.7*x+np.cumsum(rng.normal(0, .0006, n))
    price = 100*np.exp(y); times = AT+np.arange(n)*300
    gold = np.c_[times, price, price+1, price-1, price]
    return gold, x


def feature_row(at=AT, family=0, d=1):
    r = np.array([at, .001, -.0001, -3., 1., -.7, -2., 2., 6000., at-900,
                  -.001, 98., 102., 100., family, d], float)
    return r


class IntermarketChecks(unittest.TestCase):
    def test_alignment_does_not_fill_missing_or_shift_to_future(self):
        gold, _ = fixture(8)
        dtype = [('time', 'i8'), ('close', 'f8')]
        fx = {}
        for symbol in v.SYMBOLS:
            a = np.zeros(8, dtype=dtype); a['time'] = gold[:, 0]; a['close'] = 1.2; fx[symbol] = a
        fx['USDSEK'] = fx['USDSEK'][[0, 1, 2, 4, 5, 6, 7]]
        basket, report = v.align(gold, fx)
        self.assertTrue(np.isnan(basket[3])); self.assertTrue(np.all(np.isfinite(basket[[2, 4]])))
        self.assertEqual(report['all_six']['missing_on_gold'], 1)

    def test_features_prefix_and_future_perturbation(self):
        gold, x = fixture(); full = v.features(gold, x, 20)
        prefix = v.features(gold[:160], x[:160], 20)
        np.testing.assert_allclose(full[:160], prefix, equal_nan=True, rtol=0, atol=0)
        gold[160:, 1:] *= 9; x[160:] += 2
        changed = v.features(gold, x, 20)
        np.testing.assert_allclose(full[:160], changed[:160], equal_nan=True, rtol=0, atol=0)
        valid = np.isfinite(full[:, 0]); self.assertTrue(np.all(full[valid, 9] <= full[valid, 0]-900))

    def test_calibration_ols_excludes_current_impulse(self):
        gold, x = fixture(); f = v.features(gold, x, 20); i = 180
        # Hand-computed calibration includes return endpoints3..i-3 only.
        xx = x[3:i-2]-x[:i-5]; yy = np.log(gold[3:i-2, 4]/gold[:i-5, 4])
        beta = np.mean((xx-xx.mean())*(yy-yy.mean()))/np.var(xx)
        self.assertAlmostEqual(f[i, 5], beta, places=12)
        self.assertEqual(f[i, 8], len(xx))
        changed = gold.copy(); changed[i-2:i+1, 1:] *= 1.1
        other = v.features(changed, x, 20)
        self.assertEqual(f[i, 5], other[i, 5]); self.assertNotEqual(f[i, 6], other[i, 6])

    def test_features_invalidate_a_missing_component_or_bar(self):
        gold, x = fixture(); x[100] = np.nan
        f = v.features(gold, x, 20)
        self.assertTrue(np.all(np.isnan(f[100:104, 0]))); self.assertTrue(np.isfinite(f[104, 0]))
        gold[150:, 0] += 300
        f = v.features(gold, x, 20)
        self.assertTrue(np.all(np.isnan(f[150:153, 0]))); self.assertTrue(np.isfinite(f[153, 0]))

    def test_crossing_consumed_outside_hours_and_thirty_minute_gap(self):
        raw = np.array([feature_row(AT+j*300)[:14] for j in range(20)])
        raw[:, 3] = 0; raw[:, 4] = 0; raw[:, 6] = 0
        raw[[0, 1, 3, 7, 8], 3] = -3
        result = v.events(raw, AT-1, AT+10000)
        impulse = result[result[:, 14] == 0]
        self.assertEqual(impulse[:, 0].tolist(), [AT, AT+2100])
        raw[0, 0] = AT//86400*86400+7*3600+55*60
        raw[1, 0] = raw[0, 0]+300; raw[2:, 0] = raw[1, 0]+np.arange(1, 19)*300
        result = v.events(raw, raw[0, 0]-1, AT+10000)
        self.assertFalse(np.any(result[:, 0] == raw[1, 0]))

    def test_catchup_requires_negative_beta_and_underresponse(self):
        raw = np.array([feature_row(AT+j*1800)[:14] for j in range(5)])
        raw[:, 3] = [-3, -3, -3, -3, -3]; raw[:, 6] = [-2, 2, -2, -.5, -2]
        raw[2, 5] = .7
        result = v.events(raw, AT-1, AT+10000)
        catch = result[result[:, 14] == 1]
        self.assertEqual(catch[:, 0].tolist(), [AT, AT+7200])
        self.assertTrue(np.all(catch[:, 15] == 1))

    def test_costs_use_ask_bid_and_slippage_both_sides(self):
        market = np.c_[AT+np.arange(70)*60, np.full((70, 4), 100.)]
        market[16, 1] = 101.
        for d in (1, -1):
            raw = feature_row(d=d)[None, :]
            fills, _ = v.selected_fills(raw, market, dict(family=0, delay=1, hold=15), AT+10000)
            r = v.with_cost(fills, dict(id='BASE', spread=.3, slip=.01, commission_price=.07))[0]
            self.assertAlmostEqual(r['net_price'], d*1.-.39, places=10)
            self.assertAlmostEqual(r['r'], r['gross_r']-r['commission_r'], places=10)
            self.assertEqual(r['fees_status'], 'ASSUMED_BASE')

    def test_unobserved_future_target_still_consumes_entry_and_occupancy(self):
        market = np.c_[AT+np.arange(130)*60, np.full((130, 4), 100.)]
        market = np.delete(market, 10, axis=0)
        raw = np.array([feature_row(AT), feature_row(AT+900), feature_row(AT+3600)])
        rows, rejects = v.selected_fills(raw, market, dict(family=0, delay=1, hold=60), AT+10000)
        self.assertEqual(len(rows), 2); self.assertEqual(rows[0]['state'], 'CENSORED_FILLED')
        self.assertEqual(rejects['BUSY'], 1)
        cost = dict(id='BASE', spread=.3, slip=.01, commission_price=.07)
        self.assertIsNone(v.with_cost(rows, cost)[0]['r'])

    def test_daily_and_weekly_entry_caps_and_latency(self):
        minutes = np.arange(8*1440); times = AT//86400*86400+minutes*60
        market = np.c_[times, np.full((len(times), 4), 100.)]
        raw = np.array([feature_row(int(t)) for t in times[::60]])
        rows, _ = v.selected_fills(raw, market, dict(family=0, delay=5, hold=15), int(times[-1]+60))
        days = {}; weeks = {}
        for r in rows:
            self.assertEqual(r['entry_time']-r['signal_time'], 300)
            day = r['entry_time']//86400; wk = v.w.week_key(r['entry_time'])
            days[day] = days.get(day, 0)+1; weeks[wk] = weeks.get(wk, 0)+1
        self.assertEqual(max(days.values()), 2); self.assertEqual(max(weeks.values()), 10)


if __name__ == '__main__':
    unittest.main()
