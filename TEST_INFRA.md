# TEST INFRASTRUCTURE SPECIFICATION: CẢN HỖ TRỢ CAUSAL SIMULATION OVERHAUL (RUN 20261101_AGY_LAB_V2)

**Document Version**: 2.0.0  
**Status**: APPROVED & LOCKED  
**Author**: `e2e_test_writer_v2` (QA & Test Architect)  
**Target Modules**: `scripts/gold_v301_causal_core.py`, `scripts/run_can_ho_tro_lab_experiments.py`, `duc_tri_can_ho_tro_agy_lab.mq5`  
**Reference Standards**: `ORIGINAL_REQUEST.md`, `PROJECT.md`, `reports/can_ho_tro_agy_review/20261101/BAO_CAO_KIEM_TRA.md`, `reports/can_ho_tro_agy_review/20261101/AUDIT_RESULTS.json`

---

## 1. Test Philosophy & Core Principles

### 1.1 Opaque-Box & Requirement-Driven Testing
The testing infrastructure is built upon the **Opaque-Box (Black-Box)** paradigm. Tests evaluate behavior strictly against normative specifications, market mechanics, and causal invariants defined in `ORIGINAL_REQUEST.md` and `PROJECT.md`, without coupling to mutable private implementation details of `scripts/gold_v301_causal_core.py`.

### 1.2 The 4-Tier Testing Methodology
The verification framework is structured into four distinct hierarchical tiers:

```
┌────────────────────────────────────────────────────────────────────────┐
│ Tier 4: Real-World Application & Forensic Witness Scenarios            │
│ Replays exact audited witness cases (Signal #1, #3480, short_false_tp) │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 3: Cross-Feature Interactions & Portfolio Pipeline                │
│ Intrabar sequencing, single-position lock, multi-event concurrency    │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 2: Boundary & Corner Conditions (Stress / Invariants)             │
│ Window edges [0s, 299s, 300s], fallback delay [59s, 61s], zero-spread  │
├────────────────────────────────────────────────────────────────────────┤
│ Tier 1: Feature Coverage & Causal Invariants (Isolated Units)          │
│ >= 5 tests per feature: t0 close, LIMIT window, Bid/Ask, fee dedup     │
└────────────────────────────────────────────────────────────────────────┘
```

- **Tier 1 (Feature Coverage, $\ge 5$ tests per feature)**: Isolated validation of primary functional paths: timestamp causality ($t_{\text{known}} = \text{confirm\_bar\_open} + 300\text{s}$), LIMIT window $[t_{\text{known}}, t_{\text{known}} + 300\text{s})$, MARKET_FALLBACK quote delay $\le 60\text{s}$, SELL TP on Ask side, single-deduction fee accounting, 120-minute timeout, and M1 adverse path selection.
- **Tier 2 (Boundary & Corner Cases, $\ge 5$ tests per boundary)**: Stressing edge conditions: limit fill at $t=0\text{s}$ vs $299\text{s}$ vs $300\text{s}$ (expired); fallback quote delay at $59\text{s}$ vs $60\text{s}$ vs $61\text{s}$ (reject/`DATA_GAP`); zero spread; extreme slippage; prefix replay assertion (future data cannot alter past trades).
- **Tier 3 (Cross-Feature Combinations)**: Multi-feature interactions: limit fill then immediate SL/TP in same minute; fallback fill then exit in same minute; SELL order TP hit on Bid but Ask above TP; overlapping signals arriving under active single-position lock.
- **Tier 4 (Real-World Application Scenarios)**: Exact replay of audited failure witnesses from `AUDIT_RESULTS.json`: Signal #1 $t_0$ lookahead witness, Signal #3480 / synthetic `filled_loss_erased` witness, `short_false_tp` witness, and `double_cost` accounting witness.

### 1.3 Causal Invariants & Mathematical Properties
Every test case enforces the following mathematical assertions:
1. **Timestamp Monotonicity**:
   $$\text{confirm\_bar\_open} < t_{\text{known}} \le t_{\text{order\_placed}} \le t_{\text{fill}} \le t_{\text{exit}}$$
2. **LIMIT Matching Window**:
   $$t_{\text{known}} \le t_{\text{fill\_limit}} < t_{\text{known}} + 300\text{s}$$
3. **Fallback Matching Window & Guard**:
   $$t_{\text{known}} + 300\text{s} \le t_{\text{fill\_fallback}} \le t_{\text{known}} + 360\text{s}$$
   $$\text{If } t_{\text{quote}} > t_{\text{known}} + 360\text{s} \implies \text{Status} = \text{REJECTED (DATA\_GAP)}$$
4. **Market Side Matching**:
   $$\text{BUY Entry} = \text{Ask} = \text{Bid} + \text{Spread} + \text{Slip}_{\text{in}}$$
   $$\text{BUY Exit} = \text{Bid} - \text{Slip}_{\text{out}}$$
   $$\text{SELL Entry} = \text{Bid} - \text{Slip}_{\text{in}}$$
   $$\text{SELL Exit} = \text{Ask} = \text{Bid} + \text{Spread} + \text{Slip}_{\text{out}}$$
   $$\text{SELL TP Trigger}: \text{Ask}_{\text{low}} \le \text{TP}$$
