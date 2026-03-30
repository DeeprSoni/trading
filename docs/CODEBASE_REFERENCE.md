# Quant Trading System — Complete Codebase Reference

**Copy-paste this into Claude to get full context for improvements.**

**Last verified:** 2026-03-30 | **309 tests passing** | **7,428 LOC across 23 modules**
**Dashboard:** http://217.217.249.102:8501 | **Repo:** git@github.com:DeeprSoni/trading.git

---

## 1. What This System Does

Quantitative options trading on NSE (India). Trades Nifty 50 and BankNifty using 5 strategies:

| Strategy | Type | Legs | How It Profits |
|----------|------|------|----------------|
| **Iron Condor (IC)** | Credit | 4 | Sells OTM call+put spreads. Profits if market stays in range. |
| **Calendar Spread (CAL)** | Debit | 2 | Buys far-month, sells near-month ATM. Profits from theta differential. |
| **Broken Wing Butterfly (BWB)** | Credit | 5 | Asymmetric IC — sells 2x puts, buys 1x. Extra credit, free downside zone. |
| **Strangle-to-IC** | Credit→IC | 2→4 | Naked strangle in high VIX, converts to IC after 30% profit. |
| **VIX Spike Calendar** | Debit | 2 | Calendar on VIX spike (20→25 in 3 days). Profits on VIX mean-reversion. |

The system backtests thousands of parameter combinations, ranks by Sharpe, validates with bootstrap/Monte Carlo/walk-forward, and shows results on a Streamlit dashboard.

---

## 2. Capital Structure

Total: Rs 7,50,000

| Bucket | Amount | Yield | Annual |
|--------|--------|-------|--------|
| Nifty Active (margin) | Rs 90,000 | Deployed | - |
| BankNifty Active (Phase 3) | Rs 70,000 | Deployed | - |
| FinNifty Active (Phase 3) | Rs 40,000 | Deployed | - |
| Liquid Fund | Rs 4,00,000 | 6.5% | Rs 26,000 |
| Arbitrage Fund | Rs 1,00,000 | 7.5% | Rs 7,500 |
| Cash Buffer | Rs 50,000 | 3.5% | Rs 1,750 |
| **Total parked income** | | | **Rs 35,250/yr** |

Phase 1: only Nifty (Rs 90K active). Phase 3: all three (Rs 2L active).

---

## 3. Iron Condor Strategy

**Files:** `src/strategy_ic.py`, `src/strategy_ic_backtest.py`

### Entry Gates

| Gate | Threshold | Notes |
|------|-----------|-------|
| IV Rank | >= 20 | Was 30 pre-v3 |
| VIX | <= 25 standard, 25-35 elevated (wider wings + half size), >40 killswitch | Was binary <=25 |
| DTE | 30-45 days | Sweet spot for theta |
| Open positions | < 2 | Capital management |
| Event blackout | 7 days | Was 25 days pre-v3 |
| Account drawdown | < 5% | Kill switch |

### Dynamic Sizing (v2)

| VIX Range | Wing Width | Position Size |
|-----------|-----------|---------------|
| 0-15 | 400 pts | 100% |
| 15-20 | 500 pts | 100% |
| 20-25 | 600 pts | 100% |
| 25-30 | 700 pts | 75% |
| 30-35 | 800 pts | 50% |
| 35+ | 900 pts | 25% |

### Trade Structure

- Short call: 16-delta call (SELL)
- Short put: 16-delta put (SELL)
- Long call: short_call + wing_width (BUY)
- Long put: short_put - wing_width (BUY)
- Net credit must be > Rs 50/unit
- Max loss per lot must be < 5% of capital
- Lot size: 75 (Nifty)

### Exit Logic (priority order in should_exit)

1. **Stop Loss:** close_cost >= 2x entry_premium → IMMEDIATE
2. **Time Stop:** DTE <= 21 → exit (but if profitable and not yet rolled, defers to should_adjust for roll-for-duration)
3. **Profit Target:** 50% of premium decayed → exit
4. **Expiry:** DTE <= 0 → forced close

### Re-entry Cooldown (v3)

| Exit Reason | Cooldown |
|-------------|----------|
| PROFIT_TARGET | 2 days |
| STOP_LOSS | 7 days |
| TIME_STOP | 1 day |
| Default | 2 days |

### Adjustment Logic (v2 engine, all handled by adjustments_ic.py)

