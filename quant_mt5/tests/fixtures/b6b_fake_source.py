"""Deterministic SYNTHETIC read-only MT5 source for B6B wiring tests (no terminal). Seeded random walk on the legacy
XAUUSD session schedule + one designed setup-B LONG fakey whose geometry is the oracle.

M1 bars are generated per scheduled-open minute; M5/H1/D1 are aggregated from M1 (D1 = UTC-day buckets, declared to the
collector as a fixture boundary). Ticks: every 10 s inside the tick window, Bid on the M1 path, Ask = Bid + spread."""
from __future__ import annotations

import collections
import datetime as dt
import os

import numpy as np

from quantmt5.coverage import scheduled_open

SESSION = {"kind": "DAILY_BREAK", "tz": "America/New_York", "daily_close": "17:00", "daily_reopen": "18:00", "weekly_close": "Fri 17:00"}
FIXTURE_SESSION = dict(SESSION, d1_boundary={"tz": "UTC", "day_start": "00:00", "status": "SYNTHETIC_FIXTURE_DECLARED"})
MOTHER_OPEN = int(dt.datetime(2025, 1, 15, 14, 0, tzinfo=dt.timezone.utc).timestamp())    # Wednesday, session open
F_CLOSE = MOTHER_OPEN + 900
END = F_CLOSE + 75 * 60
ANCHOR_START = MOTHER_OPEN - 40 * 86400       # data generated once on a fixed anchor → identical bars whatever `end` is
ANCHOR_END = MOTHER_OPEN + 3 * 86400
TF_S = {1: 60, 5: 300, 16385: 3600, 16408: 86400}
SPREAD_PTS = 20
PROFILE = dict(name="XAUUSD", path="Metals\\XAUUSD", digits=2, point=0.01, trade_tick_size=0.01, trade_tick_value=1.0,
               trade_contract_size=100.0, currency_base="XAU", currency_profit="USD", currency_margin="USD", volume_min=0.01,
               volume_max=100.0, volume_step=0.01, trade_stops_level=0, trade_freeze_level=0, trade_calc_mode=2, trade_mode=4, chart_mode=0)
RATE_DT = [("time", "i8"), ("open", "f8"), ("high", "f8"), ("low", "f8"), ("close", "f8"), ("tick_volume", "u8"), ("spread", "i4"), ("real_volume", "u8")]
TICK_DT = [("time_msc", "i8"), ("bid", "f8"), ("ask", "f8")]


def oracle(P: float) -> dict:
    """Mother / inside / fakey (LONG) designed around price P (eps = 1 tick = 0.01)."""
    return {"mother": (P, P + 2.0, P - 2.0, P + 0.5), "inside": (P + 0.4, P + 1.0, P - 1.0, P - 0.2),
            "fakey": (P - 0.5, P + 0.8, P - 2.5, P + 0.3)}


def _m1_of(o, h, l, c):
    """Five M1 bars aggregating exactly to (o, h, l, c)."""
    return [(o, h, min(o, c), o), (o, max(o, c), l, c), (c, c, c, c), (c, c, c, c), (c, c, c, c)]


def build_m1(seed: int, start: int, end: int):
    t = np.arange(start - start % 60, end, 60, dtype=np.int64)
    t = t[scheduled_open(t, SESSION)]
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.12, len(t))
    wick = np.abs(rng.normal(0, 0.06, (len(t), 2)))
    o = np.empty(len(t)); c = np.empty(len(t)); h = np.empty(len(t)); l = np.empty(len(t))
    px = 2000.0
    for i in range(len(t)):
        o[i] = px
        c[i] = px + steps[i]
        h[i] = max(o[i], c[i]) + wick[i, 0]
        l[i] = min(o[i], c[i]) - wick[i, 1]
        px = c[i]
    r = np.round(np.c_[o, h, l, c], 2)
    # designed triplet
    i0 = int(np.searchsorted(t, MOTHER_OPEN))
    assert t[i0] == MOTHER_OPEN and t[i0 + 14] == MOTHER_OPEN + 14 * 60, "oracle minutes must be open"
    P = float(r[i0, 0])
    orc = oracle(P)
    rows = [b for name in ("mother", "inside", "fakey") for b in _m1_of(*orc[name])]
    shift = rows[-1][3] - r[i0 + 14, 3]
    r[i0:i0 + 15] = np.array(rows)
    r[i0 + 15:] += shift                                             # continuity after the fakey
    r = np.round(r, 2)
    a = np.zeros(len(t), dtype=RATE_DT)
    a["time"], a["open"], a["high"], a["low"], a["close"] = t, r[:, 0], r[:, 1], r[:, 2], r[:, 3]
    a["tick_volume"], a["spread"] = 10, SPREAD_PTS
    return a, {k: tuple(round(x, 2) for x in v) for k, v in orc.items()}, P


