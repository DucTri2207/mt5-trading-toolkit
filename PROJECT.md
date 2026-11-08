# Project: Cản Hỗ Trợ Indicator Upgrade & Causal Simulation Overhaul (Run 20261101_agy_lab_v2)

## Architecture
- **Target Indicator**: `duc_tri_can_ho_tro_agy_lab.mq5` and compiled `.ex5` in `duc_tri_can_ho_tro_agy_lab/`.
- **Baseline Source**: `duc_tri_can_ho_tro.mq5` (v3.01, 124,092 bytes, SHA-256: `5a244553a7e659fb50c78481294531e38b9e60d1d1c0b11adbc26db7c7226405`).
- **Core Methodology**: Ponytail Principle (Lazy Senior Dev Mode) — smallest complete change, zero redundant wrappers or boilerplate.
- **Verification Engine**: Causal, bitwise, strictly leak-free simulation engine (`scripts/gold_v301_causal_core.py`).
- **Delivery Path**: `reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/` (preserving baseline and previous run artifacts).

```
                  ┌─────────────────────────────────────────────────────────┐
                  │              duc_tri_can_ho_tro_agy_lab.mq5             │
                  │  - ENUM_LAB_MODE: COMPAT / TECHNICAL / EXP              │
                  │  - Telemetry: H1 Zone, Dist/ATR, Room R, Spread, Lag    │
                  │  - Decoupled Candidate Detector vs Plan Display         │
                  │  - Conditional H2 Entry (ONLY if acceptance met)        │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │            scripts/gold_v301_causal_core.py             │
                  │  - Strict Causal Separation: 6 timestamps (t0 fixed)    │
                  │  - LIMIT Window: [signal_known, signal_known + 300s)    │
                  │  - MARKET_FALLBACK: quote >= deadline, max delay 60s    │
                  │  - Real-time Intrabar Replay: order of entry -> SL/TP   │
                  │  - Exact Bid/Ask matching (BUY Ask/Bid, SELL Bid/Ask)   │
                  │  - Fee Accounting: no double-counting of spread/slip    │
                  │  - B0, B1, H1, H2 on full historical snapshot           │
                  └────────────────────────────┬────────────────────────────┘
                                               │
                                               ▼
                  ┌─────────────────────────────────────────────────────────┐
                  │    Evaluation Ledgers & Statistical Verification        │
                  │  - SIGNALS_*.csv (24 cols), TRADES_*.csv (19 cols)      │
                  │  - Retention: N_alert >= 100%, N_fill >= 100%           │
                  │  - Bootstrap 95% CI on Delta Expectancy                 │
                  │  - REPORT.md, MANIFEST.json, PROTOCOL.json              │
                  │  - Independent Audit & Parity Verification              │
                  └─────────────────────────────────────────────────────────┘
```

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Baseline Preservation & Run Setup | Preserve baseline and previous run; establish `reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/` | M1 | R1 |
| 2 | Cache Integrity & Hash Verification | Verify hashes of detector, dataset, and configuration; force regeneration on modification | M1 | R1 |
| 3 | Causal Time Separation | Explicitly separate `confirm_bar_open`, `signal_known_time`, `publish_time`, `order_place_time`, `fill_time`, `exit_time` | M1 | R2 |
| 4 | M5 Confirmation Close Enforcement | Signal known strictly after confirmation bar close (`signal_known_time = confirm_bar_open + 300s`) | M1 | R2 |
| 5 | Strict LIMIT Execution Window | LIMIT orders matched strictly within `[signal_known_time, signal_known_time + 300s)` | M1 | R2 |
| 6 | MARKET_FALLBACK Quote Validation | Fallback activates at first quote >= deadline, max delay 60s; log execution error if delay > 60s, never gap future quotes | M1 | R2 |
| 7 | Causal Assertion & Timeout Verification | Assertions against premature fill/fallback/exit; 120-minute payoff timeout from `signal_known_time`; prefix replay check | M1 | R2 |
| 8 | Chronological Intrabar Replay | Correct witness BUY limit (touch limit before SL -> fill then SL); adverse selection for indeterminate M1 paths | M1 | R3 |
| 9 | Immediate Post-Fill Exit Replay | Exit replay starts immediately post-fill in remaining bar/minute; eliminate fake `bar_time + 120` timestamps | M1 | R3 |
| 10 | Order Lifecycle State Scheduler | Real-time state machine (pending, filled, cancelled, expired, exit) with unfill reason and entry classification | M1 | R3 |
| 11 | Bid/Ask Side Matching | BUY on Ask in, Bid out; SELL on Bid in, Ask out | M1 | R4 |
| 12 | Short Exit & TP Verification | SELL SL/TP checked strictly against Ask price (`short_false_tp` fix) | M1 | R4 |
| 13 | Consistent Fee Accounting | Eliminate double deduction: if execution price incorporates spread/slippage, do not deduct again in cash/R P&L | M1 | R4 |
| 14 | Independent Python vs MT5 B0 Parity | Automated parity test proving 100% exact alert match between Python B0 and MT5 COMPAT mode | M2 | R5 |
| 15 | Python vs MT5 B1 Causal Guard Parity | Synchronize causal guards between Python B1 and MT5 TECHNICAL mode (H1 zone formation time, sweep causal check) | M2 | R5 |
| 16 | Full Historical Simulation Execution | Run B0, B1, H1, H2 on full snapshot (2021-2026) with distinct reporting for complete calendar years 2022–2025 | M3 | R5 |
| 17 | Trade Retention Gate Evaluation | Strictly evaluate $N_{alert\_new} \ge N_{alert\_baseline}$ and $N_{fill\_new} \ge N_{fill\_baseline}$ for full window and annual | M3 | R5 |
| 18 | Economic Criteria & Drawdown Audit | Evaluate Expectancy BASE >= +0.05R, PF >= 1.20, STRESS > 0, PF > 1.00, and floating equity MaxDD <= baseline | M3 | R5 |
| 19 | Statistical Bootstrap & Confidence Intervals | 10,000-iteration monthly block bootstrap reporting 95% CI on Delta Expectancy vs baseline | M3 | R5 |
| 20 | Conditional MQL5 Integration Decision | Apply Ponytail: integrate H2 into `duc_tri_can_ho_tro_agy_lab.mq5` IF AND ONLY IF all economic & retention criteria met | M4 | R6 |
| 21 | Clean MQL5 Compilation | Compile indicator clean without warnings/errors via `MetaEditor64.exe` CLI | M4 | R6 |
| 22 | Delivery Package Assembly | Generate `REPORT.md`, `MANIFEST.json`, `PROTOCOL.json`, `CODE_DIFF.patch`, `EXPERIMENT_REGISTRY.json`, `VERIFICATION.json` | M5 | R6 |
| 23 | Standardized Ledger Generation | Export 24-col `SIGNALS_*.csv`, 19-col `TRADES_*.csv`, `EQUITY_*.csv`, `FREQUENCY.csv`, `MATCHED_EVENTS.csv` | M5 | R6 |
| 24 | Error-Fix-Witness Comparison Report | Comprehensive documentation of error -> fix -> witness before/after validation | M5 | R6 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Independent opaque-box test runner & multi-tier test suite (Tiers 1-4) derived from requirements | none | DONE |
| M1 | Causal Simulation Engine Overhaul | Features 1–13. Fix t0 lookahead, LIMIT window, Fallback quotes, intrabar replay, Bid/Ask matching, fee deduplication | none | DONE |
| M2 | Python vs MT5 Parity Verification | Features 14–15. B0 100% alert identity, B1 causal guard synchronization and parity proof | M1 | DONE |
| M3 | Master Re-experimentation & Statistics | Features 16–19. Full dataset runs (2021-2026, 2022-2025 annual), retention check, economic evaluation, bootstrap CI | M1, M2 | DONE |
| M4 | Conditional MQL5 Integration | Features 20–21. Ponytail evaluation: integrate H2 into MQL5 if criteria met; compile clean with MetaEditor64 | M3 | DONE |
| M5 | Delivery Package & Audit Gate | Features 22–24. Standardized ledgers, reports, diff patch, manifests, third-party reproducibility, forensic audit | M4, E2E | DONE |