Priority order in should_adjust:
1. **DTE < 10:** Hard close (gamma risk — before v2 engine)
2. Then v2 engine checks (stop/profit/time disabled since should_exit handles them):
   - **Wing Removal:** DTE <= 7, both wings < Rs 3 → sell wings to free margin
   - **Partial Close:** One side at 80%+ profit → close winning side only
   - **Roll Untested:** Untested side at 80% profit → roll inward for credit
   - **Defensive Roll:** Tested short delta >= 0.30 → roll further OTM
   - **Iron Fly Conversion:** Spot within 50 pts of short, DTE >= 12

### Regime-Aware Delta Skew (v3)

`detect_regime(spot_history)` → BULLISH / BEARISH / NEUTRAL

| Regime | Call Delta | Put Delta | Rationale |
|--------|-----------|-----------|-----------|
| BULLISH | 0.12 | 0.22 | Tighter call, wider put — collect more on safe side |
| BEARISH | 0.22 | 0.12 | Reversed |
| NEUTRAL | 0.16 | 0.16 | Symmetric |

### Roll for Duration (v3)

If at TIME_STOP (DTE <= 21) AND position is profitable AND not yet rolled:
- Don't exit — let should_adjust handle ROLL_FOR_DURATION
- Close current legs, open new at next monthly expiry
- Max 1 roll per position

### Backtest Parameters (sweep grid)

```
short_delta:          [0.16, 0.20, 0.25]
wing_width:           [400, 500, 600, 700, 800]
profit_target_pct:    [0.40, 0.50, 0.65]
stop_loss_multiplier: [1.5, 2.0, 2.5]
time_stop_dte:        [18, 21, 25]
min_iv_rank:          [20, 25, 30]
→ 2,025 combos × 3 slippage = 6,075 backtests
```

---

## 4. Calendar Spread Strategy

**Files:** `src/strategy_cal.py`, `src/strategy_cal_backtest.py`

### Entry Gates

| Gate | Threshold |
|------|-----------|
| VIX | <= 28 |
| Event blackout | 7 days |
| Open positions | < 2 |
| Front month DTE | 20-35 (monthly, weeklies discontinued) |
| Back month DTE | 60-75 |

### Trade Structure

- ATM strike (rounded to nearest 100)
- BUY back-month ATM call (60-75 DTE)
- SELL front-month ATM call (20-35 DTE)
- Net debit = back_cost - front_premium

### Adjustment Logic

Kept in adapter: IV Harvest (back IV +30% → close), Recentre (2% move)

Via v2 engine (adjustments_cal.py):
- **Front Roll:** DTE <= 6 AND 60%+ decayed → roll to next monthly
- **Early Profit Close:** 40%+ profit AND front DTE <= 15
- **Diagonal Convert:** 1.5% move, not already diagonal → sell OTM front
- **Add Second Calendar:** 25%+ profit, market within 1% → add at ±200 pts offset

### Sweep Grid

```
move_pct_to_adjust:   [0.015, 0.02, 0.025]
move_pct_to_close:    [0.03, 0.04, 0.05]
profit_target_pct:    [0.40, 0.50, 0.60]
back_month_close_dte: [22, 25, 28]
max_vix:              [25, 28, 32]
→ 243 combos × 3 slippage = 729 backtests
```

---

## 5. Broken Wing Butterfly (v3)

**File:** `src/strategy_bwb.py`

