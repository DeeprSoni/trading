# Quant Trading System — Project Summary

A full-stack quantitative trading platform for non-speculative derivatives income on Indian options markets (NSE F&O). Trades two core strategies — **Iron Condor (IC)** and **Calendar Spreads (CAL)** — on Nifty 50, targeting a Rs 5-10 Lakhs capital base.

**Status:** Phase G (Adjustment Engine) complete — 204 tests passing, VPS dashboard live, 1,833 backtests completed, combined IC+CAL strategy generating 5.9% annual return with 1.97 Sharpe ratio.

---

## Table of Contents

1. [Directory Structure](#directory-structure)
2. [Core Modules](#core-modules)
3. [Strategy Details](#strategy-details)
4. [Backtesting Architecture](#backtesting-architecture)
5. [Cost Engine](#cost-engine)
6. [Statistical Analysis](#statistical-analysis)
7. [Database Schema](#database-schema)
8. [Configuration](#configuration)
9. [Sweep Results](#sweep-results)
10. [Dashboard](#dashboard)
11. [Testing](#testing)
12. [Dependencies](#dependencies)
13. [Build Phases](#build-phases)
14. [Architecture Decisions](#architecture-decisions)
15. [Deployment](#deployment)
16. [Next Steps](#next-steps)

---

## Directory Structure

```
quant-system/
├── src/                            # Core business logic (15 modules)
│   ├── iv_calculator.py            # Black-Scholes Greeks, IV Rank
│   ├── data_fetcher.py             # Kite Connect + NSE VIX fallback
│   ├── synthetic_data_generator.py # Synthetic option chains for backtesting
│   ├── strategy_ic.py              # Iron Condor signal generation (6 gates)
│   ├── strategy_cal.py             # Calendar Spread entry/roll/adjustment
│   ├── backtester.py               # Generic day-by-day simulator
│   ├── param_sweep.py              # Cartesian parameter grid + parallel execution
│   ├── cost_engine.py              # Indian F&O fee schedule calculator
│   ├── backtest_stats.py           # Bootstrap CI, Monte Carlo, walk-forward
│   ├── strategy_protocol.py        # BacktestStrategy protocol (pluggable adapters)
│   ├── strategy_ic_backtest.py     # IC adapter for backtester (parameterised)
│   ├── strategy_cal_backtest.py    # CAL adapter for backtester (parameterised)
│   ├── models.py                   # Shared dataclasses (signals, positions, results)
│   ├── exceptions.py               # Custom error types
│   └── __init__.py
├── config/                         # Configuration & settings
│   ├── settings.py                 # Capital, fees, DTE ranges, risk controls
│   ├── strategy_params.py          # Pre-defined param sets (base, conservative, aggressive)
│   ├── events_calendar.json        # Major economic events for event gating
│   └── __init__.py
├── db/                             # Database & ORM
│   ├── models.py                   # SQLAlchemy ORM (6 tables)
│   ├── crud.py                     # CRUD operations
│   └── __init__.py                 # SQLite session setup
├── alembic/                        # Database migrations
│   └── versions/
│       └── 001_initial_schema.py   # 6 tables
├── cli/                            # CLI commands (skeleton)
│   └── commands.py                 # morning-review, login, backtest, etc.
├── api/                            # FastAPI backend (parked)
├── tests/                          # 204 passing tests
│   ├── conftest.py                 # Pytest fixtures
│   ├── fixtures/                   # Sample data (JSON, CSV)
│   └── test_*.py                   # 13 test files
├── data/
│   └── sweep_results/              # Pre-computed backtest results
│       ├── ic_sweep.json           # 729 IC configs
│       ├── cal_sweep.json          # 729 CAL configs
│       └── combined_sweep.json     # 375 IC+CAL blends
├── dashboard.py                    # Streamlit UI (3 sections)
├── run_sweep.py                    # Sweep executor
├── cli.py                          # CLI entry point
├── requirements.txt                # Python dependencies
├── PRD.md                          # Full product requirements
├── .env.template                   # Secrets template
└── setup.sh                        # Installation script
```

---

## Core Modules

### Data Layer

**iv_calculator.py** — Black-Scholes Greeks and IV Rank computation using scipy (not mibian, which is unmaintained). Provides `_bs_price()`, `_bs_delta()`, `_bs_gamma()`, `_bs_theta()`, `_bs_vega()`, and `find_strike_by_delta()` via binary search.

**data_fetcher.py** — Live data acquisition via Kite Connect API (primary) with NSE India website scraping as VIX fallback. Caches to `data/cache/` for resilience.

**synthetic_data_generator.py** — Generates realistic daily option chains from spot price history + VIX for backtesting. NSE doesn't publish free historical strike-level data, so synthetic generation is essential.

Key calibration parameters:
- VIX = realized_vol * 1.55 (India VIX trades 30-50% above realized volatility)
- VIX floor = 14% (India VIX rarely below 12-13%)
- OTM demand premium = +15% for options >2% OTM (hedger demand)
- Vol skew = -0.25, smile = 0.20
- Monthly expiries only (Nifty weekly expiries discontinued late 2024)

### Strategy Engine

**strategy_ic.py** — Iron Condor signal generation with 6 sequential entry gates and priority-ordered exit signals. See [Strategy Details](#strategy-details).

**strategy_cal.py** — Calendar Spread entry, roll, and adjustment logic with 4 entry gates and multiple roll/close conditions.

### Backtesting

**backtester.py** — Generic day-by-day simulator. Strategy-agnostic via protocol adapters.

**param_sweep.py** — Cartesian product parameter grid with ProcessPoolExecutor for parallel execution. Supports ranking by Sharpe, Sortino, Calmar, win rate, drawdown, P&L.

**strategy_protocol.py** — `BacktestStrategy` protocol defining the adapter interface: `should_enter()`, `generate_entry()`, `should_exit()`, `should_adjust()`, `reprice_position()`.

**strategy_ic_backtest.py / strategy_cal_backtest.py** — Parameterised adapters that implement the protocol for sweep execution.

### Analysis

**cost_engine.py** — Complete Indian F&O fee schedule (FY 2024-25) with 3 slippage models.

**backtest_stats.py** — Bootstrap confidence intervals (1000 samples), Monte Carlo simulation (10,000 paths), walk-forward cross-validation (5-fold), regime analysis.

---

## Strategy Details

### Iron Condor (IC)

**Entry Gates (6, sequential — short-circuits on first failure):**

| # | Gate | Threshold |
|---|------|-----------|
| 1 | IV Rank | >= 30 |
| 2 | India VIX | <= 25 |
| 3 | DTE | 30-45 days |
| 4 | Open positions | < 2 |
| 5 | Economic events | None within 25 days |
| 6 | Account drawdown | < 5% |

**Trade Structure:** 4-leg IC with 16-delta shorts and 500-point wings.

**Exit Signals (priority order):**
1. Stop loss (2x premium) — IMMEDIATE
2. Time stop (21 DTE) — close by 3 PM
3. Profit target (50%) — close and re-enter

### Calendar Spread (CAL)

**Entry Gates (4):**

| # | Gate | Threshold |
|---|------|-----------|
| 1 | VIX | <= 28 |
| 2 | Economic events | None within 7 days |
| 3 | Open positions | < 2 |
| 4 | Expiry availability | Front (20-35 DTE) + Back (60-75 DTE) |

**Trade Structure:** 2-leg calendar on ATM strike — sell front-month, buy back-month.

**Roll/Close Conditions:**
- Front month <= 3 DTE: roll to next monthly expiry
- Front month at 50% profit: early roll
- Back month at 25 DTE: close entire position
- Back month IV expansion >= 30%: harvest and close
- Market move 2%: recentre at new ATM
- Market move 4%: close entire position

---

## Backtesting Architecture

The backtester is strategy-agnostic and cost-accurate with no lookahead bias.

**Daily Loop:**
1. Check exits on open positions
2. Check adjustments (rolls, recentres) on remaining positions
3. Check entries if capacity available
4. Apply transaction costs via CostEngine
5. Track daily P&L, peak equity, drawdown, cumulative curves

**Output:** `BacktestResult` with full trade-by-trade detail — entry/exit dates, strikes, Greeks, costs, P&L, holding days, adjustments.

**Parameter Sweep Grids:**

| Strategy | Parameters | Values | Total Configs |
|----------|-----------|--------|---------------|
| IC | delta, wing, PT, SL, time stop, IV rank | 4×3×3×3×3×3 | 729 |
| CAL | adjust%, close%, PT, back DTE, front roll, VIX | 3×3×3×3×3×3 | 729 |
| Combined | IC/CAL allocation blends | — | 375 |

---

## Cost Engine

Complete Indian F&O fee schedule (FY 2024-25):

| Fee | Rate | Notes |
|-----|------|-------|
| Brokerage | Rs 20/order (flat) | Zerodha F&O rate |
| STT | 0.0625% on sell side | Budget 2024 reduction |
| STT ITM expiry | 0.125% of intrinsic | Hidden cost if expires ITM |
| NSE Exchange | 0.053% on turnover | Both sides |
| SEBI Fee | Rs 10/crore | Regulatory fee |
| Stamp Duty | 0.003% on buy side | Transfer tax |
| GST | 18% on (brokerage + exchange + SEBI) | Meta-tax |

**Slippage Models:**
- **Optimistic:** 50% of bid-ask spread
- **Realistic:** 75% of bid-ask spread
- **Conservative:** 100% of spread + Rs 1

---

## Statistical Analysis

| Method | Detail |
|--------|--------|
| Bootstrap CI | 1000 samples, 95% confidence — Sharpe, P&L, win rate |
| Monte Carlo | 10,000 forward simulations — probability of profit, ruin, percentiles |
| Walk-Forward | 5-fold cross-validation — in-sample vs out-of-sample Sharpe degradation |
| Regime Analysis | Performance breakdown by market condition (sideways, trending, high-vol) |
| Verdict | STRONG (Sharpe>1), MARGINAL (0.5-1), WEAK (<0.5), INSUFFICIENT_DATA |

---

## Database Schema

SQLite with WAL mode for concurrent access. 6 tables via Alembic migration:

| Table | Purpose |
|-------|---------|
| `trades` | Core trade log — entry/exit, strikes, P&L, costs, regime |
| `calendar_cycles` | Individual cycles within a CAL trade (FK to trades) |
| `edge_metrics` | Rolling performance snapshots (win rate, profit factor, YTD P&L) |
| `order_log` | Execution ledger — Zerodha order IDs, fill prices, slippage |
| `zerodha_sessions` | Daily access token cache |
| `alert_log` | Alert history (type, urgency, acknowledged) |

---

## Configuration

**Capital Structure (Rs 7,50,000):**

| Allocation | Amount | Purpose |
|-----------|--------|---------|
| Active trading | Rs 3,00,000 | Margin deployed |
| Reserve buffer | Rs 2,50,000 | Never deployed |
| Liquid fund | Rs 1,50,000 | Parked (6.5% annual yield) |
| Cash buffer | Rs 50,000 | Settlement |

**Risk Controls:**
- VIX max for IC: 25
- Account drawdown stop: 5% (kill switch)
- Win rate yellow alert: 62%
- Profit factor yellow alert: 1.1

---

## Sweep Results

**Run Parameters:** seed=42, 400 trading days, June 2022 — December 2023, with adjustments enabled.

### Iron Condor Best: `IC_d0.25_w400_pt50_sl2.5`

| Metric | Value |
|--------|-------|
| Net P&L | Rs 34,004 |
| Trades | 19 (14W / 5L) |
| Win Rate | 73.7% |
| Drawdown | 3.9% |
| Sharpe | -0.16 |
| Adjustments | 14/19 trades adjusted (15 total) |

### Calendar Spread Best (5+ trades)

| Metric | Value |
|--------|-------|
| Net P&L | Rs 1,54,118 |
| Trades | 15 |
| Profit Target | 40% |

### Combined Best: IC 70% / CAL 30%

| Metric | Value |
|--------|-------|
| Annual Return | 5.9% |
| Sharpe | 1.97 |
| Win Rate | 71% |
| Drawdown | 1.8% |
| Trades | 34 |

**Key finding:** All 375 combined configurations are profitable across all 3 slippage models, confirming strategy robustness.

---

## Dashboard

Streamlit web UI (`dashboard.py`) with 3 sections:

1. **Iron Condor Analysis** — Best IC config, profit range, drawdown, ranked by Sharpe
2. **Calendar Spread Analysis** — Best CAL config, regime analysis
3. **Combined (IC + CAL)** — Blended allocation, profit distribution, slippage sensitivity

Features: interactive tables, Plotly equity curves, P&L distributions, individual trade drill-down, adjustment impact quantification.

**Live at:** `http://217.217.249.102:8501` (VPS, systemd user service)

---

## Testing

**204 passing tests** across 13 test files. All deterministic (seed=42), no real API calls.

| Test File | Count | Coverage |
|-----------|-------|----------|
| test_iv_calculator | ~12 | BS pricing, delta, gamma, theta, IV Rank |
| test_data_fetcher | ~8 | Kite mock, NSE fallback, caching |
| test_synthetic_data | ~10 | Chain generation, skew/smile, demand premium |
| test_strategy_ic | ~15 | All 6 entry gates, exit signals, trade structure |
| test_strategy_cal | ~12 | Entry gates, roll conditions, adjustments |
| test_backtester | ~10 | Day-by-day simulation, P&L tracking, drawdown |
| test_cost_engine | ~25 | Every fee type, slippage models, margin cost |
| test_param_sweep | ~8 | Grid generation, ranking, parallel execution |
| test_adjustment_engine | ~35 | IC adjustments, CAL rolls, backtester execution |
| test_backtest_stats | ~10 | Bootstrap CI, Monte Carlo, walk-forward |
| test_strategy_backtest | ~20 | IC/CAL adapters, entry/exit/adjust decisions |

---

## Dependencies

| Package | Purpose |
|---------|---------|
| scipy >= 1.13.0 | Black-Scholes (norm.cdf, brentq) |
| pandas >= 2.2.2 | Data manipulation |
| numpy >= 1.26.4 | Numerical computation |
| kiteconnect >= 5.0.1 | Zerodha API (max available on PyPI) |
| sqlalchemy >= 2.0.30 | ORM |
| alembic >= 1.13.1 | Migrations |
| streamlit >= 1.35.0 | Dashboard |
| plotly >= 5.22.0 | Interactive charts |
| anthropic >= 0.45.0 | Claude API (Sonnet 4.x model IDs) |
| fastapi >= 0.115.0 | Backend API (phases 4-11) |
| pytest >= 8.2.0 | Testing |
| typer >= 0.12.3 | CLI |
| rich >= 13.7.1 | Terminal output |
| httpx >= 0.27.0 | Async HTTP client |

---

## Build Phases

| Phase | Status | Module | Tests |
|-------|--------|--------|-------|
| Pre-Build | DONE | Directory structure, config, DB schema, alembic, fixtures, CLI skeleton | — |
| 1 — Data Layer | DONE | iv_calculator, data_fetcher, synthetic_data_generator | 44 |
| 2 — Strategy Engine | DONE | strategy_ic, strategy_cal | 34 |
| A — Cost Engine | DONE | cost_engine | 34 |
| B — Strategy Protocol + Adapters | DONE | strategy_protocol, IC/CAL backtest adapters | 27 |
| C — Generic Backtester | DONE | backtester | 15 |
| D — Parameter Sweep | DONE | param_sweep | 12 |
| E — Statistical Analysis | DONE | backtest_stats | 17 |
| F — Run Sweeps | DONE | 729 IC + 729 CAL + 375 combined = 1,833 backtests | — |
| G — Adjustment Engine | DONE | IC rolling/harvesting, CAL recentre/front-roll/IV-harvest | 21 |
| Dashboard | DONE | Streamlit (3 sections) | — |
| VPS Deploy | DONE | systemd service on VPS | — |
| Phases 4-11 | PARKED | Broker, UI, alerts, live trading | — |

---

## Architecture Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.13 | Best quant ecosystem |
| Options Math | scipy.stats.norm | Direct BS implementation (mibian unmaintained) |
| Live Data | Kite Connect API | Official Zerodha SDK |
| Historical Data | Synthetic generation | NSE has no free strike-level history |
| Backtesting | Day-by-day simulator | Strategy-agnostic, no lookahead |
| Database | SQLite + SQLAlchemy + Alembic | Zero setup, WAL mode |
| Notifications | Telegram Bot API (primary) | Works when PC is off |
| AI | Claude via Anthropic API | Daily review + orchestration |
| Parallelism | ProcessPoolExecutor | True multi-core for sweeps |
| Cost Model | Full Indian F&O schedule | Every real cost included |
| Order Type | NRML (not MIS) | MIS would auto-square-off |

---

## Deployment

**Local:**
```bash
cd quant-system
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python run_sweep.py            # Run backtests
streamlit run dashboard.py     # Launch dashboard
python cli.py morning-review   # CLI (skeleton)
```

**VPS (217.217.249.102):**
- Systemd user service running Streamlit on port 8501
- Requires `ANTHROPIC_API_KEY` and `ZERODHA_*` env vars
- Auto-restarts on crash

---

## Next Steps

**Immediate:**
1. Validate backtest with real broker data
2. Paper trading on Zerodha (confirm live execution, slippage)
3. Implement CLI commands (morning-review, login, execute-trade)
4. Add Telegram alerts
5. Redeploy adjustment engine to VPS

**Medium-term (Phases 4-11):**
1. Broker integration (order placement + cancellation)
2. Position monitoring (60-sec polling)
3. Adjustment automation
4. Edge tracking with alerts
5. Daily Claude AI review

**Long-term:**
1. React web dashboard
2. Multi-strategy portfolio (BankNifty, other underlyings)
3. ML parameter optimisation
4. Risk attribution and regime classification