def aggregate(m1: np.ndarray, step: int | None) -> np.ndarray:
    key = (m1["time"] // 86400 * 86400) if step is None else (m1["time"] // step * step)
    u, idx = np.unique(key, return_index=True)
    out = np.zeros(len(u), dtype=RATE_DT)
    ends = np.r_[idx[1:], len(m1)]
    for j, (s, e) in enumerate(zip(idx, ends)):
        seg = m1[s:e]
        out[j] = (u[j], seg["open"][0], seg["high"].max(), seg["low"].min(), seg["close"][-1], seg["tick_volume"].sum(), SPREAD_PTS, 0)
    return out


def build_ticks(m1: np.ndarray, t0: int, t1: int) -> np.ndarray:
    rows = []
    for b in m1[(m1["time"] >= t0 - 60) & (m1["time"] < t1)]:
        path = [b["open"], b["open"], b["high"], b["low"], b["close"], b["close"]]    # o → o → h → l → c (extremes visited)
        for k in range(6):
            ts = int(b["time"]) * 1000 + k * 10_000
            if t0 * 1000 <= ts < t1 * 1000:
                rows.append((ts, round(float(path[k]), 2), round(float(path[k]) + SPREAD_PTS * 0.01, 2)))
    return np.array(rows, dtype=TICK_DT)


class FakeSource:
    ORDER_TYPE_BUY, ORDER_TYPE_SELL = 0, 1
    TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_H1, TIMEFRAME_D1, COPY_TICKS_ALL = 1, 5, 16385, 16408, -1

    def __init__(self, exe: str, seed: int = 20261104, end: int = END, login: int = 70011, server: str = "Synth-Demo",
                 currency: str = "USD", data_path: str = "D:/SYNTH/data", switch_account_after_calls: int | None = None,
                 profile: dict | None = None, tick_window: tuple[int, int] | None = None):
        self.exe, self.login, self.server, self.currency, self.data_path = exe, login, server, currency, data_path
        self.switch, self.n_acc, self.calls = switch_account_after_calls, 0, []
        self.profile = profile or PROFILE
        self.end = int(end)
        self._live = {}
        self.m1, self.oracle, self.P = build_m1(seed, ANCHOR_START, ANCHOR_END)
        self.tf = {self.TIMEFRAME_M1: self.m1, self.TIMEFRAME_M5: aggregate(self.m1, 300), self.TIMEFRAME_H1: aggregate(self.m1, 3600),
                   self.TIMEFRAME_D1: aggregate(self.m1, None)}
        tw = tick_window or (MOTHER_OPEN, self.end)
        self.ticks = build_ticks(self.m1, tw[0], min(tw[1], self.end))

    def __getattr__(self, k):
        raise AttributeError(k)

    def initialize(self, path=None):
        self.calls.append("initialize")
        return True

    def shutdown(self):
        self.calls.append("shutdown")

    def last_error(self):
        return (0, "ok")

    def terminal_info(self):
        return {"path": os.path.dirname(self.exe), "data_path": self.data_path, "connected": True, "build": 5000, "company": "SYNTH"}

    def account_info(self):
        self.n_acc += 1
        login = self.login + 1 if (self.switch is not None and self.n_acc > self.switch) else self.login
        return {"login": login, "server": self.server, "currency": self.currency, "trade_mode": 0}

    def symbol_info(self, s):
        d = dict(self.profile, name=s)
        return collections.namedtuple("SI", list(d))(*d.values())

    def symbol_info_tick(self, s):
        last = self.ticks[-1] if len(self.ticks) else None
        return None if last is None else {"time": int(last["time_msc"] // 1000), "time_msc": int(last["time_msc"]), "bid": float(last["bid"]),
                                          "ask": float(last["ask"])}

    def copy_rates_range(self, s, tf, a, b):
        self.calls.append("copy_rates_range")
        # like MT5: closed bars + the FORMING bar (partial values from the minutes seen so far)
        if tf not in self._live:
            m = self.m1[self.m1["time"] < self.end]
            self._live[tf] = m if tf == self.TIMEFRAME_M1 else aggregate(m, None if tf == self.TIMEFRAME_D1 else TF_S[tf])
        r = self._live[tf]
        return r[(r["time"] >= int(a)) & (r["time"] <= int(b))]

    def copy_ticks_range(self, s, a, b, flags):
        self.calls.append("copy_ticks_range")
        t = self.ticks
        return t[(t["time_msc"] >= int(a) * 1000) & (t["time_msc"] <= int(b) * 1000 + 999)]

    def order_calc_profit(self, t, s, v, a, b):
        return (b - a) * (1 if t == 0 else -1) * 100.0 * v

    def order_calc_margin(self, t, s, v, a):
        return None

    def order_send(self, *a):
        raise AssertionError("order_send must be unreachable")