Same entry gates as IC. Structure:
- Call side: standard 1x1 spread (same as IC)
- Put side: sell 2x short puts at 16-delta, buy 1x long put at ATM - 1000 pts
- Extra credit from second short put
- Stop loss: 1.5x (tighter than IC's 2x — no free wing protection on one side)
- 5 legs total

---

## 6. Strangle-to-IC Conversion (v3)

**File:** `src/strategy_strangle.py`

Entry: VIX 28-35, IVR >= 35, DTE 30-45, max 1 position. Starts as naked 2-leg strangle.

Conversion triggers:
- 30% profit → buy 500-pt wings (becomes IC, stop changes to 2.0x)
- 2% spot move → emergency wing buy

Pre-conversion stop: 1.0x. Post-conversion: 2.0x.

---

## 7. VIX Spike Calendar (v3)

**File:** `src/strategy_vix_cal.py`

Entry: VIX spikes from <20 to >25 within 3 trading days. Tracks VIX history internally.

Exit: VIX drops below 18 (mean-reverted) OR 35% profit OR 4% move OR back DTE <= 25.

No adjustments — hold or close. Max 1 position. Hedge trade.

---

## 8. Backtesting Architecture

**File:** `src/backtester.py` (468 lines)

Daily loop:
```
For each day:
  1. EXIT CHECK → strategy.should_exit(position, state) → close if True
  2. ADJUSTMENT CHECK → strategy.should_adjust(position, state) → update legs if True
  3. ENTRY CHECK → strategy.should_enter(state) → open if True
  4. REPRICE → strategy.reprice_position(position, state) → track drawdown
```

All strategies implement `BacktestStrategy` protocol (src/strategy_protocol.py):
- `name`, `params` (properties)
- `should_enter(state) → bool`
- `generate_entry(state) → EntryDecision`
- `should_exit(position, state) → ExitDecision`
- `should_adjust(position, state) → AdjustmentDecision`
- `reprice_position(position, state) → float`

---

## 9. Cost Engine

**File:** `src/cost_engine.py` (356 lines)

Indian F&O fees (FY 2024-25):

| Fee | Rate |
|-----|------|
| Brokerage | Rs 20/order |
| STT (sell) | 0.0625% |
| STT (ITM expiry) | 0.125% of intrinsic |
| Exchange | 0.053% |
| SEBI | 0.0001% |
| Stamp Duty (buy) | 0.003% |
| GST | 18% on brokerage+exchange+SEBI |

Slippage: Optimistic (50% spread), Realistic (75%), Conservative (100% + Rs 1).

---

## 10. Data Pipeline

**File:** `src/data_fetcher_real.py` (333 lines)

### Real Data (NSE UDiFF format, 2024+)

URL: `https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip`

**Currently cached:** 247 trading days of 2024, 593 MB, 1M+ option records

Functions:
- `fetch_fo_bhavcopy(date)` → DataFrame (cached as parquet)
- `fetch_fo_date_range(start, end, symbols)` → combined DataFrame
- `fetch_india_vix()` → VIX history (URL currently 404 — VIX estimated from spot vol)
- `fetch_nifty_spot(start, end, symbol)` → spot OHLC via yfinance
- `build_option_chain(bhavcopy, date, symbol)` → chain for backtester
- `add_implied_volatility(chain, spot)` → adds IV column via BS solver

UDiFF columns normalized to legacy: TckrSymb→SYMBOL, StrkPric→STRIKE_PR, etc.

### Synthetic Data (deprecated, still used for old sweep)

**File:** `src/synthetic_data_generator.py` — BS pricing with vol skew on real spot prices. Seed=42.

---

## 11. Parameter Sweep

**File:** `src/param_sweep.py` (292 lines), `run_sweep.py`

CLI: `python run_sweep.py --use-real-data --strategy IC --underlying NIFTY`

Flags: `--use-real-data`, `--strategy {IC,CAL,COMBINED,ALL}`, `--underlying {NIFTY,BANKNIFTY}`

BankNifty sweep grid: delta [0.20-0.30], wings [600-1000], lot_size=30.

---

## 12. Statistical Analysis

**File:** `src/backtest_stats.py` (449 lines)

| Method | Detail |
|--------|--------|
| Bootstrap CI | 1000 resamples, 95% CI for Sharpe/P&L/WR |
| Monte Carlo | 10,000 paths, P(profit), P(ruin), percentiles |
| Walk-Forward | K-fold, IS vs OOS Sharpe, degradation % |
| Regime Analysis | Per-regime (HIGH_VOL/TRENDING/SIDEWAYS/NORMAL) stats |
| Robust Selection | `select_robust_params()` — picks params with positive OOS Sharpe in >=80% folds, OOS >= 70% of IS, lowest drawdown |

---

## 13. Metrics Engine

**File:** `src/metrics.py` (201 lines)

`compute_metrics(daily_pnl, trade_pnls, total_capital, active_capital, ...)` → StrategyMetrics

Includes parked capital income in combined returns. Capital efficiency %. Adjustment rate and P&L impact.

---

## 14. Operational Infrastructure

### Telegram Alerts (`src/alerts.py`)

3 levels: `send_immediate()` (stop loss), `send_today()` (entry signal), `send_monitor()` (EOD summary).

### CLI (`cli/commands.py`)

11 commands: morning_review, login, backtest, execute_trade, close_position, portfolio, edge_report, ask, paper_entry, paper_exit, paper_summary.

### Database (`db/models.py`)

7 models: Trade, CalendarCycle, EdgeMetric, OrderLog, ZerodhaSession, AlertLog, PaperTrade.
2 alembic migrations.

### Dashboard (`dashboard.py`)

7 pages: Live Market, Overview, Iron Condor, Calendar Spread, Combined IC+CAL, Risk & Statistics, Trade Explorer.

Deployed on VPS (217.217.249.102:8501) via systemd.

---

## 15. Current Baseline Results (synthetic, seed=42, 400 days)

| Strategy | Config | Net P&L | Sharpe | WR | Max DD | Trades |
|----------|--------|---------|--------|-----|--------|--------|
| IC Best | IC_d0.25_w400_pt50_sl2.5 | Rs 34,004 | -0.16 | 74% | 3.9% | 19 |
| CAL Best | PT=40%/adj=1%/cls=3% | Rs 154,118 | — | — | — | 15 |
| Combined | IC70/CAL30 | Rs 70,038 | 1.97 | 71% | 1.8% | 34 |

All 375 combined configs profitable across all slippage models.

**Note:** These results used old settings (IVR=30, VIX=25 binary, lot_size=25, old adjustment logic). Re-sweep with v3 settings + real 2024 data is pending.

---

## 16. Projected Metrics (after re-sweep)

| Phase | ROI Total | Sharpe | Max DD | Trades/yr | Monthly Rs |
|-------|-----------|--------|--------|-----------|------------|
| Baseline | 5.9% | 1.97 | 1.8% | 34 | 3,688 |
| Phase 1 (gates) | 8.5% | 1.85 | 3.2% | 55 | 5,313 |
| Phase 2 (adjustments) | 11.5% | 2.10 | 4.5% | 60 | 7,188 |
| Phase 3 (BankNifty) | 15.5% | 2.05 | 7.0% | 90 | 9,688 |
| Phase 4 (compounding) | 18.0% | 2.00 | 7.5% | 100 | 11,250 |

---

## 17. File Map

```
quant-system/                        (7,428 LOC, 309 tests)
├── src/                              23 modules
│   ├── strategy_ic.py                IC entry/exit/regime detection (416 lines)
│   ├── strategy_ic_backtest.py       IC adapter + v2 adjustments (666 lines)
│   ├── strategy_cal.py               CAL entry/roll/adjust (361 lines)
│   ├── strategy_cal_backtest.py      CAL adapter + v2 adjustments (610 lines)
│   ├── strategy_bwb.py               Broken Wing Butterfly (307 lines)
│   ├── strategy_strangle.py          Strangle-to-IC conversion (386 lines)
│   ├── strategy_vix_cal.py           VIX spike calendar (362 lines)
│   ├── adjustments_ic.py             IC v2 engine — 8 types (211 lines)
│   ├── adjustments_cal.py            CAL v2 engine — 8 types (157 lines)
│   ├── backtester.py                 Generic day-by-day simulator (468 lines)
│   ├── param_sweep.py                Cartesian grid + parallel (292 lines)
│   ├── backtest_stats.py             Bootstrap/MC/walk-forward (449 lines)
│   ├── cost_engine.py                Full Indian F&O fees (356 lines)
│   ├── metrics.py                    Returns/risk/trade/capital metrics (201 lines)
│   ├── iv_calculator.py              Black-Scholes + Greeks (329 lines)
│   ├── data_fetcher.py               Kite Connect live data (297 lines)
│   ├── data_fetcher_real.py          NSE UDiFF bhavcopy (333 lines)
│   ├── synthetic_data_generator.py   Deprecated synthetic chains (368 lines)
│   ├── alerts.py                     Telegram 3-level alerts (62 lines)
│   ├── models.py                     All dataclasses (226 lines)
│   ├── strategy_protocol.py          BacktestStrategy protocol (64 lines)
│   └── exceptions.py                 Custom errors (13 lines)
├── config/
│   ├── settings.py                   All parameters + capital + gates
│   ├── strategy_params.py            Pre-defined param sets
│   ├── underlyings.py                NIFTY/BANKNIFTY/FINNIFTY config
│   └── events_calendar.json          Economic events
├── scripts/
│   ├── download_real_data.py         One-time NSE download
│   └── validate_data.py              Data integrity check
├── tests/                            309 tests, 19 files
├── data/
│   ├── real_data_cache/              247 days, 593 MB (2024 NSE F&O)
│   └── sweep_results/               Pre-computed JSON (baseline)
├── db/                               7 SQLAlchemy models, 2 migrations
├── cli/                              11 Typer commands
├── dashboard.py                      Streamlit UI (7 pages)
├── run_sweep.py                      Sweep orchestrator
└── requirements.txt                  24 dependencies
```

---

## 18. What to Improve Next

### High Priority
- **Re-sweep with real 2024 data** — `python run_sweep.py --use-real-data` (247 days of real NSE F&O cached)
- **India VIX download** — NSE hist_vix_data.csv URL returns 404, need alternative source or estimate from spot vol
- **Integrate new strategies into sweep** — BWB, Strangle, VIX Calendar not yet in run_sweep.py grids
- **Wire regime detection into IC adapter** — detect_regime() exists but not called in generate_entry()

### Medium Priority
- **Broker integration** — Kite Connect order placement not implemented
- **Morning review with live data** — CLI stub exists, needs Kite Connect
- **Paper trading validation** — 30-day paper trade before live capital
- **BankNifty sweep** — grid configured but not yet run

### Architecture
- **Strategy 3.4 (Strangle) and 3.6 (VIX Cal) not in combined sweep** — need to add to generate_combined_results()
- **Walk-forward parameter selection not wired** — select_robust_params() exists but run_sweep.py still picks max Sharpe
- **Intraday data gap** — backtester uses EOD only, real stop losses trigger intraday
- **No CI/CD** — VPS deployed manually via git pull

### Data
- **Pre-2024 data unavailable** — UDiFF format only covers 2024+. For 2018-2023 data, need paid source or Kaggle datasets.
- **VIX history missing** — NSE CSV URL 404. Could scrape from NSE website or use spot volatility estimate.

---

## 19. Dependencies

```
fastapi>=0.115.0, uvicorn, sqlalchemy>=2.0.30, alembic>=1.13.1
pandas>=2.2.2, numpy>=1.26.4, scipy>=1.13.0
kiteconnect>=5.0.1, httpx>=0.27.0, requests>=2.32.3
anthropic>=0.45.0, python-dotenv>=1.0.1
streamlit>=1.35.0, plotly>=5.22.0, matplotlib>=3.9.0
rich>=13.7.1, typer>=0.12.3
pytest>=8.2.0, pytest-asyncio>=0.23.7
yfinance>=0.2.30, pyarrow>=15.0.0
apscheduler>=3.10.4, plyer>=2.1.0, openpyxl>=3.1.2
```

---

## 20. Key Configuration (config/settings.py)

```python
TOTAL_CAPITAL           = 750_000
NIFTY_LOT_SIZE          = 75
BANKNIFTY_LOT_SIZE      = 30

# IC Gates (v3)
IC_IVR_MIN              = 20
IC_VIX_STANDARD_MAX     = 25
IC_VIX_ELEVATED_MAX     = 35
IC_VIX_KILLSWITCH       = 40
IC_EVENT_BLACKOUT_DAYS  = 7
IC_SHORT_DELTA          = 0.16
IC_WING_WIDTH_POINTS    = 500
IC_PROFIT_TARGET_PCT    = 0.50
IC_STOP_LOSS_MULTIPLIER = 2.0
IC_TIME_STOP_DTE        = 21
IC_MAX_OPEN_POSITIONS   = 2

# CAL
CAL_FRONT_MONTH_MIN_DTE = 20
CAL_FRONT_MONTH_MAX_DTE = 35
CAL_BACK_MONTH_MIN_DTE  = 60
CAL_BACK_MONTH_MAX_DTE  = 75
CAL_PROFIT_TARGET_PCT   = 0.50
CAL_MAX_MOVE_PCT_TO_ADJUST = 0.02
CAL_MAX_MOVE_PCT_TO_CLOSE  = 0.04

# Risk
ACCOUNT_DRAWDOWN_STOP   = 0.05

# Capital
PHASE_1_ACTIVE_CAPITAL  = 90_000
PHASE_3_ACTIVE_CAPITAL  = 200_000
PARKED_CAPITAL_ANNUAL_INCOME ≈ Rs 35,250/yr
```