## Interface Contracts
### Simulation Engine (`scripts/gold_v301_causal_core.py`) ↔ Experiment Runner (`scripts/run_can_ho_tro_lab_experiments.py`)
- **Signal Contract**: `time_m5`, `confirm_bar_open`, `signal_known_time`, `publish_time`, `order_place_time`, `direction`, `entry_price`, `sl_price`, `tp_price`, `risk`, `choch_level`, `source_zone_id`, `source_zone_type`, `room_net_R`.
- **Execution Contract**: `fill_time`, `fill_price`, `entry_type` (LIMIT/MARKET_FALLBACK/MARKET), `exit_time`, `exit_price`, `exit_reason` (TP/SL/TIMEOUT), `gross_pnl_usd`, `commission_usd`, `slippage_usd`, `spread_cost_usd`, `net_pnl_usd`, `net_r`, `bars_held`.
- **Enforced Assertions**:
  1. `fill_time >= signal_known_time` and `fill_time >= order_place_time`.
  2. For LIMIT: `signal_known_time <= fill_time < signal_known_time + 300s`.
  3. For FALLBACK: `fill_time >= signal_known_time + 300s` and `fill_time - (signal_known_time + 300s) <= 60s`.
  4. `exit_time >= fill_time`.
  5. Fee: `net_pnl_usd = gross_pnl_usd - commission_usd` (when gross P&L is computed from exact execution prices including spread and slippage).

