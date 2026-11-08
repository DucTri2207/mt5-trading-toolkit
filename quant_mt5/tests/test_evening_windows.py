import copy

import numpy as np

from quantmt5.evening_context import reference_windows
from quantmt5.util import iso_utc, parse_utc
from tests.synth import T0, bars


def select(rows, key="ASIA_REFERENCE"):
    return next(r for r in rows if r["window_id"] == key)


def test_window_numeric_complete_boundary_and_late_close():
    b = bars(300, T0, [(100 + i, 102 + i, 99 + i, 101 + i) for i in range(73)])
    b.provenance["time_basis_status"] = "TIME_UNVERIFIED"
    exact = select(reference_windows(b, T0 + 21600, "S"))
    assert exact["lifecycle"] == "PARTIAL" and exact["observed_count"] == 71
    assert exact["high"] is None
    done = select(reference_windows(b, T0 + 21601, "S"))
    assert done["lifecycle"] == "COMPLETED" and done["expected_count"] == done["observed_count"] == 72
    assert done["high"] == 173 and done["low"] == 99  # bar opening at end excluded
    assert done["known_at"] == iso_utc(T0 + 21601)
    assert done["time_quality"]["time_basis_status"] == "TIME_UNVERIFIED"
    assert done["definition_basis"] == "PROJECT_REFERENCE_WINDOW"


def test_window_not_started_developing_no_closed_and_partial_slots():
    b = bars(300, T0, [(100, 102, 99, 101)] * 72)
    london = select(reference_windows(b, T0, "S"), "LONDON_OPEN_REFERENCE")
    assert london["lifecycle"] == "NOT_STARTED" and london["expected_count"] == 0 and london["high"] is None
    early = select(reference_windows(b, T0 + 299, "S"))
    assert early["lifecycle"] == "DEVELOPING" and early["expected_count"] == 0
    dev = select(reference_windows(b, T0 + 601, "S"))
    assert dev["lifecycle"] == "DEVELOPING" and dev["observed_count"] == 2 and dev["high"] is None
    assert dev["observed_high"] == 102
    b.available_at[10] = T0 + 30000
    partial = select(reference_windows(b, T0 + 21601, "S"))
    assert partial["lifecycle"] == "PARTIAL" and partial["observed_count"] == 71
    assert partial["missing_slots"] == [iso_utc(T0 + 3000)]
    assert partial["high"] is None


def test_window_missing_duplicate_bad_ohlc_and_partial_members_are_not_complete():
    b = bars(300, T0, [(100, 102, 99, 101)] * 72)
    for defect in ("duplicate", "ohlc", "members"):
        bad = copy.deepcopy(b)
        if defect == "duplicate":
            bad.open_at[1] = bad.open_at[0]
        elif defect == "ohlc":
            bad.h[1] = 98
        else:
            bad.member_count, bad.expected_members = np.full(72, 5), 5
            bad.member_count[1] = 4
        result = select(reference_windows(bad, T0 + 21601, "S"))
        assert result["lifecycle"] == "PARTIAL" and result["high"] is None


def test_window_dst_and_us_uk_mismatch_weeks_use_local_rules():
    b = bars(300, T0, [(100, 102, 99, 101)])
    for date, london, ny in (("2026-01-15", "08:00", "14:30"), ("2026-07-15", "07:00", "13:30"),
                             ("2026-03-15", "08:00", "13:30"), ("2026-10-28", "08:00", "13:30")):
        windows = reference_windows(b, parse_utc(date + "T18:00:00Z"), "S")
        assert select(windows, "LONDON_OPEN_REFERENCE")["start_utc"] == date + "T" + london + ":00Z"
        assert select(windows, "NEW_YORK_OPEN_REFERENCE")["start_utc"] == date + "T" + ny + ":00Z"
        assert select(windows)["lifecycle"] == "NO_DATA"


def test_future_bars_do_not_change_window_result():
    b = bars(300, T0, [(100, 102, 99, 101)] * 80)
    cutoff = T0 + 21601
    before = reference_windows(b, cutoff, "S")
    b.h[72:] = 999999
    b.l[72:] = -999999
    assert reference_windows(b, cutoff, "S") == before


def test_missing_timezone_database_is_item_unsupported_not_symbol_exception(monkeypatch):
    import quantmt5.evening_context as module
    from zoneinfo import ZoneInfoNotFoundError
    def missing(_):
        raise ZoneInfoNotFoundError("fixture tzdata absent")
    monkeypatch.setattr(module, "ZoneInfo", missing)
    b = bars(300, T0, [(100, 102, 99, 101)])
    result = reference_windows(b, T0 + 301, "S")
    assert len(result) == 3
    assert all(r["item_state"] == "UNSUPPORTED" and r["reason"] == "TZ_DATABASE_UNAVAILABLE" for r in result)
    assert all(r["high"] is None and r["start_utc"] is None for r in result)