5. **Consistent Cost Accounting (No Double Deduction)**:
   $$\text{Gross P\&L} = \text{direction} \times (P_{\text{exit}} - P_{\text{entry}})$$
   $$\text{Net P\&L} = \text{Gross P\&L} - \text{Commission}$$

---

## 2. Feature Inventory Mapping to Test Tiers

| Feature ID | Feature Name | Description | Test Tier | Minimum Test Count |
|---|---|---|---|:---:|
| **FEAT-01** | Causal Time Separation | $t_{\text{known}} = \text{confirm\_bar\_open} + 300\text{s}$, strict monotonic order | Tier 1, 4 | 5 |
| **FEAT-02** | LIMIT Execution Window | Virtual limit order matched strictly in $[t_{\text{known}}, t_{\text{known}} + 300\text{s})$ | Tier 1, 2 | 5 |
| **FEAT-03** | MARKET_FALLBACK Activation | First quote $\ge t_{\text{known}} + 300\text{s}$, max delay $60\text{s}$, reject if $>60\text{s}$ | Tier 1, 2 | 5 |
| **FEAT-04** | Bid/Ask Side Separation | BUY on Ask/Bid; SELL on Bid/Ask; SELL TP strictly verified on Ask | Tier 1, 3, 4 | 5 |
| **FEAT-05** | Fee Deduplication | When prices include spread/slip, deduct commission only once | Tier 1, 4 | 5 |
| **FEAT-06** | 120-Minute Timeout | Timeout strictly at $t_{\text{known}} + 7200\text{s}$, no fake timestamps | Tier 1, 2 | 5 |
| **FEAT-07** | Intrabar Adverse Selection | Adverse path resolution: limit before SL, indeterminate M1 adverse first | Tier 1, 3, 4 | 5 |
| **FEAT-08** | Boundary Limit Timing | Execution at $t_{\text{known}}$, $t_{\text{known}}+299\text{s}$, expiration at $t_{\text{known}}+300\text{s}$ | Tier 2 | 5 |
| **FEAT-09** | Fallback Delay Boundary | Quotes at delay $0\text{s}$, $59\text{s}$, $60\text{s}$ (pass) vs $61\text{s}$ (reject) | Tier 2 | 5 |
| **FEAT-10** | Spread / Slippage Extremes | Zero spread, micro spread, stress spread, extreme slippage | Tier 2 | 5 |
| **FEAT-11** | Prefix Replay Invariance | Truncating data after time $T$ does not alter trades executed before $T$ | Tier 2 | 5 |
| **FEAT-12** | Multi-Event State Machine | Limit fill immediate SL/TP, fallback fill same bar exit, single-position lock | Tier 3 | 4 |
| **FEAT-13** | Forensic Witness Replays | Replay exact cases: Signal #1, #3480, `short_false_tp`, `double_cost` | Tier 4 | 4 |

---

## 3. Test Architecture & Runner Design

### 3.1 Test Files Layout
- **`tests/test_causal_e2e_v2.py`**: The master executable test suite implemented using Python standard `unittest` framework. Contains modular test classes for Tiers 1 through 4.
- **`scripts/run_causal_e2e_tests.py`**: The test orchestration runner script. Provides CLI execution, tier filtering (`--tier 1,2,3,4` or `--all`), verbose logging, and structured JSON output for reporting.
- **`TEST_INFRA.md`**: Architectural definition and test inventory mapping (this document).
- **`TEST_READY.md`**: Operational readiness declaration, execution instructions, and test result summary.

### 3.2 Authoritative Expected Output Oracles
1. **Mathematical Reference Oracle**: Built into the test suite as an independent specification simulator (`ReferenceCausalOracle`), implementing pure mathematical rules from `ORIGINAL_REQUEST.md`.
2. **Audit Benchmark Oracle**: Extracted verbatim from `reports/can_ho_tro_agy_review/20261101/AUDIT_RESULTS.json` to verify failure witnesses.
3. **Invariance Oracle**: Built-in prefix replay harness comparing outputs under sliced vs complete input streams.

### 3.3 Test Execution Command
The test suite can be run either directly via standard Python `unittest`:
```powershell
python -m unittest tests/test_causal_e2e_v2.py -v
```
Or via the dedicated orchestration runner:
```powershell
python scripts/run_causal_e2e_tests.py --all --verbose
```

---

## 4. Coverage Thresholds & Quality Gates

| Gate Name | Metric | Required Threshold | Enforcement Action |
|---|---|---|---|
| **Tier 1 Coverage** | Tests per core feature | $\ge 5$ test cases | Hard Block if $< 5$ |
| **Tier 2 Boundary Coverage** | Tests per boundary feature | $\ge 5$ test cases | Hard Block if $< 5$ |
| **Tier 3 Integration Coverage** | Combined scenarios | $\ge 4$ test cases | Hard Block if $< 4$ |
| **Tier 4 Witness Coverage** | Audited witnesses | 100% of 4 witnesses | Hard Block if any omitted |
| **Zero-Lookahead Gate** | Early entry count | Strictly $0$ ($t_{\text{fill}} < t_{\text{known}}$) | Immediate Failure |
| **Sell TP Gate** | Short false TP count | Strictly $0$ ($\text{Ask}_{\text{low}} > \text{TP}$) | Immediate Failure |
| **Fee Double Deduction Gate**| Double count instances | Strictly $0$ | Immediate Failure |
| **Self-Containment** | External dependencies | Standard library + numpy only | Zero external packages |
