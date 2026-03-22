# PRODUCT REQUIREMENTS DOCUMENT
## Non-Speculative Derivatives Income System — Full-Stack Quant Trading Platform
**Built entirely by Claude Code · Zero human decision-making required**

---

**Capital:** ₹5–10 Lakhs | **Broker:** Zerodha (Kite Connect API) | **Market:** Nifty 50 & BankNifty | **Strategies:** Iron Condor + Calendar Spreads | **AI:** Claude Sonnet via Anthropic API

---

## HOW CLAUDE CODE MUST USE THIS PRD

1. Read every section fully before writing any code
2. Build phases in the exact numbered order — no skipping
3. Run all tests at the end of each phase — only proceed when tests pass
4. If a test fails, the resolution is documented in the same section
5. Every decision is pre-made — no choices required during implementation

---

## TABLE OF CONTENTS

1. System Architecture
2. Tech Stack and Dependencies
3. Project Structure
4. Phase 1 — Data Layer
5. Phase 2 — Strategy Engine
6. Phase 3 — Backtesting Engine
7. Phase 4 — Broker Integration
8. Phase 5 — Position Monitor and Alerts
9. Phase 6 — Adjustment Engine
10. Phase 7 — Cost and P&L Engine
11. Phase 8 — Edge Tracking Engine
12. Phase 9 — Daily Review CLI
13. Phase 10 — Dashboard Web UI
14. Phase 11 — Claude AI Integration
15. Database Schema
16. Configuration Files
17. Testing Requirements
18. Deployment Instructions
19. Error Handling Reference
20. Claude Code Execution Checklist

---

## 1. SYSTEM ARCHITECTURE

### High-Level Design

```
┌──────────────────────────────────────────────────────────────┐
│                       USER INTERFACE                         │
│        Web Dashboard (React 18)  +  CLI (Python Rich)        │
└──────────────────────┬───────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────┐
│                     FASTAPI BACKEND                          │
│  /api/positions  /api/signals  /api/review  /api/backtest    │
└──────┬─────────────┬──────────────────────┬──────────────────┘
       │             │                      │
┌──────▼──────┐ ┌────▼──────┐  ┌───────────▼────────────────┐
│  Strategy   │ │ Backtest  │  │   Claude AI Module          │
│  Engine     │ │ Engine    │  │   (Anthropic API — Sonnet)  │
└──────┬──────┘ └────┬──────┘  └───────────┬────────────────┘
       │             │                      │
┌──────▼─────────────▼──────────────────────▼────────────────┐
│                       DATA LAYER                            │
│     SQLite via SQLAlchemy  +  CSV cache (historical data)   │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│                  EXTERNAL INTEGRATIONS                       │
│  Zerodha Kite API (primary) | NSE India (VIX fallback) |    │
│  Anthropic API | Telegram Bot API (alerts)               │
└─────────────────────────────────────────────────────────────┘
```

### Core Modules — Build in This Exact Order

| # | Module | File | Purpose |
|---|--------|------|---------|
| 1 | data_fetcher | src/data_fetcher.py | Pull live options data from Kite Connect (primary) and NSE (VIX fallback) |
| 1b | synthetic_data | src/synthetic_data_generator.py | Generate realistic historical options data from Nifty spot + Black-Scholes for backtesting |
| 2 | iv_calculator | src/iv_calculator.py | Compute IV Rank, VIX, Greeks via Black-Scholes (scipy — no mibian) |
| 3 | strategy_ic | src/strategy_ic.py | Iron Condor signal generation and validation |
| 4 | strategy_cal | src/strategy_cal.py | Calendar Spread signal generation and rolls |
| 5 | backtester | src/backtester.py | Historical simulation with realistic costs |
| 6 | broker_zerodha | src/broker_zerodha.py | Kite Connect order placement and management |
| 7 | position_monitor | src/position_monitor.py | Live P&L tracking, polling loop, alerts |
| 8 | adjustment_engine | src/adjustment_engine.py | Rules-based position adjustment logic |
| 9 | cost_engine | src/cost_engine.py | Real cost calculation per trade |
| 10 | edge_tracker | src/edge_tracker.py | Win rate, profit factor, stop signals |
| 11 | daily_review_cli | cli/commands.py | Morning prompt terminal interface |
| 12 | dashboard | frontend/ | React web UI with 5 tabs |
| 13 | claude_advisor | src/claude_advisor.py | Daily AI review via Anthropic API |

### Daily Data Flow

```
08:30 AM  Telegram reminder sent: "Log in to Zerodha for today's token"
          User runs: python cli.py login (manual browser login — required daily by Zerodha)

09:00 AM  User runs: python cli.py morning-review
          data_fetcher pulls live option chain via Kite Connect API
          iv_calculator computes IV Rank and VIX (VIX from NSE fallback if needed)
          CLI displays positions + signals
          claude_advisor generates action plan via Anthropic API

09:15 AM  Market opens
          position_monitor starts 60-second polling loop
          Alert triggered → Telegram notification (primary) + desktop notification + log to DB

During    strategy_ic and strategy_cal check entry conditions every 15 min
day       Conditions met → generate ORDER OBJECT → show to user
          User types 'execute' → broker_zerodha places order

03:30 PM  Market closes
          edge_tracker updates rolling metrics in DB
          cost_engine calculates today's realised costs
          Dashboard updates with end-of-day snapshot
```

---

## 2. TECH STACK AND DEPENDENCIES

### Technology Decisions — Pre-Made, Do Not Change

| Component | Choice | Reason |
|-----------|--------|--------|
| Language | Python 3.11 | Best quant ecosystem, pandas/numpy native |
| Backend API | FastAPI | Async, fast, auto-docs at /docs |
| Database | SQLite via SQLAlchemy | Zero setup, sufficient for retail scale |
| Frontend | React 18 + Vite | Fast dev, simple component model |
| Styling | Tailwind CSS | Utility classes, no separate CSS files |
| Charts | Recharts | React-native, composable |
| CLI | Python Rich + Typer | Beautiful terminal output |
| Broker SDK | kiteconnect (official) | Only official Zerodha SDK — also primary live data source |
| HTTP client | httpx | Async-first, better than requests for FastAPI |
| Options math | scipy (Black-Scholes) | Direct BS implementation via scipy.stats.norm — no mibian (unmaintained) |
| Scheduler | APScheduler | Cron-style jobs within Python process |
| Notifications | Telegram Bot API (primary) + plyer (secondary) | Telegram for reliable alerts even when PC is off; plyer for local desktop |
| AI | anthropic SDK | For claude_advisor module |
| Testing | pytest + pytest-asyncio | Full async test support |
| Env management | python-dotenv | .env file loading |

### Complete requirements.txt

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.30
alembic>=1.13.1
pandas>=2.2.2
numpy>=1.26.4
kiteconnect>=5.1.0
httpx>=0.27.0
apscheduler>=3.10.4
plyer>=2.1.0
anthropic>=0.45.0
python-dotenv>=1.0.1
rich>=13.7.1
typer>=0.12.3
pytest>=8.2.0
pytest-asyncio>=0.23.7
requests>=2.32.3
scipy>=1.13.0
matplotlib>=3.9.0
openpyxl>=3.1.2
```

**REMOVED:** `mibian` — unmaintained, buggy put delta calculations on Python 3.11+. Replaced with direct Black-Scholes implementation using `scipy.stats.norm` (already a dependency).

**UPDATED:** `anthropic>=0.45.0` — required for Claude 4.x model IDs. Old `0.28.0` does not support `claude-sonnet-4-*` models.

**NOTE:** Using `>=` minimum versions instead of `==` pinning to avoid install conflicts. Pin exact versions in a lockfile for production.

### setup.sh — Claude Code Must Create This File

```bash
#!/bin/bash
set -e
echo "Setting up Quant Trading System..."

python3 --version | grep -E "3\.(11|12)" || { echo "ERROR: Python 3.11+ required"; exit 1; }

python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

if [ ! -f .env ]; then
  cp .env.template .env
  echo "IMPORTANT: Fill in your API keys in .env before running"
fi

python -m alembic upgrade head

mkdir -p data/historical data/cache logs

echo "Setup complete. Run: source venv/bin/activate && python cli.py --help"
```

---

## 3. PROJECT STRUCTURE

Claude Code must create this exact directory and file structure before writing any code.

```
quant-system/
├── .env                              # API keys — gitignored
├── .env.template                     # Template with all required key names
├── .gitignore                        # Exclude: .env venv __pycache__ *.db logs/
├── requirements.txt
├── setup.sh
├── README.md
├── cli.py                            # Entry point: python cli.py [command]
├── alembic.ini
│
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
│
├── config/
│   ├── __init__.py
│   ├── settings.py                   # ALL constants — no magic numbers elsewhere
│   ├── strategy_params.py            # Parameter sets for backtest variations
│   └── events_calendar.json          # RBI, Budget, Fed meeting dates
│
├── data/
│   ├── historical/                   # nifty_options_YYYY.csv files
│   ├── cache/                        # Intraday cache, refreshed daily
│   └── .gitkeep
│
├── src/
│   ├── __init__.py
│   ├── data_fetcher.py
│   ├── synthetic_data_generator.py   # Generates realistic historical options data for backtesting
│   ├── iv_calculator.py
│   ├── strategy_ic.py
│   ├── strategy_cal.py
│   ├── backtester.py
│   ├── broker_zerodha.py
│   ├── position_monitor.py
│   ├── adjustment_engine.py
│   ├── cost_engine.py
│   ├── edge_tracker.py
│   └── claude_advisor.py
│
├── api/
│   ├── __init__.py
│   ├── main.py                       # FastAPI app, mounts all routers
│   └── routers/
│       ├── __init__.py
│       ├── positions.py
│       ├── signals.py
│       ├── backtest.py
│       ├── review.py
│       └── trades.py
│
├── db/
│   ├── __init__.py
│   ├── models.py                     # All SQLAlchemy ORM models
│   └── crud.py                       # All database read/write operations
│
├── cli/
│   ├── __init__.py
│   └── commands.py                   # All Typer CLI commands
│
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── index.html
│   └── src/
│       ├── App.jsx
│       ├── main.jsx
│       ├── components/
│       │   ├── Dashboard.jsx
│       │   ├── Positions.jsx
│       │   ├── Signals.jsx
│       │   ├── BacktestResults.jsx
│       │   ├── EdgeTracker.jsx
│       │   └── DailyReview.jsx
│       └── api/
│           └── client.js             # Axios calls to FastAPI
│
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── sample_option_chain.json
    │   ├── sample_historical_prices.csv
    │   └── sample_trades.json
    ├── test_data_fetcher.py
    ├── test_iv_calculator.py
    ├── test_strategy_ic.py
    ├── test_strategy_cal.py
    ├── test_backtester.py
    ├── test_cost_engine.py
    ├── test_edge_tracker.py
    └── test_synthetic_data.py
```

---

## 4. PHASE 1 — DATA LAYER

### 4.1 config/settings.py — Build This First

Every constant lives here. No hardcoded numbers anywhere else in the codebase. If another module needs a value, it imports from settings.

```python
import os
from dotenv import load_dotenv
load_dotenv()

# BROKER
ZERODHA_API_KEY    = os.getenv("ZERODHA_API_KEY")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET")
ZERODHA_USER_ID    = os.getenv("ZERODHA_USER_ID")

# ANTHROPIC
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# CAPITAL
TOTAL_CAPITAL          = 750000   # Rs 7,50,000 midpoint of target range
ACTIVE_TRADING_CAPITAL = 300000   # Rs 3,00,000 deployed as margin
RESERVE_BUFFER         = 250000   # Never deployed in normal conditions
COIN_FUND_CAPITAL      = 150000   # Always parked in liquid fund
CASH_BUFFER            = 50000    # For brokerage and settlement

# INSTRUMENTS
NIFTY_LOT_SIZE      = 25
BANKNIFTY_LOT_SIZE  = 15
PRIMARY_INSTRUMENT   = "NIFTY"

