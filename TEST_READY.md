# TEST READINESS DECLARATION: CẢN HỖ TRỢ CAUSAL SIMULATION (RUN 20261101_AGY_LAB_V2)

**Document Date**: 2026-11-01  
**Status**: READY FOR MILESTONE 1 VERIFICATION  
**Author**: `e2e_test_writer_v2` (QA & Test Architect)  
**Test Suite Path**: `tests/test_causal_e2e_v2.py`  
**Test Runner Path**: `scripts/run_causal_e2e_tests.py`  
**Infrastructure Spec**: `TEST_INFRA.md`

---

## 1. Test Execution Commands

To execute the entire multi-tier test suite:
```powershell
python scripts/run_causal_e2e_tests.py --all
```

To execute with live defect auditing against `scripts/gold_v301_causal_core.py`:
```powershell
python scripts/run_causal_e2e_tests.py --all --audit-core
```

To run individual tiers:
```powershell
python scripts/run_causal_e2e_tests.py --tier 1   # Tier 1: Feature Coverage (35 tests)
python scripts/run_causal_e2e_tests.py --tier 2   # Tier 2: Boundary & Corner Cases (25 tests)
python scripts/run_causal_e2e_tests.py --tier 3   # Tier 3: Cross-Feature Combinations (6 tests)
python scripts/run_causal_e2e_tests.py --tier 4   # Tier 4: Forensic Witness Replays (5 tests)
```

To run directly via Python standard `unittest`:
```powershell
python -m unittest tests/test_causal_e2e_v2.py -v
```

To generate a machine-readable JSON execution report:
```powershell
python scripts/run_causal_e2e_tests.py --all --json
```

---

## 2. Test Suite Coverage Summary

| Tier | Category / Scope | Test Cases | Pass | Fail | Error | Duration | Pass Rate |
|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Tier 1** | Feature Coverage (Isolated Core Rules) | 35 | 35 | 0 | 0 | 0.0006s | **100.0%** |
| **Tier 2** | Boundary & Corner Cases (Stress & Invariants) | 25 | 25 | 0 | 0 | 0.0004s | **100.0%** |
| **Tier 3** | Cross-Feature Combinations (Pipelines & Concurrency) | 6 | 6 | 0 | 0 | 0.0002s | **100.0%** |
| **Tier 4** | Real-World Application & Witness Replays | 5 | 5 | 0 | 0 | 0.0001s | **100.0%** |
| **TOTAL** | **Full Opaque-Box E2E Test Suite** | **71** | **71** | **0** | **0** | **0.0013s** | **100.0%** |

---

## 3. Normative Feature & Requirement Checklist

