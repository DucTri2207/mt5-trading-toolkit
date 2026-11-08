"""SYNTHETIC fixture for B6C session tests/demo (loaded by `paper-run --synthetic-fixture`, gated by
QUANTMT5_ALLOW_SYNTHETIC_FIXTURE=1). Variant via QUANTMT5_FIXTURE_VARIANT: default | eur | real | contest | absent | slow."""
import os
import time

from b6b_fake_source import FIXTURE_SESSION, FakeSource


class _Slow(FakeSource):
    def copy_rates_range(self, *a):
        time.sleep(float(os.environ.get("QUANTMT5_FIXTURE_SLOW_S", "30")))
        return super().copy_rates_range(*a)


class _Mode(FakeSource):
    def __init__(self, exe, mode, **kw):
        super().__init__(exe, **kw)
        self._mode = mode

    def account_info(self):
        d = super().account_info()
        d["trade_mode"] = self._mode
        return d


def make(exe, end_utc):
    v = os.environ.get("QUANTMT5_FIXTURE_VARIANT", "default")
    end = int(end_utc)
    if v == "eur":
        src = FakeSource(exe, end=end, login=88022, currency="EUR")
    elif v == "real":
        src = _Mode(exe, 2, end=end)
    elif v == "contest":
        src = _Mode(exe, 1, end=end)
    elif v == "slow":
        src = _Slow(exe, end=end)
    else:
        src = FakeSource(exe, end=end)
    lister = (lambda: []) if v == "absent" else (lambda: [exe])
    return src, lister, {"XAUUSD": FIXTURE_SESSION}