# IRON CONDOR PARAMETERS
IC_SHORT_DELTA             = 0.16
IC_WING_WIDTH_POINTS       = 500
IC_MIN_DTE_ENTRY           = 30
IC_MAX_DTE_ENTRY           = 45
IC_MIN_IV_RANK             = 30
IC_PROFIT_TARGET_PCT       = 0.50
IC_STOP_LOSS_MULTIPLIER    = 2.0
IC_TIME_STOP_DTE           = 21
IC_MAX_OPEN_POSITIONS      = 2
IC_MAX_PCT_CAPITAL_PER_TRADE = 0.05

# CALENDAR SPREAD PARAMETERS
# NOTE: Nifty weekly expiries were discontinued by NSE in late 2024.
# Front month now uses the nearest MONTHLY expiry (~20-30 DTE) instead of weeklies.
CAL_BACK_MONTH_MIN_DTE       = 60
CAL_BACK_MONTH_MAX_DTE       = 75
CAL_FRONT_MONTH_MIN_DTE      = 20    # Nearest monthly expiry (was 7 for weeklies)
CAL_FRONT_MONTH_MAX_DTE      = 35    # Upper bound for front month selection
CAL_PROFIT_TARGET_PCT        = 0.50
CAL_BACK_MONTH_CLOSE_DTE     = 25
CAL_MAX_MOVE_PCT_TO_ADJUST   = 0.02
CAL_MAX_MOVE_PCT_TO_CLOSE    = 0.04
CAL_MAX_OPEN_POSITIONS       = 2

# RISK CONTROLS
VIX_MAX_FOR_IC               = 25
VIX_HIGH_THRESHOLD           = 28
ACCOUNT_DRAWDOWN_SIZE_DOWN   = 0.03
ACCOUNT_DRAWDOWN_STOP        = 0.05
ROLLING_WIN_RATE_YELLOW      = 0.62
ROLLING_WIN_RATE_RED         = 0.58
PROFIT_FACTOR_YELLOW         = 1.1
PROFIT_FACTOR_RED            = 1.0

# COSTS (Updated to FY 2024-25 rates)
COST_BROKERAGE_PER_ORDER     = 20
COST_BROKERAGE_GST_RATE      = 0.18
COST_STT_SELL_RATE           = 0.000625   # Updated: 0.0625% on sell side (Budget 2024)
COST_STT_ITM_EXPIRY_RATE     = 0.00125    # 0.125% of intrinsic value on ITM expiry
COST_NSE_EXCHANGE_RATE       = 0.00053
COST_STAMP_DUTY_RATE         = 0.00003
COST_SLIPPAGE_PER_UNIT_PER_LEG = 2
COST_LIQUID_FUND_RATE_ANNUAL = 0.065

# TELEGRAM ALERTS (primary notification channel)
TELEGRAM_BOT_TOKEN           = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID             = os.getenv("TELEGRAM_CHAT_ID")

# SYSTEM
DATABASE_URL                 = "sqlite:///./quant_system.db"
DATABASE_WAL_MODE            = True       # Enable WAL for SQLite concurrent reads/writes
TIMEZONE                     = "Asia/Kolkata"
MARKET_OPEN                  = "09:15"
MARKET_CLOSE                 = "15:30"
DATA_REFRESH_INTERVAL_MIN    = 15
POSITION_POLL_INTERVAL_SEC   = 60
```

### 4.2 .env.template

```
ZERODHA_API_KEY=your_api_key_here
ZERODHA_API_SECRET=your_api_secret_here
ZERODHA_USER_ID=your_zerodha_user_id
ANTHROPIC_API_KEY=your_anthropic_api_key
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id
```

**Telegram Setup (2 minutes):**
1. Message @BotFather on Telegram, send `/newbot`, follow prompts → get bot token
2. Message your new bot, then visit `https://api.telegram.org/bot<TOKEN>/getUpdates` → get chat_id
3. Add both values to `.env`

### 4.3 src/data_fetcher.py — Full Specification