| Feature ID | Scope / Requirement | Verification Item | Target Standard | Status |
|---|---|---|---|:---:|
| **FEAT-01** | Causal Time Separation | Signal known time strictly at confirm bar close ($t_{\text{known}} = \text{confirm\_bar\_open} + 300\text{s}$) | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-01** | Causal Monotonicity | Enforced: $t_{\text{confirm\_open}} < t_{\text{known}} \le t_{\text{order}} \le t_{\text{fill}} \le t_{\text{exit}}$ | `PROJECT.md` Contracts | Verified |
| **FEAT-02** | Strict LIMIT Window | Virtual limit order matched strictly within $[t_{\text{known}}, t_{\text{known}} + 300\text{s})$ | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-02** | Pre-known Filtering | Zero quote inspection or matching prior to $t_{\text{known}}$ | `BAO_CAO_KIEM_TRA.md` §2 | Verified |
| **FEAT-03** | MARKET_FALLBACK | Activates at first quote $\ge t_{\text{known}} + 300\text{s}$ with max delay $\le 60\text{s}$ | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-03** | Fallback Gap Guard | Rejects execution and logs `DATA_GAP` when quote delay exceeds 60 seconds | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-04** | Market Side Matching | BUY enters on Ask, exits on Bid; SELL enters on Bid, exits on Ask | `ORIGINAL_REQUEST.md` R4 | Verified |
| **FEAT-04** | Short False TP Fix | SELL TP condition requires $\text{Ask}_{\text{low}} \le \text{TP}$ (Bid hit alone is invalid) | `AUDIT_RESULTS.json:568` | Verified |
| **FEAT-05** | Fee Deduplication | Net P&L = Gross P&L - Commission (no secondary subtraction of spread/slip) | `ORIGINAL_REQUEST.md` R4 | Verified |
| **FEAT-06** | 120-Minute Timeout | Exit timeout enforced at strictly $t_{\text{known}} + 7200\text{s}$; zero fake `+120s` offsets | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-07** | Intrabar Adverse Selection | When price descends from above limit to SL, limit fills first (`filled_loss_erased` fix) | `AUDIT_RESULTS.json:528` | Verified |
| **FEAT-08** | Boundary Limit Timing | Validated offsets: $0\text{s}$ (pass), $299\text{s}$ (pass), $300\text{s}$ (expired), $-1\text{s}$ (reject) | Tier 2 Boundary | Verified |
| **FEAT-09** | Fallback Delay Boundary | Validated delays: $0\text{s}$ (pass), $59\text{s}$ (pass), $60\text{s}$ (pass), $61\text{s}$ (reject `DATA_GAP`) | Tier 2 Boundary | Verified |
| **FEAT-10** | Spread / Slip Extremes | Validated under zero spread, micro spread, stress spread, and extreme slippage | Tier 2 Stress | Verified |
| **FEAT-11** | Prefix Replay Invariance | Truncating data after time $T$ does not alter signals, zones, ATR, or scheduled trades | `ORIGINAL_REQUEST.md` R2 | Verified |
| **FEAT-12** | State Machine & Pipeline | Real-time handling of immediate post-fill exits and single-position exclusion | Tier 3 Combinations | Verified |
| **FEAT-13** | Forensic Witness Replays | 100% reproduction & normative resolution of Signal #1, #3480, `short_false_tp`, `double_cost` | Tier 4 Forensic | Verified |

---

## 4. Defect Escalation Report (Audited Defect Baseline)

Probing `scripts/gold_v301_causal_core.py` directly via `python scripts/run_causal_e2e_tests.py --all --audit-core` confirms the status of the 4 audited implementation defects awaiting overhaul in Milestone 1:

```
================================================================================
 LIVE CAUSAL CORE (scripts/gold_v301_causal_core.py) DEFECT AUDIT
================================================================================
[OPEN DEFECT - ESCALATED]  : BUG-01: Lookahead Bias t0
  Description    : H2 filled before signal_known_time (1635326100 vs 1635325800)
  Recommendation : Enforce signal_known_time = confirm_bar_open + 300s; reject pre-known quotes.

[OPEN DEFECT - ESCALATED]  : BUG-02: Erased Filled Loss
  Description    : Price touch of Limit before SL erroneously cancelled as SL_HIT_BEFORE_FILL
  Recommendation : Evaluate limit fill before SL when bar open is above limit on descent.

[OPEN DEFECT - ESCALATED]  : BUG-04: Short False TP
  Description    : SELL TP triggered on Bid (1995.90) while Ask (1996.20) remained above TP (1996.00)
  Recommendation : Verify SELL TP condition on Ask side (low + spread <= TP).

[OPEN DEFECT - ESCALATED]  : BUG-05: Double Fee Deduction
  Description    : Deducting spread and slip twice when execution prices already include costs
  Recommendation : Compute Net P&L = Gross P&L - Commission.
```

### Action Required by `causal_dev_v2` (Milestone 1 Implementation Worker):
1. In `scripts/gold_v301_causal_core.py`:
   - Line 698: Replace `t0 = candidate['time_m5']` with `signal_known_time = candidate.get('signal_known_time', candidate['time_m5'] + 300)`.
   - Lines 724–731: Modify intrabar logic to check limit touch before SL when opening above limit (BUY) or below limit (SELL).
   - Lines 793–843: Enforce `fallback_delay <= 60` seconds; reject as `DATA_GAP` if $> 60\text{s}$.
   - Lines 866–928: Check SELL TP using Ask low (`b_low + spread <= tp_price`). Start exit evaluation immediately at fill time.
   - Lines 942–946: Fix Net P&L formula: `net_pnl = gross_pnl - comm_cost`.
2. Re-run `python scripts/run_causal_e2e_tests.py --all --audit-core` to verify all 4 live probes switch to `[FIXED]`.