### MQL5 Lab Indicator (`duc_tri_can_ho_tro_agy_lab.mq5`) ↔ Parity Verifier
- **Modes**:
  - `LAB_MODE_COMPAT` = 0 (100% exact baseline B0 replication).
  - `LAB_MODE_TECHNICAL` = 1 (B1 with float bug, zone tracking, and decoupling fixes).
  - `LAB_MODE_EXP` = 2 (Enables H1 multi-zone ranking and, if approved, H2 retest logic).

## Code Layout
- `duc_tri_can_ho_tro.mq5`: Baseline unmodified file (v3.01, SHA256: `5a244553...`)
- `duc_tri_can_ho_tro_agy_lab/`: Dedicated directory for the upgraded indicator
  - `duc_tri_can_ho_tro_agy_lab.mq5`: Ponytail lab indicator source
  - `duc_tri_can_ho_tro_agy_lab.ex5`: Compiled binary via MetaEditor64
- `scripts/`: Test harness and simulation scripts
  - `gold_v301_causal_core.py`: Overhauled causal simulation engine
  - `run_can_ho_tro_lab_experiments.py`: Master experiment and ledger generation script
  - `verify_can_ho_tro_lab.py`: Comprehensive verification and bootstrap test harness
- `reports/can_ho_tro_agy_upgrade/20261101_agy_lab_v2/`: Official delivery package
  - `REPORT.md`: Comprehensive final report with mandatory summary table & witness comparisons
  - `MANIFEST.json`: Hashes, sizes, and paths of all delivery artifacts
  - `PROTOCOL.json`: Formal pre-registered experiment protocol
  - `CODE_DIFF.patch`: Unified diff between baseline and lab version
  - `SIGNALS_*.csv`: 24-column signals ledger for each branch
  - `TRADES_*.csv`: 19-column trades ledger for each branch
  - `EQUITY_*.csv`: Daily equity curves
  - `MATCHED_EVENTS.csv`: Event-by-event comparison between branches
  - `FREQUENCY.csv`: Annual, monthly, weekly trade distribution
  - `EXPERIMENT_REGISTRY.json`: Run parameters and configuration
  - `VERIFICATION.json`: Verification and test passing records