**ARCHITECTURE CHANGE:** Kite Connect API is the **primary** data source for live options data. NSE scraping is used **only** as a fallback for India VIX (which Kite doesn't provide directly). Historical options data for backtesting is generated synthetically — see Section 4.6.

**Class: DataFetcher**

```python
from kiteconnect import KiteConnect
from config import settings

class DataFetcher:

    def __init__(self, kite: KiteConnect):
        """
        Accepts an authenticated KiteConnect instance.
        The broker_zerodha module handles token management.
        """
        self.kite = kite
        self._nse_session = None  # Lazy-init for VIX fallback only

    def get_option_chain(self, symbol: str) -> dict:
        """
        PRIMARY SOURCE: Kite Connect API

        Steps:
        1. kite.instruments("NFO") → get all NFO instruments
        2. Filter by symbol prefix (e.g. "NIFTY") and instrument_type in ("CE", "PE")
        3. Group by expiry → pick the target expiry based on DTE requirements
        4. For each strike/type combo, call kite.ltp() or kite.quote() to get prices
        5. Build option chain dict with same structure:

        Returns dict with keys:
          records: list of option rows with strike, type, bid, ask, ltp, iv, oi, volume
          timestamp: datetime of data
          underlying_value: current index level (from kite.ltp("NSE:NIFTY 50"))
          expiry_dates: list of available expiry dates

        Cache response to: data/cache/{symbol}_chain.json with timestamp

        RATE LIMIT NOTE: kite.quote() allows max 500 instruments per call.
        Batch requests accordingly.

        Error handling:
          TokenException    -> raise, caller must re-login
          NetworkError      -> log warning, return cache, do not crash
          DataException     -> log, return cache
          Cache older than 15 minutes during market hours -> raise DataStalenessError
        """

    def get_india_vix(self) -> float:
        """
        PRIMARY: Try kite.ltp("NSE:INDIA VIX") first
        FALLBACK: NSE scraping (https://www.nseindia.com/api/allIndices)

        NSE fallback uses two-step session pattern:
          1. GET https://www.nseindia.com with browser headers to get cookies
          2. GET /api/allIndices with those cookies
          3. Parse for index name "INDIA VIX", return 'last' value

        Cache to: data/cache/india_vix.json
        Return float. If both sources fail, return cached value.
        """

    def get_nifty_price_history(self, from_date, to_date) -> pd.DataFrame:
        """
        Uses kite.historical_data() for Nifty 50 spot prices.
        instrument_token for NIFTY 50 = 256265

        kite.historical_data(256265, from_date, to_date, "day")

        Returns DataFrame: date, open, high, low, close, volume
        Save to: data/historical/nifty_price_{from_date}_{to_date}.csv
        If file exists already: return from file, do not re-fetch

        NOTE: Kite historical data API gives up to 2000 days of daily data.
        For longer ranges, make multiple requests.
        """

    def _init_nse_session(self):
        """
        NSE fallback session. Only used for VIX when Kite is unavailable.
        Create requests.Session with browser headers and NSE cookies.
        """
```

**Error Resolution Table for data_fetcher.py:**

| Error | Cause | Resolution |
|-------|-------|------------|
| TokenException | Zerodha token expired (daily reset ~8 AM) | Raise to caller, prompt re-login |
| NetworkError | API unreachable or no internet | Return cached JSON, log warning, continue |
| DataStalenessError | Cache over 15 min old in market hours | Raise to caller, position_monitor handles |
| DataException | Kite API returned error | Log, return cache, do not crash |
| Empty response | Market holiday, no data | Return empty DataFrame with correct columns |

### 4.4 src/iv_calculator.py — Full Specification

**NOTE:** Uses `scipy.stats.norm` and `scipy.optimize.brentq` for Black-Scholes calculations. Do NOT use `mibian` — it is unmaintained and has known bugs with put delta on Python 3.11+.

```python
import numpy as np
from scipy.stats import norm
from scipy.optimize import brentq

class IVCalculator:

    def _bs_price(self, S, K, T, r, sigma, option_type) -> float:
        """
        Core Black-Scholes pricing formula.
        S: underlying price
        K: strike price
        T: time to expiry in years
        r: risk-free rate (default 0.065 for India)
        sigma: implied volatility as decimal
        option_type: "CE" or "PE"

        d1 = (ln(S/K) + (r + sigma^2/2) * T) / (sigma * sqrt(T))
        d2 = d1 - sigma * sqrt(T)

        CE price = S * N(d1) - K * e^(-rT) * N(d2)
        PE price = K * e^(-rT) * N(-d2) - S * N(-d1)
        """

    def _bs_delta(self, S, K, T, r, sigma, option_type) -> float:
        """
        CE delta = N(d1)         — ranges 0 to +1
        PE delta = N(d1) - 1     — ranges -1 to 0
        """

    def _bs_gamma(self, S, K, T, r, sigma) -> float:
        """gamma = N'(d1) / (S * sigma * sqrt(T))"""

    def _bs_theta(self, S, K, T, r, sigma, option_type) -> float:
        """Daily theta in rupees (divide annual by 365)"""

    def _bs_vega(self, S, K, T, r, sigma) -> float:
        """vega = S * N'(d1) * sqrt(T) / 100  (per 1% IV change)"""

    def _implied_vol(self, market_price, S, K, T, r, option_type) -> float:
        """
        Solve for sigma where bs_price(sigma) = market_price
        Use scipy.optimize.brentq with bounds [0.01, 5.0]
        If no solution found (market price below intrinsic): return None
        """

    def calculate_iv_rank(self, symbol, current_iv, lookback_days=252) -> float:
        """
        Formula: IV_Rank = (current_iv - min_iv) / (max_iv - min_iv) * 100

        Data: load historical IV from data/historical CSV files
        If less than 100 days of history available: return None, log warning
        Returns: float 0 to 100
        Example: 65 means current IV is in 65th percentile of past year
        """

    def calculate_greeks(self, underlying_price, strike, time_to_expiry_years,
                         iv, option_type, risk_free_rate=0.065) -> dict:
        """
        Uses _bs_* methods above. No external library dependency.

        Returns dict:
          delta: directional exposure (-1 to +1)
          gamma: rate of delta change
          theta: daily time decay in rupees
          vega:  sensitivity to IV change
          theoretical_price: Black-Scholes fair value
        """

    def find_strike_by_delta(self, option_chain, target_delta, option_type,
                              tolerance=0.03) -> int:
        """
        Scan option chain to find strike closest to target_delta.

        Algorithm:
          1. Filter chain rows by option_type (CE or PE)
          2. For each strike, calculate delta using calculate_greeks()
          3. Find strike where abs(calculated_delta - target_delta) is minimum
          4. If minimum distance > tolerance: log warning, still return closest

        Returns: strike price as integer
        """

    def classify_market_regime(self, vix, nifty_monthly_change_pct) -> str:
        """
        Apply rules in this order:
          if vix > 25:                                  return "HIGH_VOL"
          if abs(nifty_monthly_change_pct) > 5:         return "TRENDING"
          if abs(nifty_monthly_change_pct) < 3
             and vix < 18:                              return "SIDEWAYS"
          else:                                         return "NORMAL"

        This label gets stored with every trade for regime analysis.
        """
```

### 4.5 src/synthetic_data_generator.py — Full Specification

**WHY THIS EXISTS:** NSE does not provide free historical options chain data at strike-level granularity. Paid data providers cost ₹500-2000/month. For backtesting, we generate realistic synthetic options data by applying Black-Scholes pricing to actual Nifty spot price history (which IS freely available via Kite historical data API).

**Class: SyntheticDataGenerator**

```python
class SyntheticDataGenerator:

    def __init__(self, iv_calculator: IVCalculator):
        self.iv_calc = iv_calculator

    def generate_historical_chains(self, spot_history: pd.DataFrame,
                                    vix_history: pd.DataFrame,
                                    symbol: str = "NIFTY") -> None:
        """
        Generates daily option chain snapshots for backtesting.

        INPUT:
          spot_history: DataFrame with columns [date, open, high, low, close]
                        from data_fetcher.get_nifty_price_history()
          vix_history:  DataFrame with columns [date, vix]
                        — can use actual historical VIX data from NSE or
                        — approximate from spot returns (see _estimate_vix below)

        ALGORITHM:
        For each trading day in spot_history:
          1. Get spot close price for that day
          2. Get VIX for that day (use as ATM IV baseline)
          3. Determine all active expiry dates (monthly, last Thursday of month)
          4. For each active expiry:
               a. Generate strikes: ATM ± 20 strikes at 50-point intervals for Nifty
               b. For each strike, calculate:
                    - Moneyness = strike / spot_close
                    - IV = apply volatility smile/skew model (see _apply_vol_skew)
                    - Time to expiry in years
                    - BS price for CE and PE using iv_calculator._bs_price()
                    - Add realistic noise: ± uniform(0.5, 2.0) rupees
                    - Bid = price - spread/2, Ask = price + spread/2
                    - Spread = max(0.50, price * 0.02)  (2% of price, min Rs 0.50)
                    - Delta, Gamma from iv_calculator
                    - OI = synthetic (higher near ATM, lower at wings)

          5. Save each day's chain as: data/historical/{symbol}_chain_{date}.csv

        OUTPUT columns per row:
          date, symbol, expiry, strike, option_type, bid, ask, ltp, close,
          iv, delta, gamma, theta, vega, oi, volume, underlying_value

        IMPORTANT: This is synthetic data for strategy validation only.
        Before deploying real capital, validate with a paid data source or paper trading.
        """

    def _apply_vol_skew(self, atm_iv, moneyness, dte) -> float:
        """
        Realistic IV smile/skew model for Indian index options.

        Model:
          skew_factor = -0.15 * (moneyness - 1.0)   # puts more expensive (negative skew)
          smile_factor = 0.10 * (moneyness - 1.0)**2  # wings more expensive
          term_adjustment = 1.0 / (1.0 + dte/365)     # skew flattens with longer DTE

          adjusted_iv = atm_iv * (1 + (skew_factor + smile_factor) * term_adjustment)
          return max(adjusted_iv, 0.05)  # floor at 5% IV
        """

    def _generate_monthly_expiries(self, start_date, end_date) -> list:
        """
        Return list of last-Thursday-of-month dates between start and end.
        These are the NSE monthly expiry dates for Nifty.
        If last Thursday is a holiday, use previous trading day.
        """

    def _generate_synthetic_oi(self, strike, underlying, total_oi_atm=50000) -> int:
        """
        OI is highest at ATM, decays at wings.
        Formula: oi = total_oi_atm * exp(-0.5 * ((strike - underlying) / (underlying * 0.05))^2)
        Returns integer, minimum 100.
        """

    def _estimate_vix_from_returns(self, spot_history: pd.DataFrame,
                                    window=21) -> pd.DataFrame:
        """
        If actual VIX history is unavailable, estimate from realised volatility.

        annualised_vol = spot_history['close'].pct_change().rolling(window).std() * sqrt(252)
        vix_estimate = annualised_vol * 100 * 1.15  # VIX typically ~15% above realised vol

        Returns DataFrame with columns [date, vix]
        """

    def validate_synthetic_data(self, chain_df: pd.DataFrame) -> dict:
        """
        Sanity checks on generated data:
          1. All CE prices decrease as strike increases (for same expiry)
          2. All PE prices increase as strike increases (for same expiry)
          3. Put-call parity holds within ±5% tolerance
          4. No negative prices
          5. ATM delta ≈ 0.50 (within 0.05)
          6. IV > 0 for all rows

        Returns dict: {"passed": bool, "failures": list of failure descriptions}
        """
```

### 4.6 Phase 1 Tests — All Must Pass Before Proceeding

```python
# tests/test_data_fetcher.py

def test_get_option_chain_returns_expected_structure():
    """Uses mocked KiteConnect to verify chain structure."""
    fetcher = DataFetcher(mock_kite)
    chain = fetcher.get_option_chain("NIFTY")
    assert "underlying_value" in chain
    assert chain["underlying_value"] > 10000
    assert len(chain["records"]) > 50

def test_get_india_vix_returns_float():
    fetcher = DataFetcher(mock_kite)
    vix = fetcher.get_india_vix()
    assert isinstance(vix, float)
    assert 5.0 < vix < 100.0

def test_cache_used_when_api_fails(monkeypatch):
    # monkeypatch kite.quote to raise NetworkError
    # assert returns cached data without raising
    pass

# tests/test_iv_calculator.py

def test_bs_price_matches_known_values():
    """Verify Black-Scholes implementation against known analytical results."""
    calc = IVCalculator()
    # Known: S=100, K=100, T=1, r=0.05, sigma=0.20, CE -> price ≈ 10.45
    price = calc._bs_price(100, 100, 1.0, 0.05, 0.20, "CE")
    assert abs(price - 10.45) < 0.10

def test_iv_rank_returns_value_between_0_and_100():
    calc = IVCalculator()
    rank = calc.calculate_iv_rank("NIFTY", current_iv=20.0)
    assert 0 <= rank <= 100

def test_greeks_calculation_within_tolerance():
    # Known values: ATM call, 30 days, IV=20, underlying=22000
    calc = IVCalculator()
    greeks = calc.calculate_greeks(22000, 22000, 30/365, 0.20, "CE")
    assert 0.45 < greeks["delta"] < 0.55  # ATM delta ~0.50

def test_put_delta_is_negative():
    calc = IVCalculator()
    greeks = calc.calculate_greeks(22000, 22000, 30/365, 0.20, "PE")
    assert -0.55 < greeks["delta"] < -0.45  # ATM put delta ~-0.50

def test_implied_vol_roundtrips():
    """Price with known vol, then solve back — should recover original vol."""
    calc = IVCalculator()
    price = calc._bs_price(22000, 22000, 30/365, 0.065, 0.20, "CE")
    recovered_iv = calc._implied_vol(price, 22000, 22000, 30/365, 0.065, "CE")
    assert abs(recovered_iv - 0.20) < 0.001

def test_find_strike_by_delta_returns_correct_strike():
    # Use fixture option chain
    # At 16 delta, returned strike should be roughly 5-8% OTM
    pass

# tests/test_synthetic_data.py

def test_synthetic_chain_structure():
    """Generated chain has all required columns."""
    gen = SyntheticDataGenerator(IVCalculator())
    # Use 5 days of fixture spot data
    gen.generate_historical_chains(fixture_spot, fixture_vix)
    chain = pd.read_csv("data/historical/NIFTY_chain_2023-01-02.csv")
    assert set(["strike", "option_type", "ltp", "iv", "delta"]).issubset(chain.columns)

def test_synthetic_data_passes_validation():
    gen = SyntheticDataGenerator(IVCalculator())
    gen.generate_historical_chains(fixture_spot, fixture_vix)
    chain = pd.read_csv("data/historical/NIFTY_chain_2023-01-02.csv")
    result = gen.validate_synthetic_data(chain)
    assert result["passed"] is True

def test_put_call_parity_holds():
    """C - P ≈ S - K*e^(-rT) within tolerance."""
    gen = SyntheticDataGenerator(IVCalculator())
    # Verify on ATM strike
    pass
```

---

## 5. PHASE 2 — STRATEGY ENGINE

### 5.1 src/strategy_ic.py

**Class: IronCondorStrategy**

**check_entry_conditions(market_data) -> EntrySignal**

Returns EntrySignal(should_enter: bool, reason: str, blocking_conditions: list)

Apply gates in this order. Short-circuit and return False on first failure:

```
Gate 1: market_data["iv_rank"] >= IC_MIN_IV_RANK (30)
  FAIL message: "IV Rank {x:.0f} below minimum 30 — premium not rich enough"

Gate 2: market_data["india_vix"] <= VIX_MAX_FOR_IC (25)
  FAIL message: "India VIX {x:.1f} above maximum 25 — too volatile for IC"

Gate 3: Days to next monthly expiry must be between 30 and 45
  Calculate using: next_monthly_expiry_date - today
  FAIL message: "No expiry in 30-45 DTE window — wrong time of month"

Gate 4: Count open IC trades in DB with status=OPEN < IC_MAX_OPEN_POSITIONS (2)
  FAIL message: "Maximum 2 open IC positions already active"

Gate 5: No event in config/events_calendar.json within 25 days
  Load events JSON, check all dates within today + 25 days
  FAIL message: "Major event on {date}: {name} — avoid holding IC through event"

Gate 6: Account drawdown < ACCOUNT_DRAWDOWN_STOP (5%)
  Query DB: (current_account_value - starting_capital) / starting_capital
  FAIL message: "Account drawdown exceeds 5% — all trading suspended"
```

**generate_trade_structure(option_chain, underlying_price) -> TradeStructure**

```python
# Step-by-step calculation — implement exactly:

short_call_strike = find_strike_by_delta(chain, 0.16, "CE")
short_put_strike  = find_strike_by_delta(chain, 0.16, "PE")
long_call_strike  = short_call_strike + IC_WING_WIDTH_POINTS  # +500
long_put_strike   = short_put_strike  - IC_WING_WIDTH_POINTS  # -500

# Get mid prices (average of bid and ask) for all 4 legs
short_call_mid = get_mid_price(chain, short_call_strike, "CE")
short_put_mid  = get_mid_price(chain, short_put_strike,  "PE")
long_call_mid  = get_mid_price(chain, long_call_strike,  "CE")
long_put_mid   = get_mid_price(chain, long_put_strike,   "PE")

net_premium = short_call_mid + short_put_mid - long_call_mid - long_put_mid

max_profit_per_lot = net_premium * NIFTY_LOT_SIZE
max_loss_per_lot   = (IC_WING_WIDTH_POINTS - net_premium) * NIFTY_LOT_SIZE

profit_target_close_price = net_premium * (1 - IC_PROFIT_TARGET_PCT)
stop_loss_close_price     = net_premium * IC_STOP_LOSS_MULTIPLIER

# Validation — raise InvalidTradeStructureError if:
#   net_premium <= 0              (must collect premium, not pay it)
#   max_loss_per_lot > TOTAL_CAPITAL * IC_MAX_PCT_CAPITAL_PER_TRADE
```

**check_exit_conditions(position, current_data) -> ExitSignal**

Returns ExitSignal(should_exit: bool, exit_type: str, urgency: str, message: str)

```python
# Check in this priority order:

# 1. STOP LOSS (check first — highest priority)
current_close_cost = get_current_close_cost(position, current_data)
if current_close_cost >= position.entry_premium * IC_STOP_LOSS_MULTIPLIER:
    return ExitSignal(True, "STOP_LOSS", "IMMEDIATE",
        "Loss exceeds 2x premium. Close ALL legs with market orders NOW.")

# 2. TIME STOP
dte = (position.expiry_date - datetime.now()).days
if dte <= IC_TIME_STOP_DTE:
    return ExitSignal(True, "TIME_STOP", "TODAY",
        f"21 DTE reached ({dte} days left). Close by 3 PM today.")

# 3. PROFIT TARGET
profit_pct = 1 - (current_close_cost / position.entry_premium)
if profit_pct >= IC_PROFIT_TARGET_PCT:
    return ExitSignal(True, "PROFIT_TARGET", "TODAY",
        f"Profit target reached at {profit_pct:.0%}. Close and consider re-entry.")

# 4. DEFAULT
return ExitSignal(False, "NONE", "MONITOR", "Position within parameters.")
```

### 5.2 src/strategy_cal.py

**Class: CalendarSpreadStrategy**

**check_entry_conditions(market_data) -> EntrySignal**

```
Gate 1: india_vix <= VIX_HIGH_THRESHOLD (28)
  FAIL message: "VIX {x:.1f} above 28 — back-month option too expensive"

Gate 2: No event within 7 days (shorter window than IC)
  FAIL message: "Event in {x} days: {name} — wait until after"

Gate 3: Open calendar positions < CAL_MAX_OPEN_POSITIONS (2)
  FAIL message: "Maximum 2 open calendar positions reached"

Gate 4: Back-month option with 60-75 DTE exists AND front-month option with 20-35 DTE exists
  FAIL message: "No back-month expiry in 60-75 DTE window or no front-month in 20-35 DTE window"
```

**generate_trade_structure(option_chain, underlying_price) -> CalendarTradeStructure**

```python
# ATM strike selection
strike = round(underlying_price / 100) * 100
# Examples: 22150 -> 22200, 22050 -> 22000

# Find back month: first expiry with DTE between 60 and 75
back_month_expiry = find_expiry_in_dte_range(chain, 60, 75)

# Find front month: nearest MONTHLY expiry with DTE between 20 and 35
# NOTE: Nifty weekly expiries were discontinued in late 2024.
# Front month now uses the nearest monthly expiry instead of weeklies.
front_month_expiry = find_expiry_in_dte_range(chain,
    CAL_FRONT_MONTH_MIN_DTE, CAL_FRONT_MONTH_MAX_DTE)

back_month_cost      = get_mid_price(chain, strike, "CE", back_month_expiry)
front_month_premium  = get_mid_price(chain, strike, "CE", front_month_expiry)

net_debit   = back_month_cost - front_month_premium
max_loss    = net_debit * NIFTY_LOT_SIZE  # defined from day one

centre_trigger_points = underlying_price * CAL_MAX_MOVE_PCT_TO_ADJUST
```

**DESIGN NOTE — Monthly vs Weekly Front Month:**
With monthly front months (20-35 DTE), the calendar rolls less frequently (once per month instead of weekly). This means:
- Less brokerage paid on rolls (fewer transactions)
- Each front month premium collected is larger (more DTE = more theta)
- But theta decay is slower at 20+ DTE compared to 7 DTE
- Net effect: slightly lower annualised theta income, but lower costs and less operational complexity
- The strategy remains structurally sound — it profits from the IV differential between front and back months

**check_roll_conditions(position, current_data) -> RollSignal**

```python
# Returns RollSignal(should_roll, action, message)
# Check in this order:

front_month_dte = (position.front_month_expiry - datetime.now()).days

if front_month_dte <= 3:
    # Monthly expiry approaching — roll to next month
    return RollSignal(True, "ROLL_FRONT",
        "Front month expiring in 3 days. Sell next monthly expiry immediately.")

if front_month_profit_pct >= 0.50:
    return RollSignal(True, "ROLL_FRONT",
        "Front month at 50% profit. Early roll to next monthly to reset theta clock.")

back_month_dte = (position.back_month_expiry - datetime.now()).days
if back_month_dte <= CAL_BACK_MONTH_CLOSE_DTE:
    return RollSignal(True, "CLOSE_BACK_MONTH",
        "Back month at 25 DTE. Close entire position now.")

if back_month_iv_expansion_pct >= 30:
    return RollSignal(True, "HARVEST_AND_CLOSE",
        "Back month gained 30%+ from IV expansion. Harvest this bonus.")

return RollSignal(False, "NONE", "Position healthy.")
```

**check_adjustment_conditions(position, current_data) -> AdjustmentSignal**

```python
move_pct = abs(current_price - position.strike) / position.strike

if move_pct >= CAL_MAX_MOVE_PCT_TO_CLOSE:     # 4%
    return AdjustmentSignal(True, "CLOSE", "IMMEDIATE",
        f"Market moved {move_pct:.1%} from strike. Close entire position.")

if move_pct >= CAL_MAX_MOVE_PCT_TO_ADJUST:    # 2%
    return AdjustmentSignal(True, "CENTRE", "TODAY",
        f"Market moved {move_pct:.1%}. Centre calendar at new ATM.")

return AdjustmentSignal(False, "NONE", "MONITOR", "Within acceptable range.")
```

### 5.3 Phase 2 Tests — All Must Pass

```python
# IC entry gate tests
def test_ic_rejects_low_iv_rank():         # IVR=25 -> should_enter=False
def test_ic_rejects_high_vix():             # VIX=28 -> should_enter=False
def test_ic_rejects_insufficient_dte():    # 20 DTE -> should_enter=False
def test_ic_rejects_event_proximity():     # RBI in 3 days -> should_enter=False
def test_ic_accepts_all_valid_conditions():# All green -> should_enter=True

# IC exit tests
def test_ic_stop_loss_at_2x_premium():    # loss=2x -> exit_type=STOP_LOSS
def test_ic_time_stop_at_21_dte():         # dte=21 -> exit_type=TIME_STOP
def test_ic_profit_target_at_50_pct():    # profit=52% -> exit_type=PROFIT_TARGET

# Structure validation
def test_trade_structure_max_loss_within_capital_limit():
def test_trade_structure_rejects_negative_premium():
```

---

## 6. PHASE 3 — BACKTESTING ENGINE

### 6.1 src/backtester.py

**Class: Backtester**

**run_ic_backtest(symbol, from_date, to_date, params=None) -> BacktestResult**

```python
# ALGORITHM — implement exactly in this order:

# 1. Load price history for symbol from data/historical or fetch
#    IMPORTANT: Historical options chain data comes from SyntheticDataGenerator.
#    Before running backtest, ensure synthetic chains have been generated:
#      gen = SyntheticDataGenerator(IVCalculator())
#      gen.generate_historical_chains(spot_history, vix_history)
#    The backtester loads from data/historical/{symbol}_chain_{date}.csv files.
# 2. Get list of all monthly expiry dates in the date range

# 3. For each month in the range:
#    a. Entry date = 1st trading day of month
#    b. Calculate IV Rank for that date
#    c. If IV Rank < IC_MIN_IV_RANK: record "no_entry" for this month, continue
#    d. If IV Rank sufficient:
#         - Get option chain for entry date
#         - Calculate 16-delta strikes
#         - Get close prices for all 4 legs (not mid — use close for conservative estimate)
#         - Subtract slippage immediately: 4 legs x 2 sides x Rs 2/unit x lot_size
#         - Store trade dict with all entry details

#    e. Simulate day by day after entry:
#         - Get option chain for each subsequent day
#         - Calculate current cost to close position
#         - Check exit conditions (profit target / time stop / stop loss)
#         - When exit triggered: record exit, calculate net P&L, break inner loop

# 4. After all months processed: calculate aggregate BacktestResult

# MANDATORY — Cost deduction per trade:
brokerage   = 8 * COST_BROKERAGE_PER_ORDER * (1 + COST_BROKERAGE_GST_RATE)  # Rs 188.80
stt         = (short_call_mid + short_put_mid) * COST_STT_SELL_RATE * lot_size
              # COST_STT_SELL_RATE = 0.000625 (0.0625%, Budget 2024 rate)
nse         = total_premium_turnover * COST_NSE_EXCHANGE_RATE
slippage    = 4 * 2 * COST_SLIPPAGE_PER_UNIT_PER_LEG * lot_size  # Rs 400 for 1 lot
total_costs = brokerage + stt + nse + slippage
net_pnl     = gross_pnl - total_costs

# If costs are not deducted the backtest will overstate returns.
# Claude Code must assert total_costs > 0 for every trade.
```

**BacktestResult — all fields:**

```python
@dataclass
class BacktestResult:
    total_trades:       int
    winning_trades:     int
    losing_trades:      int
    no_entry_months:    int       # months where IV Rank too low
    win_rate:           float     # winning_trades / total_trades
    avg_winner_net:     float     # average net P&L of winning trades in Rs
    avg_loser_net:      float     # average net P&L of losing trades in Rs (negative)
    expected_value:     float     # (win_rate * avg_winner) + (loss_rate * avg_loser)
    profit_factor:      float     # sum(winners) / abs(sum(losers))
    max_drawdown_pct:   float     # worst peak-to-trough as decimal
    sharpe_ratio:       float     # annualised risk-adjusted return
    total_net_pnl:      float     # total net P&L in Rs
    cagr:               float     # compound annual growth rate
    monthly_returns:    list      # list of (month_str, net_pnl) tuples
    trade_log:          pd.DataFrame  # full trade-by-trade detail
    regime_breakdown:   dict      # {"SIDEWAYS": 0.82, "TRENDING": 0.64, "HIGH_VOL": 0.71}
```

**GO / NO-GO Verdict Logic:**

```python
def generate_backtest_report(self, result: BacktestResult) -> str:
    """
    Print to console via Rich AND save to data/backtest_report_{timestamp}.txt
    
    GO criteria — ALL must pass:
      result.win_rate >= 0.72
      result.expected_value > 0
      result.max_drawdown_pct < 0.15
      result.profit_factor > 1.3
    
    If any fail: verdict = "NO-GO — {list failing criteria}"
    If all pass: verdict = "GO — proceed to paper trading"
    """
```

**run_parameter_sweep(symbol, from_date, to_date, param_grid) -> pd.DataFrame**

```python
# param_grid example:
# {
#   "ic_short_delta":       [0.10, 0.16, 0.20],
#   "ic_profit_target_pct": [0.25, 0.50, 0.75],
#   "ic_min_iv_rank":       [20, 30, 40]
# }
# Run cartesian product of all combinations
# For each combination: call run_ic_backtest() with params overriding settings
# Return DataFrame ranked by Sharpe ratio descending
# Save to: data/backtest_sweep_{timestamp}.csv
```

### 6.2 Phase 3 Tests

```python
def test_backtest_costs_always_deducted():
    # Run backtest on synthetic fixture data
    result = backtester.run_ic_backtest("NIFTY", "2023-01-01", "2023-12-31")
    for trade in result.trade_log.to_dict("records"):
        assert trade["total_costs"] > 0

def test_backtest_ev_positive_on_good_params():
    result = backtester.run_ic_backtest(...)
    assert result.expected_value > 0

def test_no_entry_months_recorded_when_iv_rank_low():
    # Fixture data where IV Rank is always below 30
    result = backtester.run_ic_backtest(...)
    assert result.no_entry_months > 0
    assert result.total_trades == 0
```

---

## 7. PHASE 4 — BROKER INTEGRATION

### 7.1 Zerodha Setup Requirements

Before broker_zerodha.py can be tested, the user must:
1. Create a Zerodha Kite Connect developer app at developers.kite.trade
2. Add ZERODHA_API_KEY and ZERODHA_API_SECRET to .env
3. Run: python cli.py login — this triggers the daily browser login

### 7.2 src/broker_zerodha.py

**Class: ZerodhaBroker**

```python
from kiteconnect import KiteConnect
from config import settings
from db import crud

class ZerodhaBroker:

    def __init__(self):
        self.kite = KiteConnect(api_key=settings.ZERODHA_API_KEY)
        self.access_token = self._load_or_refresh_token()
        self.kite.set_access_token(self.access_token)

    def _load_or_refresh_token(self) -> str:
        """
        1. Query DB zerodha_sessions table for today's date
        2. If valid token found: return it
        3. If no token for today:
             a. Print login URL: print(self.kite.login_url())
             b. Print instruction: "Open this URL, log in, paste the request_token here:"
             c. request_token = input("request_token: ").strip()
             d. session = self.kite.generate_session(request_token, settings.ZERODHA_API_SECRET)
             e. Save to DB with today's date
             f. Return session["access_token"]
        """

    def get_positions(self) -> list:
        """
        Returns list of Position objects from Zerodha API.
        Map Zerodha response fields to our internal Position model.
        Returns empty list if no positions (not None).
        """

    def place_order(self, symbol, transaction_type, quantity, price) -> dict:
        """
        ALWAYS use LIMIT orders. Market orders ONLY in stop_loss_close().

        symbol format: "NIFTY24MAR22600CE" — convert from our internal format
        transaction_type: "BUY" or "SELL"
        product: "NRML" (normal/carryforward) for all positional options trades

        CRITICAL: Do NOT use "MIS" (intraday) — IC and Calendar positions are held
        for weeks/months. MIS would auto-square-off at 3:20 PM the same day.

        MARGIN CHECK: Before placing, call self.check_margin(symbol, transaction_type,
          quantity, price) to verify sufficient margin. Abort if insufficient.

        If not filled in 2 minutes:
          Improve price by Rs 1 (sell lower / buy higher)
          Retry up to 3 times
          If still unfilled after 3 attempts: cancel, return failure result

        Log every order attempt to db order_log table.

        Error handling:
          MarginException -> log, return OrderResult(success=False, error="Insufficient margin")
          TokenException  -> refresh token, retry once
          NetworkError    -> log, return OrderResult(success=False, error="Network error")
        """

    def stop_loss_close(self, position) -> bool:
        """
        EMERGENCY ONLY. Called when stop loss breached.
        Uses MARKET orders — acceptable here because speed matters over price.
        
        Steps:
        1. Log "EMERGENCY STOP LOSS CLOSE — position {id}" to console and DB
        2. For each leg in position: place MARKET order to close
        3. Return True if all legs closed
        4. If any leg fails: log error, send desktop alert, return False
        """

    def get_option_ltp(self, symbol, strike, expiry, option_type) -> float:
        """
        Get last traded price for a specific option.
        Used for real-time position P&L calculation in position_monitor.
        """

    def check_margin(self, symbol, transaction_type, quantity, price) -> dict:
        """
        Use Kite Connect margin API instead of hardcoded estimates.

        Call: self.kite.order_margins([{
            "exchange": "NFO",
            "tradingsymbol": symbol,
            "transaction_type": transaction_type,
            "variety": "regular",
            "product": "NRML",
            "order_type": "LIMIT",
            "quantity": quantity,
            "price": price
        }])

        Returns dict:
          required_margin: float — actual SPAN + exposure margin
          available_margin: float — from kite.margins()["equity"]["available"]["live_balance"]
          sufficient: bool — available >= required
          shortfall: float — max(0, required - available)

        NOTE: Actual margin fluctuates with VIX. Always check before placing orders.
        Hardcoded fallback values (Rs 35,000/lot for IC, Rs 20,000/lot for CAL) are
        used ONLY when the margin API is unreachable.
        """
```

---

## 8. PHASE 5 — POSITION MONITOR AND ALERTS

### 8.1 src/position_monitor.py

**Class: PositionMonitor**

```python
class PositionMonitor:

    def start_monitoring_loop(self):
        """
        Use APScheduler to run _monitoring_tick() every 60 seconds.
        Only schedule during market hours: 09:15 to 15:30 IST (settings.TIMEZONE).
        Do not run on weekends or exchange holidays.
        Run inside the FastAPI process — not a separate process.
        """

    def _monitoring_tick(self):
        """
        Called every 60 seconds. Do all of:
        
        1. Fetch current positions from Zerodha API
        
        2. For each open IC position in DB:
             a. Get current close cost via broker.get_option_ltp() for all 4 legs
             b. Calculate P&L percentage
             c. Call strategy_ic.check_exit_conditions()
             d. If ExitSignal.should_exit = True:
                  send_alert(signal.message, signal.urgency)
                  log to alert_log table
        
        3. For each open Calendar position in DB:
             a. Check roll conditions via strategy_cal.check_roll_conditions()
             b. Check adjustment conditions via strategy_cal.check_adjustment_conditions()
             c. If action needed: send_alert()
        
        4. Calculate portfolio-level Greeks:
             total_delta = sum(position.current_delta for all positions)
             total_theta = sum(position.current_theta for all positions)
             If abs(total_delta) > 5: send_alert("Portfolio delta > 5 — becoming directional", "TODAY")
             If total_theta < 0: send_alert("Net theta negative — investigate", "IMMEDIATE")
        
        5. Save portfolio snapshot to DB with timestamp
        """

    def send_alert(self, message, urgency):
        """
        PRIMARY channel: Telegram Bot API (works even when PC is off).
        SECONDARY channel: plyer desktop notification (local backup).

        urgency = "IMMEDIATE":
          send_telegram_message(f"🚨 URGENT: {message}")
          plyer.notification.notify(title="Quant System ALERT", message=message)
          print alert to console in red via Rich
          log to alert_log DB table

        urgency = "TODAY":
          send_telegram_message(f"⚠️ ACTION TODAY: {message}")
          print to console in yellow via Rich
          log to alert_log DB table

        urgency = "MONITOR":
          log to alert_log DB table only (no user interruption)
        """

    def send_telegram_message(self, message: str):
        """
        POST https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage
        Body: {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}

        Use httpx (already a dependency). Fire-and-forget — do not block on failure.
        If Telegram fails, log warning and continue (plyer is the fallback).
        """
```

---

## 9. PHASE 6 — ADJUSTMENT ENGINE

### 9.1 src/adjustment_engine.py

**Class: AdjustmentEngine**

**evaluate_and_suggest_adjustment(position, current_data) -> AdjustmentPlan**

Returns AdjustmentPlan containing:
- adjustment_needed: bool
- action: str
- rationale: str
- estimated_cost: float
- orders_to_place: list of OrderRequest objects with exact legs
- new_stop_loss: float
- new_profit_target: float

**IC Adjustment Decision Tree — implement exactly:**

```python
def _evaluate_ic_adjustment(self, position, current_data) -> AdjustmentPlan:
    
    dte = (position.expiry_date - datetime.now()).days
    current_price = current_data["underlying_value"]
    
    # Step 1: DTE check — abort adjustment if too close to expiry
    if dte < 10:
        return AdjustmentPlan(
            adjustment_needed=True,
            action="CLOSE_ENTIRE_IC",
            rationale="DTE below 10. Gamma risk too high. Close all legs.",
            orders_to_place=build_full_close_orders(position)
        )
    
    # Step 2: Loss level check
    current_close_cost = get_current_close_cost(position, current_data)
    if current_close_cost > position.entry_premium * 1.5:
        return AdjustmentPlan(
            adjustment_needed=True,
            action="CLOSE_ENTIRE_IC",
            rationale="Loss exceeds 1.5x premium. Approaching stop loss. Close now.",
            orders_to_place=build_full_close_orders(position)
        )
    
    # Step 3: Identify tested side
    distance_to_call = position.short_call_strike - current_price
    distance_to_put  = current_price - position.short_put_strike
    
    if distance_to_call < 300:
        # Call side tested — build roll-up orders
        new_short_call = position.short_call_strike + 500
        new_long_call  = new_short_call + IC_WING_WIDTH_POINTS
        orders = [
            OrderRequest("BUY",  position.short_call_strike, "CE", position.expiry),
            OrderRequest("SELL", new_short_call,              "CE", position.expiry),
            OrderRequest("BUY",  position.long_call_strike,   "CE", position.expiry),
            OrderRequest("SELL", new_long_call,               "CE", position.expiry),
        ]
        # Also check if put side can be harvested
        put_profit_pct = get_put_side_profit_pct(position, current_data)
        if put_profit_pct >= 0.85:
            orders += build_put_side_close_orders(position)
        
        return AdjustmentPlan(
            adjustment_needed=True,
            action="ROLL_CALL_SIDE_UP",
            rationale=f"Short call at {position.short_call_strike} within 300pts. Rolling to {new_short_call}.",
            orders_to_place=orders,
            new_stop_loss=recalculate_stop_loss(position, orders, current_data)
        )
    
    elif distance_to_put < 300:
        # Mirror logic for put side
        pass
    
    else:
        return AdjustmentPlan(adjustment_needed=False, action="NONE", rationale="Position healthy.")
```

**Calendar Adjustment Decision Tree:**

```python
def _evaluate_cal_adjustment(self, position, current_data) -> AdjustmentPlan:
    
    current_price = current_data["underlying_value"]
    move_pct = abs(current_price - position.strike) / position.strike
    
    if move_pct >= CAL_MAX_MOVE_PCT_TO_CLOSE:       # 4%
        return AdjustmentPlan(
            adjustment_needed=True,
            action="CLOSE_ENTIRE_CAL",
            rationale=f"Market moved {move_pct:.1%} — structural advantage gone. Close.",
            orders_to_place=build_full_cal_close_orders(position)
        )
    
    if move_pct >= CAL_MAX_MOVE_PCT_TO_ADJUST:       # 2%
        new_strike = round(current_price / 100) * 100
        orders = [
            OrderRequest("BUY",  position.front_month_strike, "CE", position.front_month_expiry),
            OrderRequest("SELL", new_strike,                   "CE", position.front_month_expiry),
        ]
        return AdjustmentPlan(
            adjustment_needed=True,
            action="CENTRE_CALENDAR",
            rationale=f"Market at {current_price:.0f}. Recentring front month from {position.front_month_strike} to {new_strike}.",
            orders_to_place=orders
        )
    
    if position.front_month_dte <= 3:
        next_front_expiry = get_next_monthly_expiry()  # Monthly, not weekly
        orders = [
            OrderRequest("BUY",  position.front_month_strike, "CE", position.front_month_expiry),
            OrderRequest("SELL", position.front_month_strike, "CE", next_front_expiry),
        ]
        return AdjustmentPlan(
            adjustment_needed=True,
            action="ROLL_FRONT_MONTH",
            rationale="Front month expiring in 3 days. Selling next monthly expiry.",
            orders_to_place=orders
        )
    
    return AdjustmentPlan(adjustment_needed=False, action="NONE", rationale="Calendar healthy.")
```

---

## 10. PHASE 7 — COST AND P&L ENGINE

### 10.1 src/cost_engine.py

**Class: CostEngine**

```python
class CostEngine:

    def calculate_trade_costs(self, strategy, lots, gross_premium_per_unit,
                               num_legs, lot_size=25) -> TradeCosts:
        """
        Returns TradeCosts dataclass with all fields:

        brokerage      = num_legs * 2 * COST_BROKERAGE_PER_ORDER * lots
        brokerage_gst  = brokerage * COST_BROKERAGE_GST_RATE
        stt            = gross_premium_per_unit * COST_STT_SELL_RATE * lots * lot_size
                         # STT at 0.0625% on sell side premium (Budget 2024 rate)
        nse_charges    = gross_premium_per_unit * lots * lot_size * COST_NSE_EXCHANGE_RATE
        stamp_duty     = gross_premium_per_unit * lots * lot_size * COST_STAMP_DUTY_RATE
        slippage       = COST_SLIPPAGE_PER_UNIT_PER_LEG * num_legs * 2 * lots * lot_size
        margin         = estimate_margin_required(strategy, lots)
        margin_opp_cost = margin * COST_LIQUID_FUND_RATE_ANNUAL / 12

        total_costs    = sum of all above
        net_per_unit   = gross_premium_per_unit - (total_costs / (lots * lot_size))

        NOTE ON STT: If options expire ITM, STT is charged at the higher
        COST_STT_ITM_EXPIRY_RATE (0.125%) on intrinsic value. Always close
        ITM positions before expiry to avoid this. The cost_engine should
        flag ITM positions approaching expiry.

        EXPECTED VALUES FOR 1 LOT NIFTY IC AT Rs 106/unit GROSS PREMIUM:
          brokerage + GST : Rs 188.80
          STT             : Rs 16.56  (Rs 106 * 0.000625 * 25)
          NSE charges     : Rs 14.08
          slippage        : Rs 400.00  (4 legs * 2 * Rs 2 * 25)
          margin opp cost : Rs 216.67  (Rs 40000 * 6.5% / 12)
          TOTAL           : Rs 836.11
          NET PROFIT      : Rs 2650 - Rs 836 = Rs 1814
        """

    def estimate_margin_required(self, strategy, lots, broker=None) -> float:
        """
        PRIMARY: If broker (ZerodhaBroker) is available, use broker.check_margin()
        for real-time SPAN + exposure margin from Kite API.

        FALLBACK (if broker unavailable or API fails):
          Conservative hardcoded estimates:
          IC  (hedged with 500pt wings): Rs 35,000 per lot for Nifty
          CAL (long back month):         Rs 20,000 per lot for Nifty

        NOTE: Actual margin varies significantly with VIX. During high VIX,
        margin can be 50-100% higher. Always prefer the API-based check.
        """

    def get_minimum_viable_premium(self, strategy, lots) -> float:
        """
        Minimum gross premium/unit where net_per_unit > 0 after all costs.
        For 1-lot Nifty IC: approximately Rs 34/unit.
        Display this threshold in daily review — any premium below this, skip the trade.
        """
```

### 10.2 Phase 7 Tests

```python
def test_ic_1_lot_total_costs_within_expected_range():
    engine = CostEngine()
    costs = engine.calculate_trade_costs("IC", 1, 106.0, 4)
    assert 650 < costs.total_costs < 1000  # ~Rs 836 with updated STT 0.0625%

def test_net_premium_always_less_than_gross():
    engine = CostEngine()
    costs = engine.calculate_trade_costs("IC", 1, 106.0, 4)
    assert costs.net_per_unit < 106.0

def test_minimum_viable_premium_positive():
    engine = CostEngine()
    minimum = engine.get_minimum_viable_premium("IC", 1)
    assert minimum > 0
```

---

## 11. PHASE 8 — EDGE TRACKING ENGINE

### 11.1 src/edge_tracker.py

**Class: EdgeTracker**

```python
class EdgeTracker:

    def update_metrics(self, completed_trade):
        """Called after every trade close. Recalculate all metrics and save to DB."""

    def get_rolling_win_rate(self, last_n=20) -> float:
        """Query last N completed trades from DB. Return wins / n."""

    def get_rolling_profit_factor(self, last_n=20) -> float:
        """
        sum(net_pnl for winning trades) / abs(sum(net_pnl for losing trades))
        Query last N trades from DB.
        If no losses yet: return float('inf') and log "no losses in last N trades"
        """

    def get_regime_win_rates(self) -> dict:
        """
        Return dict with win rates per regime:
        {
          "SIDEWAYS": {"trades": 12, "win_rate": 0.83, "expected": 0.80},
          "TRENDING": {"trades": 5,  "win_rate": 0.60, "expected": 0.65},
          "HIGH_VOL": {"trades": 3,  "win_rate": 0.67, "expected": 0.68},
          "NORMAL":   {"trades": 8,  "win_rate": 0.75, "expected": 0.75}
        }
        """

    def evaluate_stop_signals(self) -> list:
        """
        Check all 5 conditions. Return list of active StopSignal objects (empty if healthy).
        
        Condition 1 — RED:
          if rolling_win_rate(20) < ROLLING_WIN_RATE_RED (0.58):
            StopSignal(type="RED", action="STOP_ALL_TRADING",
              message="Win rate critically low. No new trades for 4 weeks.")
        
        Condition 2 — YELLOW:
          elif rolling_win_rate(20) < ROLLING_WIN_RATE_YELLOW (0.62):
            StopSignal(type="YELLOW", action="HALF_SIZE",
              message="Win rate degraded. Reduce all position sizes by 50%.")
        
        Condition 3 — RED:
          if rolling_profit_factor(20) < PROFIT_FACTOR_RED (1.0):
            StopSignal(type="RED", action="STOP_ALL_TRADING",
              message="Profit factor below 1.0. Losing money in aggregate.")
        
        Condition 4 — YELLOW:
          For each regime with >= 10 trades:
            if actual_win_rate < expected_win_rate - 0.15:
              StopSignal(type="YELLOW", action="INVESTIGATE",
                message=f"{regime} win rate {actual:.0%} vs expected {expected:.0%}")
        
        Condition 5 — YELLOW:
          if india_vix > VIX_HIGH_THRESHOLD (28) for 3+ consecutive trading days:
            StopSignal(type="YELLOW", action="IC_PAUSE",
              message="VIX sustained above 28. Stop IC entries. Calendars only.")
        
        Return empty list if all conditions healthy.
        """
```

---

## 12. PHASE 9 — DAILY REVIEW CLI

### 12.1 cli.py (entry point)

```python
import typer
from cli.commands import app

if __name__ == "__main__":
    app()
```

### 12.2 cli/commands.py — All Commands

```python
app = typer.Typer()

@app.command()
def morning_review():
    """
    Run every trading day at 9:00 AM before market open.
    
    Output in this exact order:
    
    Section 1 — Header
      Date, Nifty level, India VIX, IV Rank (fetched live)
      Color code: Green if IV Rank > 30, Yellow if 20-30, Red if < 20
    
    Section 2 — Open Positions Table
      Columns: Strategy | Strikes | Expiry | DTE | Entry Premium | P&L% | Status
      Row color: GREEN = no action needed
                 YELLOW = watch (approaching threshold)
                 RED = act today (exit or adjust)
    
    Section 3 — Entry Signals
      IC: show each gate with checkmark or X and current value
      CAL: same
      If all gates green: "SIGNAL: ENTER NEW IC TODAY" (or CALENDAR)
      If any gate red: "NO SIGNAL — [failing gate reason]"
    
    Section 4 — Claude AI Action Plan
      Call claude_advisor.generate_daily_review() with current context
      Print structured output:
        Position 1: [HOLD / CLOSE_NOW / ADJUST: description]
        Position 2: [HOLD / CLOSE_NOW / ADJUST: description]
        New IC Trade: [ENTER / WAIT / SKIP with reason]
        New Calendar: [ENTER / WAIT / SKIP with reason]
        PRIORITY: [single sentence — the one thing to do today]
    
    Section 5 — Edge Metrics
      Rolling win rate (20 trades) with Green/Yellow/Red indicator
      Profit factor with Green/Yellow/Red indicator
      Any active stop signals shown prominently in red
    
    Section 6 — Upcoming Events
      All events from events_calendar.json within next 25 days
    """

@app.command()
def login():
    """Daily Zerodha token refresh. Run every morning before market-review."""
    broker = ZerodhaBroker()
    console.print("[green]Zerodha login complete.[/green]")

@app.command()
def backtest(
    from_date: str = typer.Option("2021-01-01", help="Start date YYYY-MM-DD"),
    to_date:   str = typer.Option("2023-12-31", help="End date YYYY-MM-DD"),
    strategy:  str = typer.Option("IC",         help="IC or CAL"),
    sweep:     bool = typer.Option(False,        help="Run parameter sweep")
):
    """Run historical backtest and show GO/NO-GO verdict."""

@app.command()
def execute_trade(
    trade_type: str = typer.Argument(help="IC or CAL")
):
    """
    Interactive trade entry.
    1. Fetch live option chain
    2. Generate trade structure with cost breakdown
    3. Display all details including estimated net profit
    4. Ask: "Execute? (y/n): "
    5. If y: place all orders via broker_zerodha
    6. Record to DB immediately
    """

@app.command()
def close_position(position_id: int):
    """Close a specific position by trade ID."""

@app.command()
def portfolio():
    """Show full portfolio with live Greeks and current P&L."""

@app.command()
def edge_report():
    """Display all edge tracking metrics and any active stop signals."""

@app.command()
def ask(question: str = typer.Argument(help="Question about your positions or strategy")):
    """Ask Claude a question about current positions or market conditions."""
```

---

## 13. PHASE 10 — DASHBOARD WEB UI

### 13.1 Frontend Setup

```bash
cd frontend
npm create vite@latest . -- --template react
npm install tailwindcss recharts axios dayjs
npx tailwindcss init
```

### 13.2 App.jsx — Five Tab Navigation

```
Tab 1: Dashboard
  - Nifty price badge — auto-refresh every 60 seconds via polling
  - India VIX and IV Rank badges with green/yellow/red colour coding
  - Open position cards showing P&L progress bars
  - Claude AI action plan scrollable text box
  - Edge metrics strip at bottom: win rate, profit factor, drawdown
  - Stop signal banner at very top if any active — red, cannot dismiss

Tab 2: Signals
  - IC entry gate checklist: each of 6 gates with current value and pass/fail
  - Calendar entry gate checklist: each of 4 gates
  - If all gates pass: show "PROPOSED TRADE" card with exact strikes and estimated profit
  - Instruction: "Run: python cli.py execute-trade IC to enter"

Tab 3: Backtest
  - Date range pickers (from_date, to_date)
  - Strategy selector: IC or CAL
  - Parameter set selector: base / conservative / aggressive / high_iv_only
  - "Run Backtest" button calling POST /api/backtest
  - Results panel: summary statistics table + equity curve (Recharts AreaChart)
  - Monthly returns heatmap (12 columns x N years, green/red cells)
  - GO / NO-GO verdict prominently displayed

Tab 4: Edge Tracker
  - 4 metric cards (win rate, profit factor, monthly return, max drawdown)
    Each card shows: current value, threshold levels, green/yellow/red status
  - Regime analysis table with actual vs expected win rate per regime
  - Stop signal history (last 10 alerts from DB)
  - Rolling win rate chart (Recharts LineChart, last 50 trades)

Tab 5: Trade Log
  - Sortable, filterable table of all trades from DB
  - Filters: date range, strategy (IC/CAL), outcome (win/loss/open)
  - Columns: ID, Strategy, Underlying, Entry Date, Strikes, IV Rank, Entry Premium, Exit Date, Exit Reason, Net P&L, Days, Regime
  - Summary row at bottom: total net P&L, win rate, profit factor
```

### 13.3 FastAPI Routers — All Endpoints

```
GET  /api/positions                  All open positions with live P&L
GET  /api/positions/{id}             Single position detail with full trade history
POST /api/positions/{id}/close       Trigger close for a specific position

GET  /api/signals/ic                 Current IC entry signal with all gate results
GET  /api/signals/cal                Current Calendar entry signal
GET  /api/signals/market             {nifty_level, india_vix, iv_rank, timestamp}

POST /api/backtest                   Run backtest — body: {strategy, from_date, to_date, params}
GET  /api/backtest/results           List all past backtest results with timestamps

GET  /api/review/daily               Trigger Claude AI daily review, return structured text

GET  /api/trades                     All trades, supports query params: strategy, outcome, from, to
GET  /api/trades/stats               Aggregate stats for edge tracker tab
```

### 13.4 api/main.py

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routers import positions, signals, backtest, review, trades

app = FastAPI(title="Quant Trading System", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Vite dev server
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(positions.router, prefix="/api/positions")
app.include_router(signals.router,   prefix="/api/signals")
app.include_router(backtest.router,  prefix="/api/backtest")
app.include_router(review.router,    prefix="/api/review")
app.include_router(trades.router,    prefix="/api/trades")
```

---

## 14. PHASE 11 — CLAUDE AI INTEGRATION

### 14.1 src/claude_advisor.py

```python
import anthropic
from config import settings

class ClaudeAdvisor:

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    SYSTEM_PROMPT = """You are a systematic quant trading assistant for a
    non-speculative options income system on Nifty 50. 
    
    STRATEGY RULES — never override these:
    - Iron Condor: Enter when IV Rank > 30, 16-delta strikes, 30-45 DTE
    - Exit IC at 50% profit, 21 DTE, or 2x premium stop loss — no exceptions
    - Calendar Spread: Enter any IV environment, ATM strike, 60-75 DTE back month
    - Close calendar back month at 25 DTE — no exceptions
    - Max 5% of total capital at risk per trade
    - NEVER suggest directional market predictions or bets
    - NEVER suggest overriding defined-risk principles
    - If a rule is clear, cite it and enforce it"""

    def generate_daily_review(self, context: dict) -> dict:
        """
        context dict must contain:
          nifty_level:          float
          india_vix:            float
          iv_rank:              float
          open_positions:       list of position dicts
          ic_signal:            EntrySignal object as dict
          cal_signal:           EntrySignal object as dict
          edge_metrics:         {win_rate, profit_factor}
          stop_signals:         list of active stop signal strings
          upcoming_events:      list of {date, name} dicts
          monthly_pnl:          float
        
        Prompt includes all context. Claude responds in structured format:
        
        ACTION_POSITION_1: [HOLD / CLOSE_NOW / ADJUST: description]
        ACTION_POSITION_2: [HOLD / CLOSE_NOW / ADJUST: description]
        NEW_IC_TRADE: [ENTER / WAIT: reason / SKIP: reason]
        NEW_CAL_TRADE: [ENTER / WAIT: reason / SKIP: reason]
        PRIORITY_ACTION: [single sentence]
        RISK_NOTE: [risk flag or empty]
        REASONING: [2-3 sentences]
        
        Parse response into dict and return it.
        
        Fallback on AnthropicAPIError:
          Return rule-based summary built from signal objects only.
          Do not crash. Always return a dict with all required keys.
        """

    def generate_adjustment_advice(self, position: dict, market_data: dict) -> str:
        """
        Called when adjustment_engine detects a trigger.
        Provides nuanced context-aware advice on top of the deterministic rules.
        """

    def answer_trade_question(self, question: str, context: dict) -> str:
        """
        Free-form Q&A. Always grounds answer in strategy rules.
        Used by: python cli.py ask "your question"
        """
```

---

## 15. DATABASE SCHEMA

### 15.0 SQLite Configuration — CRITICAL

**WAL Mode:** SQLite must be configured in WAL (Write-Ahead Logging) mode to support concurrent reads from FastAPI while the position_monitor writes every 60 seconds. Without WAL, you will get `database is locked` errors.

Add this to `db/__init__.py` or wherever the engine is created:

```python
from sqlalchemy import event, create_engine
from config import settings

engine = create_engine(settings.DATABASE_URL)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")  # wait up to 5s if locked
    cursor.close()
```

### 15.1 Alembic Migration — 001_initial_schema.py

Create all tables in one migration. Claude Code must implement all 6 SQLAlchemy models in db/models.py and generate this migration.

**Table: trades**

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | Auto-increment |
| trade_code | String UNIQUE | T001, T002... |
| strategy | String | "IC" or "CAL" |
| underlying | String | "NIFTY" |
| status | String | "OPEN" or "CLOSED" |
| entry_date | DateTime | When position opened |
| expiry_date | DateTime | Main expiry date |
| short_strike_1 | Integer | IC: short call |
| short_strike_2 | Integer | IC: short put |
| long_strike_1 | Integer | IC: long call wing |
| long_strike_2 | Integer | IC: long put wing |
| iv_rank_at_entry | Float | IV Rank when entered |
| india_vix_at_entry | Float | VIX when entered |
| entry_premium_per_unit | Float | Gross premium |
| net_premium_per_unit | Float | After estimated costs |
| lots | Integer | Default 1 |
| market_regime | String | SIDEWAYS/TRENDING/HIGH_VOL/NORMAL |
| exit_date | DateTime nullable | When position closed |
| exit_reason | String nullable | PROFIT_TARGET/TIME_STOP/STOP_LOSS/ADJUSTED |
| exit_price_per_unit | Float nullable | Cost to close |
| gross_pnl | Float nullable | Before costs |
| net_pnl | Float nullable | After all costs |
| days_in_trade | Integer nullable | entry to exit |
| brokerage_paid | Float nullable | Actual brokerage charged |
| stt_paid | Float nullable | Actual STT charged |
| slippage_estimate | Float nullable | Estimated slippage |
| total_costs | Float nullable | Sum of all costs |
| notes | Text nullable | Adjustments and observations |

**Table: calendar_cycles** — tracks each weekly roll within a calendar position

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| trade_id | Integer FK trades.id | Parent calendar position |
| cycle_number | Integer | 1 for first front month, 2 for second, etc |
| front_month_expiry | DateTime | Expiry of this cycle's front month |
| premium_collected | Float | Premium from selling this front month |
| exit_date | DateTime nullable | When this cycle's front was closed |
| exit_price | Float nullable | Price at close |
| cycle_pnl | Float nullable | Net P&L for this cycle |

**Table: edge_metrics** — snapshot saved after every trade close

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| snapshot_date | DateTime | When snapshot taken |
| rolling_win_rate_20 | Float | Win rate last 20 trades |
| rolling_profit_factor_20 | Float | Profit factor last 20 trades |
| total_trades_all_time | Integer | |
| ytd_net_pnl | Float | Year to date net P&L |
| regime_sideways_win_rate | Float nullable | |
| regime_trending_win_rate | Float nullable | |
| regime_highvol_win_rate | Float nullable | |

**Table: order_log** — every order placed, success or failure

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| trade_id | Integer FK nullable | Parent trade if known |
| zerodha_order_id | String nullable | Returned by Zerodha API |
| symbol | String | Option symbol |
| transaction_type | String | BUY or SELL |
| quantity | Integer | Number of units |
| price | Float | Requested limit price |
| order_type | String | LIMIT or MARKET |
| status | String | PLACED/FILLED/REJECTED/CANCELLED |
| fill_price | Float nullable | Actual fill price |
| slippage_actual | Float nullable | fill_price minus price |
| timestamp | DateTime | When order was placed |
| error_message | String nullable | Error on REJECTED status |

**Table: zerodha_sessions** — daily access tokens

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| date | Date UNIQUE | One row per calendar day |
| access_token | String | Zerodha access token |
| created_at | DateTime | When token was generated |

**Table: alert_log** — all system alerts

| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | |
| alert_type | String | EXIT_SIGNAL/ADJUSTMENT/STOP_SIGNAL/INFO |
| urgency | String | IMMEDIATE/TODAY/MONITOR |
| message | Text | Full alert message |
| position_id | Integer FK nullable | Related position if applicable |
| acknowledged | Boolean | Default False |
| created_at | DateTime | When alert was generated |

---

## 16. CONFIGURATION FILES

### 16.1 config/events_calendar.json

```json
{
  "events": [
    {"date": "2025-04-09", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2025-06-06", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2025-08-06", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2025-10-08", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2025-12-05", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2026-02-01", "name": "Union Budget",         "type": "BUDGET", "blackout_days_before": 5},
    {"date": "2026-02-06", "name": "RBI Monetary Policy", "type": "RBI", "blackout_days_before": 5},
    {"date": "2025-07-30", "name": "US Federal Reserve",  "type": "FED", "blackout_days_before": 3},
    {"date": "2025-09-17", "name": "US Federal Reserve",  "type": "FED", "blackout_days_before": 3}
  ],
  "note": "Update when RBI announces new dates. Check rbi.org.in for official schedule."
}
```

### 16.2 config/strategy_params.py

```python
PARAM_SETS = {
    "base": {
        "ic_short_delta":          0.16,
        "ic_profit_target_pct":    0.50,
        "ic_min_iv_rank":          30,
        "ic_stop_loss_multiplier": 2.0,
    },
    "conservative": {
        "ic_short_delta":          0.10,
        "ic_profit_target_pct":    0.25,
        "ic_min_iv_rank":          40,
        "ic_stop_loss_multiplier": 1.5,
    },
    "aggressive": {
        "ic_short_delta":          0.20,
        "ic_profit_target_pct":    0.75,
        "ic_min_iv_rank":          20,
        "ic_stop_loss_multiplier": 2.5,
    },
    "high_iv_only": {
        "ic_short_delta":          0.16,
        "ic_profit_target_pct":    0.50,
        "ic_min_iv_rank":          50,
        "ic_stop_loss_multiplier": 2.0,
    },
}
```

---

## 17. TESTING REQUIREMENTS

### 17.1 Test Coverage Requirements

Every module in src/ must have 90%+ test coverage before the project is considered complete.

### 17.2 Test Fixtures — Create These Files

**tests/fixtures/sample_option_chain.json**
Realistic Nifty options chain snapshot with at least 20 strikes, both CE and PE, with bid/ask/ltp/iv/delta fields populated.

**tests/fixtures/sample_historical_prices.csv**
3 years of synthetic Nifty daily data: date, open, high, low, close, volume. Values should show realistic volatility clustering.

**tests/fixtures/sample_trades.json**
20 pre-populated trade records for edge tracker tests — mix of wins and losses, all regimes represented.

### 17.3 Complete Test Requirements by Module

```
data_fetcher:
  test_option_chain_structure_valid               underlying_value > 10000, records > 50 (mocked Kite)
  test_get_india_vix_returns_reasonable_float     5.0 < vix < 100.0
  test_cache_fallback_on_network_error            no crash on KiteNetworkError
  test_token_exception_raised_on_expired_token    TokenException raised, not swallowed

iv_calculator:
  test_bs_price_matches_known_values              S=100,K=100,T=1,r=0.05,σ=0.20 -> ~10.45
  test_iv_rank_between_0_and_100                  0 <= rank <= 100
  test_iv_rank_none_when_insufficient_history     < 100 days -> returns None
  test_greeks_atm_delta_near_0_5                  ATM call delta between 0.45 and 0.55
  test_put_delta_is_negative                      ATM put delta between -0.55 and -0.45
  test_implied_vol_roundtrips                     price→IV→price roundtrip within 0.001
  test_find_strike_by_delta_returns_closest       result within tolerance=0.03

synthetic_data:
  test_synthetic_chain_structure                  all required columns present
  test_synthetic_data_passes_validation           no negative prices, parity holds
  test_put_call_parity_holds                      C-P ≈ S-K*e^(-rT) within 5%

strategy_ic:
  test_ic_rejects_low_iv_rank                     IVR=25 -> should_enter=False
  test_ic_rejects_high_vix                        VIX=28 -> should_enter=False
  test_ic_rejects_bad_dte_too_low                 20 DTE -> should_enter=False
  test_ic_rejects_bad_dte_too_high                50 DTE -> should_enter=False
  test_ic_rejects_event_proximity                 RBI in 3 days -> should_enter=False
  test_ic_accepts_all_valid_conditions            all green -> should_enter=True
  test_stop_loss_triggered_at_2x                  loss=2x -> exit_type=STOP_LOSS
  test_time_stop_at_21_dte                        dte=21 -> exit_type=TIME_STOP
  test_profit_target_at_50pct                     profit=52% -> exit_type=PROFIT_TARGET
  test_trade_structure_positive_net_premium       net_premium > 0
  test_trade_structure_max_loss_within_limit      max_loss < 5% of TOTAL_CAPITAL

backtester:
  test_backtest_costs_deducted_every_trade        total_costs > 0 always
  test_no_entry_when_iv_rank_below_filter         no trades when IVR always low
  test_ev_positive_on_fixture_data                EV > 0 on known-good fixture
  test_regime_breakdown_populated                 all 4 regimes in result

cost_engine:
  test_1lot_ic_total_costs_within_range           650 < costs < 1000  (updated STT 0.0625%)
  test_net_premium_less_than_gross                always
  test_minimum_viable_premium_is_positive

edge_tracker:
  test_rolling_win_rate_correct_calculation
  test_stop_signal_red_at_correct_threshold       win_rate=0.55 -> RED signal
  test_stop_signal_yellow_at_correct_threshold    win_rate=0.60 -> YELLOW signal
  test_profit_factor_red_below_1                  PF=0.95 -> RED signal
  test_regime_degradation_signal                  actual 15pp below expected -> YELLOW
```

---

## 18. DEPLOYMENT

### 18.1 Local Development — Three Terminals

```bash
# Terminal 1 — Start FastAPI backend
source venv/bin/activate
uvicorn api.main:app --reload --port 8000
# API docs at: http://localhost:8000/docs

# Terminal 2 — Start React frontend
cd frontend
npm run dev
# Dashboard at: http://localhost:5173

# Terminal 3 — Daily workflow
source venv/bin/activate
python cli.py login           # Every morning first
python cli.py morning-review  # At 9 AM before market open
```

### 18.2 README.md Structure

Claude Code must create a README.md with all six of these sections:

1. **Prerequisites** — Python 3.11+, Node 18+, Zerodha API access steps, Anthropic API key
2. **Installation** — Run ./setup.sh, then fill .env from .env.template
3. **Daily Usage** — Step by step: login command, morning-review command, execute-trade command
4. **CLI Reference** — All 7 commands with argument descriptions and example output
5. **Architecture Overview** — Brief description of each module and how they connect
6. **Troubleshooting** — Top 10 issues with exact fix commands

---

## 19. ERROR HANDLING REFERENCE

Every error this system can encounter, documented with its cause and resolution.

| Error Class | Module | Cause | Resolution |
|-------------|--------|-------|------------|
| KiteTokenException | data_fetcher, broker_zerodha | Zerodha token expired (daily reset ~8 AM) | Send Telegram alert "Re-login required", halt until done |
| KiteNetworkError | data_fetcher | Kite API unreachable | Return cached data, log warning, continue without crashing |
| DataStalenessError | data_fetcher | Cache older than 15 min in market hours | Raise to caller, position_monitor pauses until fresh data |
| NSEConnectionError | data_fetcher | NSE VIX fallback unreachable | Use cached VIX, log warning, do not crash |
| TokenExpiredError | broker_zerodha | Zerodha token expired (resets at 8 AM) | Send Telegram "re-login required", halt order placement until done |
| InsufficientMarginError | broker_zerodha | Not enough margin for order (from margin API check) | Log skipped trade, Telegram alert, suggest reducing lots |
| InvalidTradeStructureError | strategy_ic | Net premium negative or max loss too large | Skip trade, log full reason, alert user |
| StopSignalError | edge_tracker | Win rate below red threshold | Lock new trade entries, record timestamp for 4-week timer |
| DatabaseError | any | SQLite write failure | Log to flat file fallback, alert user, retry on next tick |
| AnthropicAPIError | claude_advisor | Anthropic API unreachable | Fall back to rule-based summary, never crash, always return dict |
| OptionChainParseError | data_fetcher | NSE changed API response format | Log raw response, alert user to update parser |
| ExpiryNotFoundError | strategy_ic / strategy_cal | No expiry in target DTE window | Skip entry today, log reason, try again tomorrow |
| OrderFillTimeout | broker_zerodha | Limit order not filled in time | Improve price by Rs 1, retry up to 3 times, then cancel |
| MarginCallDetected | position_monitor | Zerodha sends margin shortfall alert | Immediate alert to user, do not place new trades |

---

## 20. CLAUDE CODE EXECUTION CHECKLIST

Work through this list in exact order. Do not skip any item. Mark complete only when tests pass.

### Pre-Build Setup
- [ ] Create complete directory structure as specified in Section 3
- [ ] Create requirements.txt with all packages from Section 2
- [ ] Create setup.sh with all setup steps from Section 2
- [ ] Create .env.template with all 6 required key names (including TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
- [ ] Create .gitignore excluding .env, venv, __pycache__, *.db, logs/
- [ ] Build config/settings.py with all constants from Section 4.1 — verify no hardcoding in any other file
- [ ] Create config/events_calendar.json with all events from Section 16.1
- [ ] Create config/strategy_params.py with all 4 param sets from Section 16.2
- [ ] Create alembic.ini and alembic/env.py
- [ ] Build db/models.py with all 6 tables from Section 15
- [ ] Build db/crud.py with read/write functions for every model
- [ ] Create alembic/versions/001_initial_schema.py
- [ ] Run: alembic upgrade head — verify creates without error

### Phase 1 — Data Layer
- [ ] Build src/data_fetcher.py — Kite Connect as primary data source, NSE fallback for VIX only
- [ ] Build src/data_fetcher.py — all methods with error handling as specified
- [ ] Build src/iv_calculator.py — Black-Scholes via scipy (NOT mibian) — all methods
- [ ] Build src/synthetic_data_generator.py — generate realistic historical options data
- [ ] Run synthetic data validation — put-call parity, delta sanity, no negative prices
- [ ] Create tests/fixtures/ with all 3 fixture files
- [ ] Write all tests in tests/test_data_fetcher.py (using mocked KiteConnect)
- [ ] Write all tests in tests/test_iv_calculator.py (including BS roundtrip test)
- [ ] Write all tests in tests/test_synthetic_data.py
- [ ] Run: pytest tests/test_data_fetcher.py tests/test_iv_calculator.py tests/test_synthetic_data.py — all pass

### Phase 2 — Strategy Engine
- [ ] Build src/strategy_ic.py — check_entry_conditions with all 6 gates
- [ ] Build src/strategy_ic.py — generate_trade_structure with validation
- [ ] Build src/strategy_ic.py — check_exit_conditions with 3 exit types
- [ ] Build src/strategy_cal.py — all 4 methods
- [ ] Write all tests in tests/test_strategy_ic.py
- [ ] Write all tests in tests/test_strategy_cal.py
- [ ] Run: pytest tests/test_strategy_ic.py tests/test_strategy_cal.py — all pass

### Phase 3 — Backtesting Engine
- [ ] Generate synthetic historical options data: fetch Nifty spot history via Kite, run SyntheticDataGenerator
- [ ] Validate synthetic data quality: put-call parity, delta sanity checks
- [ ] Build src/backtester.py — run_ic_backtest with cost deduction mandatory (using synthetic data)
- [ ] Build src/backtester.py — run_parameter_sweep
- [ ] Build src/backtester.py — generate_backtest_report with GO/NO-GO verdict
- [ ] Write all tests in tests/test_backtester.py
- [ ] Run: pytest tests/test_backtester.py — all pass
- [ ] Verify: assert total_costs > 0 for every simulated trade
- [ ] NOTE: Backtest results are based on synthetic data. Before deploying real capital, validate with paper trading or a paid data provider.

### Phase 4 — Broker Integration
- [ ] Build src/broker_zerodha.py — daily token management
- [ ] Build src/broker_zerodha.py — place_order with NRML product (NOT MIS) and limit orders with retry logic
- [ ] Build src/broker_zerodha.py — check_margin() using Kite margin API
- [ ] Build src/broker_zerodha.py — stop_loss_close with market orders
- [ ] Build src/broker_zerodha.py — get_positions and get_option_ltp
- [ ] Test token flow with mocked Zerodha API
- [ ] Verify: product="NRML" in all place_order calls (never MIS)
- [ ] Verify: no market orders placed except in stop_loss_close()

### Phase 5 — Position Monitor
- [ ] Build src/position_monitor.py — APScheduler loop during market hours only
- [ ] Build src/position_monitor.py — _monitoring_tick calling exit and adjustment checks
- [ ] Build src/position_monitor.py — send_alert with Telegram (primary) + plyer (secondary) + 3 urgency levels
- [ ] Build src/position_monitor.py — send_telegram_message() via httpx
- [ ] Verify: Telegram alerts delivered correctly for IMMEDIATE and TODAY urgency levels
- [ ] Verify: plyer desktop notification works as fallback

### Phase 6 — Adjustment Engine
- [ ] Build src/adjustment_engine.py — IC decision tree exactly as specified
- [ ] Build src/adjustment_engine.py — Calendar decision tree exactly as specified
- [ ] Test all IC adjustment scenarios: DTE<10, loss>1.5x, call tested, put tested
- [ ] Test all Calendar scenarios: 4% move, 2% move, front expiring

### Phase 7 — Cost Engine
- [ ] Build src/cost_engine.py — calculate_trade_costs with all cost components
- [ ] Build src/cost_engine.py — estimate_margin_required
- [ ] Build src/cost_engine.py — get_minimum_viable_premium
- [ ] Run: pytest tests/test_cost_engine.py
- [ ] Verify: 1-lot IC costs between Rs 650 and Rs 1000 (with updated STT 0.0625%)

### Phase 8 — Edge Tracker
- [ ] Build src/edge_tracker.py — rolling_win_rate and rolling_profit_factor
- [ ] Build src/edge_tracker.py — get_regime_win_rates
- [ ] Build src/edge_tracker.py — evaluate_stop_signals with all 5 conditions
- [ ] Run: pytest tests/test_edge_tracker.py — all 5 stop signal tests pass

### Phase 9 — CLI
- [ ] Build cli/commands.py — all 7 commands
- [ ] Build cli.py entry point
- [ ] Test: python cli.py --help shows all commands
- [ ] Test: python cli.py morning-review completes without error

### Phase 10 — Dashboard
- [ ] Scaffold React app: npm create vite, install tailwindcss recharts axios dayjs
- [ ] Build all 5 tab components as specified in Section 13.2
- [ ] Build api/main.py with CORS and all router mounts
- [ ] Build all 5 API routers with all endpoints from Section 13.3
- [ ] Test: GET /api/signals/market returns valid JSON
- [ ] Test: Frontend loads at localhost:5173 without errors
- [ ] Test: Frontend successfully calls backend API

### Phase 11 — Claude AI
- [ ] Build src/claude_advisor.py — generate_daily_review with fallback
- [ ] Build src/claude_advisor.py — generate_adjustment_advice
- [ ] Build src/claude_advisor.py — answer_trade_question
- [ ] Test: fallback returns valid dict when API unreachable
- [ ] Verify: all 7 output fields always present in daily review response

### Final Integration
- [ ] Run full test suite: pytest tests/ -v — all tests pass
- [ ] Run morning-review end to end — verify all 6 sections render correctly
- [ ] Run backtest on 2021-2023 data — win rate between 72-85%, EV positive
- [ ] Create README.md with all 6 sections from Section 18.2
- [ ] Verify .gitignore is correct — .env not tracked by git
- [ ] Final check: no hardcoded numbers anywhere outside config/settings.py

---

*This PRD is complete. Every decision is made. Every error has a resolution. Every test has a pass criterion. Claude Code starts at the Pre-Build Setup checklist and works through each phase in order.*

---

## APPENDIX: ISSUES IDENTIFIED AND RESOLUTIONS APPLIED

| # | Issue | Resolution | Section Updated |
|---|-------|------------|-----------------|
| 1 | NSE historical options data unavailable for free | Added SyntheticDataGenerator (Option B): generates realistic options data from Nifty spot + Black-Scholes | 4.5, 6.1, Phase 3 checklist |
| 2 | Nifty weekly expiries discontinued (late 2024) | Calendar Spread front month redesigned: uses nearest monthly expiry (20-35 DTE) instead of weeklies | Settings, 5.2, 9.1 |
| 3 | MIS product type would auto-square-off positional trades | Changed to NRML (normal/carryforward) for all options orders | 7.2 |
| 4 | NSE scraping is fragile and frequently blocked | Kite Connect API is now primary data source; NSE retained only as VIX fallback | 4.3 |
| 5 | mibian library unmaintained, buggy on Python 3.11+ | Replaced with direct Black-Scholes implementation using scipy.stats.norm | 4.4, requirements.txt |
| 6 | Zerodha requires daily manual browser login | Accepted (cannot automate per Zerodha rules); added Telegram reminder at 8:30 AM | Daily flow, 8.1 |
| 7 | STT rates outdated (pre-Budget 2024) | Updated to 0.0625% sell-side (Budget 2024); added ITM expiry rate 0.125% | Settings, 10.1 |
| 8 | Margin estimates hardcoded, inaccurate during high VIX | Added broker.check_margin() using Kite Connect margin API; hardcoded values are fallback only | 7.2, 10.1 |
| 9 | plyer desktop notifications unreliable on Windows | Added Telegram Bot API as primary alert channel; plyer retained as secondary | 8.1 |
| 10 | Package versions pinned to old releases | Updated to >= minimum versions; anthropic>=0.45.0 required for Claude 4.x models | requirements.txt |
| 11 | SQLite concurrent access errors (FastAPI async + monitor writes) | Added WAL mode + busy_timeout=5000ms on engine connect | 15.0 |
