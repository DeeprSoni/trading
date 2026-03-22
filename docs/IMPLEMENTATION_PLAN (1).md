# Quant Trading System — Complete Codebase & Strategy Reference

**Purpose:** Full explanation of the existing codebase, strategies, architecture, and current results. Use this to understand the system end-to-end and identify improvements.

**Last updated:** 2026-03-22 | **Tests:** 242 passing | **Dashboard:** http://217.217.249.102:8501

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Capital Structure](#2-capital-structure)
3. [Iron Condor Strategy](#3-iron-condor-strategy)
4. [Calendar Spread Strategy](#4-calendar-spread-strategy)
5. [Adjustment Engines (v2)](#5-adjustment-engines-v2)
6. [Backtesting Architecture](#6-backtesting-architecture)
7. [Cost Engine](#7-cost-engine)
8. [Parameter Sweep](#8-parameter-sweep)
9. [Statistical Analysis](#9-statistical-analysis)
10. [Metrics Engine](#10-metrics-engine)
11. [Real Data Pipeline](#11-real-data-pipeline)
12. [Current Results (Baseline Sweep)](#12-current-results-baseline-sweep)
13. [Projected Metrics (After Re-Sweep)](#13-projected-metrics-after-re-sweep)
14. [What's Implemented vs What's Pending](#14-whats-implemented-vs-whats-pending)
15. [File Map](#15-file-map)
16. [Known Issues & Improvement Areas](#16-known-issues--improvement-areas)

---

## 1. System Overview

This is a quantitative options trading system for Indian markets (NSE F&O). It trades two strategies on Nifty 50:

- **Iron Condor (IC):** Sell OTM call + put credit spreads. Profits when the market stays in a range.
- **Calendar Spread (CAL):** Buy far-month ATM option, sell near-month ATM option. Profits from time decay differential.

The system backtests thousands of parameter combinations, ranks them, and provides statistical validation (bootstrap CI, Monte Carlo, walk-forward). A Streamlit dashboard shows all results.

**Tech stack:** Python 3.13, scipy (Black-Scholes), pandas, Streamlit, Plotly, SQLite, Kite Connect (Zerodha broker API).

**Directory:** `quant-system/` under the repo root.

---

## 2. Capital Structure

**File:** `config/settings.py`

Total capital: Rs 7,50,000. Split into deployed margin and yield-earning parked capital:

| Bucket | Amount | Yield | Annual Income |
|--------|--------|-------|---------------|
| Nifty Active (margin) | Rs 90,000 | Deployed | - |
| BankNifty Active (Phase 3) | Rs 70,000 | Deployed | - |
| FinNifty Active (Phase 3) | Rs 40,000 | Deployed | - |
| Liquid Fund | Rs 4,00,000 | 6.5% | Rs 26,000 |
| Arbitrage Fund | Rs 1,00,000 | 7.5% | Rs 7,500 |
| Cash Buffer | Rs 50,000 | 3.5% | Rs 1,750 |
| **Total** | **Rs 7,50,000** | | **Rs 35,250/yr** |

Phase 1 deploys only Nifty (Rs 90K active). Phase 3 adds BankNifty + FinNifty (Rs 2L total active). The Rs 5.5L parked capital earns 4.7% annually regardless of trading performance.

---

## 3. Iron Condor Strategy

**Files:** `src/strategy_ic.py` (live), `src/strategy_ic_backtest.py` (backtester adapter)

### What It Is

An Iron Condor sells an OTM call spread and an OTM put spread simultaneously. You collect premium upfront and profit if the market stays between your short strikes until expiry or until you close.

**Example trade on Nifty at 22,000:**
- Sell 22,500 CE (call) at Rs 80 — 16-delta
- Buy 23,000 CE (call) at Rs 30 — protection
- Sell 21,500 PE (put) at Rs 70 — 16-delta
- Buy 21,000 PE (put) at Rs 25 — protection
- Net credit collected: Rs 95/unit (80+70-30-25)
- Max loss: Rs 405/unit (500 wing width - 95 premium)
- Profit target: close when you can buy back for Rs 47.50 (50% of 95)

### Entry Gates

The strategy checks 6 conditions before entering. All must pass:

| # | Gate | Threshold | Rationale |
|---|------|-----------|-----------|
| 1 | IV Rank | >= 30 | Premium not worth selling below this |
| 2 | India VIX | <= 25 | Too volatile for credit spreads above this |
| 3 | DTE | 30-45 days | Sweet spot for theta decay |
| 4 | Open positions | < 2 | Diversification + margin control |
| 5 | No major event | within 25 days | Avoid earnings, RBI, budget |
| 6 | Account drawdown | < 5% | Kill switch |

**v2 relaxed gates** (in settings.py but NOT yet used in sweep):
- IV Rank lowered to 20 (from 30) — +40% more trade opportunities
- VIX: dynamic 3-tier instead of binary cutoff — standard (<=25), elevated (25-35 with wider wings + half size), killswitch (>40)
- Event blackout reduced to 7 days (from 25)
- Dynamic wing width by VIX level (400-900 pts instead of fixed 500)

### Exit Logic (Priority Order)

1. **Stop Loss:** Close cost >= 2x entry premium → IMMEDIATE exit
2. **Time Stop:** DTE <= 21 → exit by end of day
3. **Profit Target:** 50% of premium decayed → exit by end of day
4. **Expiry:** DTE <= 0 → forced close

### Backtest Adapter Parameters

The sweep engine overrides these for each combination:

```
short_delta: 0.16        (how far OTM — 16% probability ITM)
wing_width: 500          (protection spread in points)
min_dte: 30              (minimum days to expiry for entry)
max_dte: 45              (maximum days to expiry for entry)
min_iv_rank: 30          (minimum IV percentile)
max_vix: 25              (maximum India VIX for entry)
profit_target_pct: 0.50  (close at 50% profit)
stop_loss_multiplier: 2.0 (close at 2x premium loss)
time_stop_dte: 21        (close at 21 DTE)
max_open_positions: 2
lot_size: 25             (Nifty lot size)
min_premium: 50          (reject if net credit < Rs 50/unit)
```

### Adjustment Logic (in should_adjust)

Checked daily on open positions, in this order:

1. **DTE < 10:** Hard close — gamma risk too high to adjust
2. **Short call within 300 pts of spot:** Roll call spread 500 pts higher. If put side at 85%+ profit, harvest it.
3. **Short put within 300 pts of spot:** Roll put spread 500 pts lower. If call side at 85%+ profit, harvest it.
4. **v2 engine checks** (via `adjustments_ic.py`, skipping stop/profit/time which are handled by should_exit):
   - Wing removal (DTE <= 7, both wings < Rs 3)
   - Partial close winner (one side at 80%+ profit)
   - Roll untested inward (untested side at 80% profit)
   - Defensive roll (tested short delta >= 0.30)
   - Iron fly conversion (spot within 50 pts of short strike, DTE >= 12)

5-day cooldown after any exit before re-entering.

---

## 4. Calendar Spread Strategy

**Files:** `src/strategy_cal.py` (live), `src/strategy_cal_backtest.py` (backtester adapter)

### What It Is

A Calendar Spread buys a far-month ATM call and sells a near-month ATM call at the same strike. The near-month decays faster (theta), so the spread value increases if the market stays near the strike.

**Example trade on Nifty at 22,000:**
- Buy 22,000 CE expiring in 65 days at Rs 500
- Sell 22,000 CE expiring in 28 days at Rs 250
- Net debit: Rs 250/unit
- Profit comes from the front month decaying faster than the back month

### Entry Gates

| # | Gate | Threshold | Rationale |
|---|------|-----------|-----------|
| 1 | India VIX | <= 28 | Back month too expensive above this |
| 2 | No event | within 7 days | Avoid volatility crush |
| 3 | Open positions | < 2 | Capital management |
| 4 | Both expiries exist | Front 20-35 DTE + Back 60-75 DTE | Need the time differential |

Weekly Nifty expiries were discontinued by NSE in late 2024, so front month uses nearest monthly (20-35 DTE).

### Exit Logic

1. **Stop Loss:** Close cost >= entry debit * stop_loss_multiplier
2. **Time Stop:** Back month DTE <= back_month_close_dte (25)
3. **Profit Target:** Spread value gained >= 50% of entry debit
4. **4% move from strike:** Close everything
5. **Front month expiry:** Forced close

### Backtest Adapter Parameters

```
max_vix: 28
front_min_dte: 20, front_max_dte: 35
back_min_dte: 60, back_max_dte: 75
profit_target_pct: 0.50
back_month_close_dte: 25
move_pct_to_adjust: 0.02  (2% move → recentre)
move_pct_to_close: 0.04   (4% move → close)
front_roll_dte: 3          (roll front at 3 DTE)
front_profit_roll_pct: 0.50 (roll front at 50% decay)
iv_harvest_pct: 30         (close if back IV up 30%)
```

### Adjustment Logic (in should_adjust)

1. **IV Harvest:** Back month IV expanded 30%+ from entry → close entire position
2. **Front month roll at DTE <= 3:** Buy back current front, sell new front at same strike on next monthly expiry
3. **Front month roll at 50% decay:** Same as above, triggered by decay
4. **Recentre on 2% move:** Close old front, sell new ATM front
5. **v2 engine checks** (via `adjustments_cal.py`, skipping checks already handled above):
   - Early profit close (40%+ profit AND front DTE <= 15)
   - Diagonal conversion (1.5% move — sell OTM front instead of ATM, cheaper than full recentre)
   - Add second calendar (25%+ profit, market within 1% of entry, up to 2 secondary calendars at ±200 pts offset)

---

## 5. Adjustment Engines (v2)

**Files:** `src/adjustments_ic.py`, `src/adjustments_cal.py`

These are pure functions that take a position snapshot and return an adjustment enum. The strategy adapters build the position snapshot from the backtester's `Position` object, call the engine, and map the result back to an `AdjustmentDecision`.

### IC Adjustment Engine — 8 Types (Priority Order)

| # | Type | Trigger | Action |
|---|------|---------|--------|
| 1 | Emergency Stop | Value >= 2x credit | Close everything |
| 2 | Profit Target | 50%+ profit on IC | Close everything |
| 3 | Time Stop | DTE <= 21 | Close everything |
| 4 | Wing Removal | DTE <= 7, both wings < Rs 3 | Sell wings to free margin |
| 5 | Partial Close | One side at 80%+ profit | Close winning side only |
| 6 | Roll Untested | Untested side at 80% profit | Roll inward for fresh credit |
| 7 | Defensive Roll | Tested short delta >= 0.30 | Roll tested side further OTM |
| 8 | Iron Fly Conversion | Spot within 50 pts of short, DTE >= 12 | Convert to iron butterfly |

Note: In the adapter, checks 1-3 are disabled (set to impossible thresholds) because `should_exit` already handles stop loss, profit target, and time stop. Only checks 4-8 run through the v2 engine.

### CAL Adjustment Engine — 8 Types (Priority Order)

| # | Type | Trigger | Action |
|---|------|---------|--------|
| 1 | Close Large Move | Spot moved 4%+ from entry | Close everything |
| 2 | Close Back Near | Back month DTE <= 25 | Close everything |
| 3 | Early Profit Close | 40%+ profit AND front DTE <= 15 | Close (past theta peak) |
| 4 | IV Harvest Roll | Back month IV up 25%+ | Roll to next expiry |
| 5 | Front Roll | Front DTE <= 6 AND 60%+ decayed | Roll front to next monthly |
| 6 | Full Recentre | Spot moved 2%+ | Close old front, sell ATM front |
| 7 | Diagonal Convert | Spot moved 1.5%, not already diagonal | Sell OTM front instead |
| 8 | Add Second Calendar | 25%+ profit, market stable (<1% move) | Add legs at ±200 pts offset |

Note: In the adapter, checks 1-2 and 4-6 are disabled (handled by existing should_adjust logic). Only checks 3, 7, 8 run through the v2 engine.

---

## 6. Backtesting Architecture

**File:** `src/backtester.py`

### Daily Loop (per trading day)

```
For each day in market_states:
  1. EXIT CHECK: For each open position →
     strategy.should_exit(position, state)
     If True → _close_position() → TradeResult

  2. ADJUSTMENT CHECK: For each remaining open position →
     strategy.should_adjust(position, state)
     If True → _execute_adjustment() → update position legs

  3. ENTRY CHECK: If open_positions < max_open →
     strategy.should_enter(state)
     If True → strategy.generate_entry(state) → _open_position()

  4. REPRICE: For each open position →
     strategy.reprice_position(position, state)
     Track unrealised P&L, update peak equity, compute drawdown
```

### Position Model

Each position tracks: legs (list of Leg objects with strike, type, side, premium, expiry), lots, net_premium_per_unit, margin_required, adjustment_count, adjustment_costs, adjustment_history, and a metadata dict for strategy-specific state.

### Strategy Protocol

Any strategy adapter must implement:
- `name` (property) → e.g. "IC_d0.16_w500_pt50_sl2.0"
- `params` (property) → dict of current parameters
- `should_enter(state) → bool`
- `generate_entry(state) → EntryDecision`
- `should_exit(position, state) → ExitDecision`
- `should_adjust(position, state) → AdjustmentDecision`
- `reprice_position(position, state) → float`

---

## 7. Cost Engine

**File:** `src/cost_engine.py`

Every fee in Indian F&O trading is modelled:

| Fee | Rate | Applied To |
|-----|------|-----------|
| Brokerage | Rs 20/order | Both sides |
| STT | 0.0625% | Sell side premium |
| STT (ITM expiry) | 0.125% | Intrinsic value |
| Exchange (NSE) | 0.053% | Turnover, both sides |
| SEBI | 0.0001% | Turnover |
| Stamp Duty | 0.003% | Buy side |
| GST | 18% | On brokerage + exchange + SEBI |

**Slippage models** (how much worse your fill is vs mid-price):
- **Optimistic:** 50% of bid-ask spread
- **Realistic:** 75% of bid-ask spread
- **Conservative:** 100% of spread + Rs 1 extra per unit

---

## 8. Parameter Sweep

**Files:** `src/param_sweep.py`, `run_sweep.py`

### How It Works

1. Define a parameter grid (e.g. short_delta: [0.16, 0.20, 0.25])
2. Generate cartesian product of all combinations
3. For each combo × each slippage model: run full backtest
4. Rank results by metric (default: Sharpe ratio)
5. Filter by minimum trade count (default: 3)

### What Was Actually Swept (Baseline)

**IC grid** (3×3×3×3×3 = 243 combos × 3 slippage = 729 backtests):
- short_delta: [0.16, 0.20, 0.25]
- wing_width: [400, 500, 600]
- profit_target_pct: [0.40, 0.50, 0.65]
- stop_loss_multiplier: [1.5, 2.0, 2.5]
- time_stop_dte: [18, 21, 25]
- Fixed: min_iv_rank=30, max_vix=25

**CAL grid** (3×3×3×3×3 = 243 combos × 3 slippage = 729 backtests):
- move_pct_to_adjust: [0.015, 0.02, 0.025]
- move_pct_to_close: [0.03, 0.04, 0.05]
- profit_target_pct: [0.40, 0.50, 0.60]
- back_month_close_dte: [22, 25, 28]
- max_vix: [25, 28, 32]

**Combined** (375 blends): Top 5 IC × Top 5 CAL × 5 allocation splits (30/40/50/60/70% IC) × 3 slippage

### Synthetic Data Generation (in run_sweep.py)

The sweep uses synthetic option chains because NSE doesn't provide free historical strike-level data:

- Load real Nifty spot prices (Jun 2022 — Dec 2023, 400 trading days)
- Estimate VIX: `realized_vol * 1.55` (India VIX trades 30-50% above realized), floor 14%
- Generate 2 monthly expiries per day
- Build 21 strikes per expiry (ATM ± 1000 pts, 100-pt intervals)
- Price via Black-Scholes with vol skew: -0.25 skew, 0.20 smile
- Add OTM demand premium: +15% for options >2% OTM
- Add realistic bid-ask spread: 1.5% of price
- IV Rank: `min(max(vix * 2.5, 15), 85)`
- Seed: `np.random.seed(42)` for reproducibility

---

## 9. Statistical Analysis

**File:** `src/backtest_stats.py`

Applied to top 5 configs of each strategy after sweep:

| Method | What It Does |
|--------|-------------|
| **Bootstrap CI** | Resample trades 1000x, compute 95% confidence interval for Sharpe, P&L, win rate |
| **Monte Carlo** | Simulate 10,000 forward paths from trade distribution. Report P(profit), P(ruin), percentile P&Ls |
| **Walk-Forward** | K-fold split: train on fold N, test on fold N+1. Compare in-sample vs out-of-sample Sharpe |
| **Regime Analysis** | Break trades by market regime (HIGH_VOL, TRENDING, SIDEWAYS, NORMAL). Report per-regime win rate and avg P&L |

**Verdict logic:** STRONG (OOS Sharpe > 1.0 + high prob_profit) / MARGINAL / WEAK / INSUFFICIENT_DATA

---

## 10. Metrics Engine

**File:** `src/metrics.py`

Computes comprehensive metrics from backtest output:

**Returns:** annual return (total capital), annual return (active capital), total P&L, parked income, combined income, monthly income

**Risk:** Sharpe, Sortino, Calmar, max drawdown (% and Rs), avg drawdown, longest drawdown (days), annualized volatility

**Trades:** total, win rate, avg winner/loser, max winner/loser, profit factor, EV per trade, avg holding days

**Adjustments:** trades adjusted, adjustment rate %, avg adjustment cost, adjustment P&L improvement

**Capital:** capital efficiency %, margin utilisation %

The key insight: `combined_income = trading_pnl + parked_capital_yield`. Even with zero trading P&L, the system earns Rs 35,250/yr (4.7%) from parked capital.

---

## 11. Real Data Pipeline

**Files:** `src/data_fetcher_real.py`, `scripts/download_real_data.py`, `scripts/validate_data.py`

### Data Sources (all free, no API key needed)

| Source | Data | Method |
|--------|------|--------|
| NSE Archives | F&O bhavcopy (daily option prices) | HTTP GET, zip extract |
| NSE Archives | India VIX daily history | CSV download |
| Yahoo Finance | Nifty/BankNifty spot OHLC | yfinance library |

**URL for bhavcopy:** `https://archives.nseindia.com/archives/fo/bhav/fo{DDMMMYYYY}bhav.csv.zip`

### Status

The code is written and tested. The download script takes 2-4 hours (1,750 daily files at 1 req/sec). **Data has NOT been downloaded yet** — the baseline sweep used synthetic data.

Once downloaded, `run_sweep.py` can be modified to use `build_option_chain()` from `data_fetcher_real.py` instead of inline synthetic generation.

---

## 12. Current Results (Baseline Sweep)

**Data:** Synthetic chains, seed=42, 400 days, Jun 2022 — Dec 2023
**Ran with:** Old settings (IVR=30, VIX=25 cutoff, fixed wings)

### IC Best (by P&L, optimistic slippage)

| Metric | Value |
|--------|-------|
| Config | IC_d0.25_w400_pt50_sl2.5 |
| Net P&L | Rs 34,004 |
| Sharpe | -0.16 |
| Win Rate | 73.7% (14/19) |
| Max Drawdown | 3.9% |
| Trades | 19 |
| Avg Hold | 7.2 days |
| Adjustments | 14/19 trades adjusted (15 total) |
| Adj Costs | Rs 15,000 |
| Adj P&L | -Rs 20,000 |

### CAL Best (5+ trades, optimistic)

| Metric | Value |
|--------|-------|
| Net P&L | Rs 154,118 |
| Trades | 15 |
| Config | PT=40%/adj=1%/close=3% |

### Combined Best (by Sharpe, optimistic)

| Metric | Value |
|--------|-------|
| Config | IC70/CAL30 split |
| Net P&L | Rs 70,038 |
| Combined Income | Rs 105,288 (trading + parked) |
| Sharpe | 1.97 |
| Annual Return | 5.9% |
| Win Rate | 71% |
| Max Drawdown | 1.8% |
| Trades | 34 |

**Key finding:** All 375 combined configurations are profitable across all 3 slippage models.

---

## 13. Projected Metrics (After Re-Sweep)

These are conservative targets based on the v2 code changes (relaxed gates, better adjustments, multi-underlying):

| Phase | ROI Total | ROI Active | Sharpe | Max DD | Win Rate | Trades/yr | Monthly Rs |
|-------|-----------|-----------|--------|--------|----------|-----------|------------|
| Baseline (current) | 5.9% | 11.5% | 1.97 | 1.8% | 71% | 34 | 3,688 |
| Phase 1 — gates relaxed | 8.5% | 13.0% | 1.85 | 3.2% | 72% | 55 | 5,313 |
| Phase 2 — v2 adjustments | 11.5% | 16.0% | 2.10 | 4.5% | 78% | 60 | 7,188 |
| Phase 3 — BankNifty added | 15.5% | 19.5% | 2.05 | 7.0% | 75% | 90 | 9,688 |
| Phase 4 — compounding (yr 2) | 18.0% | 21.0% | 2.00 | 7.5% | 75% | 100 | 11,250 |

- ROI Total = (trading P&L + parked yield) / Rs 7,50,000
- ROI Active = trading P&L / deployed capital only
- Phase 1 Sharpe drops slightly (more trades = noisier equity curve)
- Phase 3 drawdown jumps (BankNifty has 5% single-day moves)
- Phase 4 assumes 12% account growth compounded into larger positions

### Risk Assumptions

- Entry/exit slippage: 75% of bid-ask spread
- Adjustment slippage: 150% of spread (moving against you)
- Event day slippage: 200% of spread (liquidity withdrawal)
- Tax on trading profits: 20% short-term capital gains
- After-tax Phase 2 return: ~9.5% on total capital

---

## 14. What's Implemented vs What's Pending

### Implemented (in code, tested)

- [x] Capital restructure (Rs 5.5L earning yield)
- [x] IC gates relaxed (IVR 20, VIX dynamic, events 7 days, dynamic wings)
- [x] IC adjustment engine v2 (8 types) — wired into strategy_ic_backtest.py
- [x] CAL adjustment engine v2 (8 types) — wired into strategy_cal_backtest.py
- [x] Multi-underlying config (NIFTY/BANKNIFTY/FINNIFTY)
- [x] Metrics engine (parked income, capital efficiency)
- [x] Real data pipeline (data_fetcher_real.py, download/validate scripts)
- [x] find_iv_from_price() wrapper in iv_calculator.py
- [x] 242 tests passing
- [x] Dashboard v2 deployed on VPS

### Pending (needs execution)

- [ ] **Download real NSE data** — run `python scripts/download_real_data.py` (2-4 hours)
- [ ] **Validate data** — run `python scripts/validate_data.py`
- [ ] **Re-run sweep with v2 settings** — the current sweep used old IVR=30/VIX=25/fixed wings. Need to re-sweep with IVR=20/dynamic VIX/dynamic wings
- [ ] **Re-run sweep with real data** — replace synthetic chain generation in run_sweep.py with data_fetcher_real.build_option_chain()
- [ ] **BankNifty sweep** — add BankNifty to param_sweep.py grids
- [ ] **Broker integration** — Kite Connect order placement, position monitoring
- [ ] **Telegram alerts** — IMMEDIATE/TODAY/MONITOR alert levels
- [ ] **CLI commands** — morning-review, login, execute-trade, portfolio (skeleton exists in cli/commands.py)
- [ ] **Paper trading** — validate with live market data before deploying capital

---

## 15. File Map

```
quant-system/
├── src/
│   ├── iv_calculator.py          # Black-Scholes, Greeks, IV rank, find_iv_from_price
│   ├── data_fetcher.py           # Kite Connect live data (Zerodha API)
│   ├── data_fetcher_real.py      # Real NSE bhavcopy + yfinance (NEW)
│   ├── synthetic_data_generator.py # Synthetic chains for backtesting (DEPRECATED)
│   ├── strategy_ic.py            # IC entry gates, exit logic, trade structure
│   ├── strategy_cal.py           # CAL entry gates, roll/adjust logic
│   ├── strategy_ic_backtest.py   # IC adapter for backtester (parameterised)
│   ├── strategy_cal_backtest.py  # CAL adapter for backtester (parameterised)
│   ├── adjustments_ic.py         # IC v2 adjustment engine (8 types) (NEW)
│   ├── adjustments_cal.py        # CAL v2 adjustment engine (8 types) (NEW)
│   ├── backtester.py             # Generic day-by-day simulator
│   ├── param_sweep.py            # Cartesian grid + parallel execution
│   ├── backtest_stats.py         # Bootstrap, Monte Carlo, walk-forward
│   ├── cost_engine.py            # Full Indian F&O fee schedule
│   ├── metrics.py                # Comprehensive metrics computation (NEW)
│   ├── models.py                 # Leg, Position, MarketState, EntryDecision, etc.
│   ├── strategy_protocol.py      # BacktestStrategy protocol interface
│   └── exceptions.py             # Custom errors
├── config/
│   ├── settings.py               # All parameters, capital, gates, costs
│   ├── strategy_params.py        # Pre-defined param sets
│   ├── underlyings.py            # NIFTY/BANKNIFTY/FINNIFTY config (NEW)
│   └── events_calendar.json      # Economic events for gating
├── scripts/
│   ├── download_real_data.py     # One-time NSE data download (NEW)
│   └── validate_data.py          # Data integrity check (NEW)
├── tests/                        # 242 tests across 17 files
├── data/sweep_results/           # Pre-computed backtest JSON
├── dashboard.py                  # Streamlit UI
├── run_sweep.py                  # Sweep orchestrator
├── cli.py                        # CLI entry point
├── db/                           # SQLAlchemy models + CRUD
├── alembic/                      # DB migrations
└── requirements.txt              # 24 dependencies
```

---

## 16. Known Issues & Improvement Areas

### Data Quality
- **Synthetic data is approximate.** Real NSE bhavcopy would give actual historical option prices instead of Black-Scholes estimates. Download is ready but not executed.
- **VIX calibration is heuristic.** `realized_vol * 1.55` with 14% floor — real VIX data from NSE would be more accurate.
- **No intraday data.** Backtester uses EOD prices only. Real stop losses would trigger intraday.

### Strategy Improvements
- **IC Sharpe is negative (-0.16).** The best IC config alone isn't great — it only works well in the combined portfolio with CAL.
- **Adjustment costs hurt IC.** 14/19 trades adjusted with Rs 15k cost and -Rs 20k P&L impact. The v2 adjustment engine may help but hasn't been sweep-tested yet.
- **CAL has few trades.** Only 15 trades in 400 days due to monthly-only expiries. Expanding to BankNifty (which has weekly expiries) would increase opportunities.
- **No regime-aware entry.** The system doesn't vary strategy based on market regime (trending vs sideways). Adding regime detection could improve timing.

### Architecture
- **Sweep doesn't use v2 gates.** The baseline sweep used IVR=30/VIX=25 — need to re-sweep with v2 settings (IVR=20, dynamic VIX, dynamic wings).
- **No walk-forward parameter selection.** Current approach: pick best Sharpe from in-sample. Better: pick parameters that are robust out-of-sample.
- **Backtester is single-threaded per config.** The sweep parallelises across configs, but each backtest is sequential. Not a bottleneck currently (729 backtests in 10 seconds).

### Operational
- **No broker integration.** Kite Connect code exists but live order placement is not implemented.
- **Dashboard doesn't auto-refresh.** Shows pre-computed JSON results. No live position tracking.
- **VPS needs manual redeploy.** No CI/CD — git pull + restart systemd manually.
