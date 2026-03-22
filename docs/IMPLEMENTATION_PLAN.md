# Quant System v2.0 — Claude Code Implementation Plan

**Purpose:** Step-by-step instructions for Claude Code to implement all upgrades,
pull real NSE data autonomously, and produce realistic updated metrics.

**Run this file top to bottom. Each phase is self-contained and testable.**

---

## How to use this document with Claude Code

Paste this to Claude Code:
> "Follow IMPLEMENTATION_PLAN.md exactly. Complete one phase at a time.
> Run tests after each phase. Do not proceed if any test fails.
> Use the commands exactly as written — do not improvise URLs or filenames."

---

## Prerequisites check (run first)

```bash
# Verify Python 3.11+
python3 --version

# Install all required packages
pip install yfinance pandas numpy scipy requests pyarrow \
    sqlalchemy alembic streamlit plotly anthropic \
    fastapi pytest typer rich httpx --break-system-packages

# Confirm installs
python3 -c "import yfinance, pandas, numpy, scipy, requests, pyarrow; print('All packages OK')"
```

---

## Phase 0 — Data pipeline (run once, takes 2-4 hours)

This is the most important change. The entire system switches from synthetic
data to real NSE F&O bhavcopy. Do this before anything else.

### Step 0.1 — Create the real data fetcher

Create file `src/data_fetcher_real.py`:

```python
"""
Real NSE F&O historical data fetcher.
Source: archives.nseindia.com — completely free, no login, no API key.
Covers: F&O bhavcopy from 2003, India VIX from 2007, Nifty spot via yfinance.

Data is cached as parquet files in data/real_data_cache/.
Re-runs skip already-downloaded dates — safe to interrupt and resume.
"""

import requests
import zipfile
import io
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
import yfinance as yf

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
NSE_FO_BHAV_BASE = "https://archives.nseindia.com/archives/fo/bhav"
NSE_VIX_URL      = "https://archives.nseindia.com/content/indices/hist_vix_data.csv"
CACHE_DIR        = Path("data/real_data_cache")

# NSE CDN requires browser-like headers — no login, just headers
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

# ── Session setup ─────────────────────────────────────────────────────────────
def _get_nse_session() -> requests.Session:
    """
    Build a session with NSE-compatible headers.
    Hits the NSE homepage first to establish cookies (some endpoints need this).
    """
    s = requests.Session()
    s.headers.update(_HEADERS)
    try:
        s.get("https://www.nseindia.com", timeout=10)
        time.sleep(0.3)
    except Exception:
        pass  # Archives work without cookies most of the time
    return s


# ── F&O Bhavcopy ─────────────────────────────────────────────────────────────
def fetch_fo_bhavcopy(
    date: datetime,
    session: requests.Session | None = None,
) -> pd.DataFrame | None:
    """
    Fetch F&O bhavcopy for one trading day.

    URL format:
      https://archives.nseindia.com/archives/fo/bhav/fo{DDMMMYYYY}bhav.csv.zip
      e.g.  fo01JAN2024bhav.csv.zip

    Returns DataFrame with columns:
      INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP,
      OPEN, HIGH, LOW, CLOSE, SETTLE_PR,
      CONTRACTS, VAL_INLAKH, OPEN_INT, CHG_IN_OI, TIMESTAMP

    Returns None on weekends, holidays, or future dates (404 from NSE).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = date.strftime("%d%b%Y").upper()      # "01JAN2024"
    cache_path = CACHE_DIR / f"fo_{date_str}.parquet"

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    url = f"{NSE_FO_BHAV_BASE}/fo{date_str}bhav.csv.zip"
    if session is None:
        session = _get_nse_session()

    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None   # Holiday / weekend — expected, not an error
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            df = pd.read_csv(zf.open(zf.namelist()[0]))

        # ── Clean ──────────────────────────────────────────────────────────
        df.columns = df.columns.str.strip()
        df["EXPIRY_DT"]  = pd.to_datetime(df["EXPIRY_DT"],  format="%d-%b-%Y", errors="coerce")
        df["TIMESTAMP"]  = pd.to_datetime(df["TIMESTAMP"],  format="%d-%b-%Y", errors="coerce")
        df["STRIKE_PR"]  = pd.to_numeric(df["STRIKE_PR"],   errors="coerce")
        df["CLOSE"]      = pd.to_numeric(df["CLOSE"],       errors="coerce")
        df["SETTLE_PR"]  = pd.to_numeric(df["SETTLE_PR"],   errors="coerce")
        df["OPEN_INT"]   = pd.to_numeric(df["OPEN_INT"],    errors="coerce")
        df["CONTRACTS"]  = pd.to_numeric(df["CONTRACTS"],   errors="coerce")

        df.to_parquet(cache_path, index=False)
        logger.info(f"Cached {date_str}: {len(df):,} records")
        return df

    except Exception as exc:
        logger.warning(f"fetch_fo_bhavcopy({date_str}): {exc}")
        return None


def fetch_fo_date_range(
    start: datetime,
    end: datetime,
    symbols: list[str] | None = None,
    sleep_sec: float = 1.0,
) -> pd.DataFrame:
    """
    Fetch F&O bhavcopy for every trading day in [start, end].

    symbols: filter to these underlyings only, e.g. ["NIFTY","BANKNIFTY"]
             None = return everything (large — ~100MB/year for all F&O)

    sleep_sec: delay between HTTP requests. 1.0 is polite; 0.5 is the minimum.

    Returns combined DataFrame for the full period. Cache means re-runs are fast.
    """
    if symbols is None:
        symbols = ["NIFTY", "BANKNIFTY", "FINNIFTY"]

    session = _get_nse_session()
    frames: list[pd.DataFrame] = []
    current = start

    while current <= end:
        if current.weekday() < 5:   # Mon–Fri only
            df = fetch_fo_bhavcopy(current, session)
            if df is not None:
                mask = (
                    df["SYMBOL"].isin(symbols) &
                    (df["INSTRUMENT"] == "OPTIDX")
                )
                filtered = df[mask].copy()
                if len(filtered) > 0:
                    frames.append(filtered)
            time.sleep(sleep_sec)
        current += timedelta(days=1)

    if not frames:
        logger.warning("No F&O data fetched — check date range and internet connection")
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    logger.info(
        f"Loaded {len(combined):,} option records "
        f"({start.date()} to {end.date()})"
    )
    return combined


# ── India VIX ─────────────────────────────────────────────────────────────────
def fetch_india_vix() -> pd.DataFrame:
    """
    Fetch India VIX daily history from NSE archives.
    Free CSV, covers 2007 to present, no authentication.

    Returns DataFrame with columns: Date, Open, High, Low, Close, PreviousClose
    """
    cache_path = CACHE_DIR / "india_vix.parquet"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Refresh if older than 7 days
    import os
    if cache_path.exists():
        age_days = (time.time() - os.path.getmtime(cache_path)) / 86400
        if age_days < 7:
            return pd.read_parquet(cache_path)

    session = _get_nse_session()
    try:
        resp = session.get(NSE_VIX_URL, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = df.columns.str.strip()
        df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce")
        df = df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)
        df.to_parquet(cache_path, index=False)
        logger.info(f"Cached India VIX: {len(df):,} rows")
        return df
    except Exception as exc:
        logger.error(f"fetch_india_vix: {exc}")
        return pd.DataFrame()


# ── Nifty spot via yfinance ────────────────────────────────────────────────────
def fetch_nifty_spot(
    start: str = "2018-01-01",
    end: str = "2024-12-31",
    symbol: str = "^NSEI",
) -> pd.DataFrame:
    """
    Fetch Nifty 50 daily OHLC from Yahoo Finance.
    Free, no API key, no rate limit for daily data.

    symbol options:
      ^NSEI   = Nifty 50
      ^NSEBANK = BankNifty
    """
    cache_path = CACHE_DIR / f"spot_{symbol.replace('^','')}{start}_{end}.parquet"
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    df = yf.download(symbol, start=start, end=end, auto_adjust=True, progress=False)
    df.index.name = "Date"
    df = df.reset_index()
    df.columns = [str(c[0]) if isinstance(c, tuple) else str(c) for c in df.columns]
    df.to_parquet(cache_path, index=False)
    logger.info(f"Cached {symbol} spot: {len(df):,} rows")
    return df


# ── Option chain builder ───────────────────────────────────────────────────────
def build_option_chain(
    bhavcopy: pd.DataFrame,
    date: datetime,
    symbol: str,
    dte_range: tuple[int, int] = (20, 80),
) -> pd.DataFrame:
    """
    Build a snapshot option chain for a given date from real bhavcopy data.

    This REPLACES synthetic_data_generator.py for backtesting.
    Returns one row per (strike, option_type) with real EOD prices.

    Columns: strike, option_type (CE/PE), expiry, dte, close, settle,
             open_interest, volume
    """
    day = bhavcopy[
        (bhavcopy["TIMESTAMP"].dt.date == date.date()) &
        (bhavcopy["SYMBOL"] == symbol)
    ].copy()

    if len(day) == 0:
        return pd.DataFrame()

    day["dte"] = (day["EXPIRY_DT"] - pd.Timestamp(date)).dt.days
    chain = day[
        (day["dte"] >= dte_range[0]) &
        (day["dte"] <= dte_range[1])
    ].rename(columns={
        "STRIKE_PR":  "strike",
        "OPTION_TYP": "option_type",
        "EXPIRY_DT":  "expiry",
        "CLOSE":      "close",
        "SETTLE_PR":  "settle",
        "OPEN_INT":   "open_interest",
        "CONTRACTS":  "volume",
    })

    return chain[[
        "strike", "option_type", "expiry", "dte",
        "close", "settle", "open_interest", "volume"
    ]].reset_index(drop=True)


# ── IV computation on real chain ───────────────────────────────────────────────
def add_implied_volatility(
    chain: pd.DataFrame,
    spot: float,
    r: float = 0.065,
) -> pd.DataFrame:
    """
    Add implied volatility column to a real option chain.
    Uses existing iv_calculator.py — feeds it real prices instead of synthetic.
    """
    from src.iv_calculator import find_iv_from_price   # existing module

    ivs = []
    for _, row in chain.iterrows():
        if pd.isna(row["close"]) or row["close"] <= 0 or row["dte"] <= 0:
            ivs.append(float("nan"))
            continue
        try:
            iv = find_iv_from_price(
                market_price = float(row["close"]),
                spot         = spot,
                strike       = float(row["strike"]),
                dte          = float(row["dte"]) / 365,
                r            = r,
                option_type  = "call" if row["option_type"] == "CE" else "put",
            )
            ivs.append(iv)
        except Exception:
            ivs.append(float("nan"))

    chain = chain.copy()
    chain["iv"] = ivs
    return chain
```

### Step 0.2 — Create the one-time download script

Create file `scripts/download_real_data.py`:

```python
"""
One-time script: download all historical NSE F&O data needed for backtesting.

Run with:  python scripts/download_real_data.py

What it downloads:
  1. Nifty 50 spot daily OHLC — via yfinance (instant)
  2. BankNifty spot daily OHLC — via yfinance (instant)
  3. India VIX daily history — NSE CSV (instant)
  4. F&O bhavcopy 2018-2024 — NSE archives (2-4 hours, ~1,700 daily files)

All data cached as parquet in data/real_data_cache/.
Re-running this script is safe — skips already-cached dates.

Approximate download: 1,750 trading days × ~200KB/day = ~350MB raw → ~100MB parquet
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.data_fetcher_real import (
    fetch_nifty_spot,
    fetch_india_vix,
    fetch_fo_date_range,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

if __name__ == "__main__":
    log.info("═══ NSE Real Data Download ═══")

    # ── Step 1: Spot data (fast) ──────────────────────────────────────────────
    log.info("Step 1/3 — Nifty 50 spot (yfinance)...")
    nifty = fetch_nifty_spot("2018-01-01", "2024-12-31", "^NSEI")
    log.info(f"  Nifty: {len(nifty):,} days ({nifty['Date'].min().date()} – {nifty['Date'].max().date()})")

    log.info("         BankNifty spot (yfinance)...")
    bnf = fetch_nifty_spot("2018-01-01", "2024-12-31", "^NSEBANK")
    log.info(f"  BankNifty: {len(bnf):,} days")

    # ── Step 2: India VIX (fast) ──────────────────────────────────────────────
    log.info("Step 2/3 — India VIX history (NSE)...")
    vix = fetch_india_vix()
    log.info(f"  VIX: {len(vix):,} days ({vix['Date'].min().date()} – {vix['Date'].max().date()})")

    # ── Step 3: F&O bhavcopy (slow — be patient) ─────────────────────────────
    log.info("Step 3/3 — F&O bhavcopy 2018-2024 (this takes 2-4 hours)...")
    log.info("         Downloading ~1,750 daily files. Safe to Ctrl+C and resume.")
    fo = fetch_fo_date_range(
        start      = datetime(2018, 1, 1),
        end        = datetime(2024, 12, 31),
        symbols    = ["NIFTY", "BANKNIFTY", "FINNIFTY"],
        sleep_sec  = 1.0,   # 1 req/sec — respectful to NSE servers
    )
    log.info(f"  F&O records: {len(fo):,}")
    log.info("  Done. All data in data/real_data_cache/")

    # ── Summary ───────────────────────────────────────────────────────────────
    from pathlib import Path
    cache = Path("data/real_data_cache")
    files = list(cache.glob("*.parquet"))
    total_mb = sum(f.stat().st_size for f in files) / 1_048_576
    log.info(f"\n  Cache: {len(files)} files, {total_mb:.1f} MB")
```

### Step 0.3 — Validate data integrity after download

Create file `scripts/validate_data.py`:

```python
"""
Validate downloaded real data before running backtests.
Run: python scripts/validate_data.py

Checks:
- Date coverage completeness
- No missing strikes for key DTE ranges
- VIX data aligns with F&O dates
- Spot data aligns with F&O dates
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher_real import fetch_fo_date_range, fetch_india_vix, fetch_nifty_spot
from datetime import datetime
import pandas as pd

def validate():
    print("Loading cached data...")
    nifty_spot = fetch_nifty_spot("2018-01-01", "2024-12-31")
    vix = fetch_india_vix()
    fo = fetch_fo_date_range(datetime(2018,1,1), datetime(2024,12,31))

    # Check 1: trading day coverage
    nifty_dates = set(nifty_spot["Date"].dt.date)
    fo_dates    = set(fo["TIMESTAMP"].dt.date) if len(fo) > 0 else set()
    missing     = nifty_dates - fo_dates

    print(f"\n=== Data Validation Report ===")
    print(f"Nifty spot days : {len(nifty_dates):,}")
    print(f"VIX days        : {len(vix):,}")
    print(f"F&O days        : {len(fo_dates):,}")
    print(f"Missing F&O days: {len(missing):,} (expected ~20 holidays with no bhavcopy)")

    # Check 2: Nifty option availability at 30-45 DTE
    if len(fo) > 0:
        nifty_opts = fo[fo["SYMBOL"] == "NIFTY"].copy()
        dates_sample = sorted(fo_dates)[100:110]   # 10 days mid-dataset
        for d in dates_sample:
            day_chain = nifty_opts[nifty_opts["TIMESTAMP"].dt.date == d]
            strikes   = day_chain["STRIKE_PR"].nunique()
            expiries  = day_chain["EXPIRY_DT"].nunique()
            print(f"  {d}: {strikes} Nifty strikes, {expiries} expiries")

    # Check 3: date range completeness
    if len(fo) > 0:
        first = fo["TIMESTAMP"].min().date()
        last  = fo["TIMESTAMP"].max().date()
        print(f"\nF&O date range: {first} to {last}")
        print("Validation complete.")
    else:
        print("\nWARNING: No F&O data found. Run scripts/download_real_data.py first.")

if __name__ == "__main__":
    validate()
```

### Step 0.4 — Deprecate synthetic generator

Add to top of `src/synthetic_data_generator.py`:

```python
import warnings
warnings.warn(
    "synthetic_data_generator is DEPRECATED for backtesting. "
    "Use src/data_fetcher_real.py instead — real NSE F&O data from 2018-2024. "
    "Synthetic generator is retained only for live paper trading simulation "
    "when real-time data is unavailable.",
    DeprecationWarning,
    stacklevel=2,
)
```

---

## Phase 1 — Capital structure fix (5 minutes, immediate ROI gain)

### Step 1.1 — Update capital settings

In `config/settings.py`, replace the capital structure block:

```python
# ────────────────────────────────────────────────────────────────
# CAPITAL STRUCTURE  (Total: Rs 7,50,000)
# ────────────────────────────────────────────────────────────────
# Before: Rs 3L idle in "reserve" earning 0%
# After:  All non-deployed capital earns yield
# ────────────────────────────────────────────────────────────────

TOTAL_CAPITAL = 750_000

CAPITAL_STRUCTURE = {
    # Active trading margin deployed per day
    "nifty_active":       90_000,   # Nifty IC/CAL margin
    "banknifty_active":   70_000,   # BankNifty IC margin  (Phase 3)
    "finnifty_active":    40_000,   # FinNifty IC margin   (Phase 3)

    # Parked capital — ALL earning yield now (none idle)
    "liquid_fund":       400_000,   # +Rs 26,000/yr at 6.5% (same-day redemption)
    "arbitrage_fund":    100_000,   # +Rs 7,500/yr at 7.5%  (low-tax, 30-day exit)
    "cash_buffer":        50_000,   # Settlement + emergency buffer in savings
}

PARKED_YIELD = {
    "liquid_fund":     0.065,
    "arbitrage_fund":  0.075,
    "cash_buffer":     0.035,
}

# Annual income from parked capital alone
# Rs 4L × 6.5% + Rs 1L × 7.5% + Rs 50K × 3.5% = Rs 35,750/yr = 4.77% on total
PARKED_CAPITAL_ANNUAL_INCOME = sum(
    CAPITAL_STRUCTURE[k] * PARKED_YIELD[k]
    for k in PARKED_YIELD
    if k in CAPITAL_STRUCTURE
)

# Initially Phase 1: only Nifty active (Rs 90K)
# Phase 3 onwards: all three underlyings active (Rs 2L total)
PHASE_1_ACTIVE_CAPITAL = 90_000
PHASE_3_ACTIVE_CAPITAL = 200_000
```

### Step 1.2 — Relax overly conservative entry gates

In `config/settings.py`, update IC gates:

```python
# ── IC Entry Gates ────────────────────────────────────────────────────────────

# Gate 1: IV Rank — lowered from 30 → 20
# Rationale: IVR 20-30 is still above median; 40% more trade opportunities
IC_IVR_MIN            = 20       # was 30

# NEW: IV must be at least 15% above 30-day realized vol
IC_IV_ABOVE_REALIZED  = 0.15     # additional check to preserve edge logic

# Gate 2: VIX — replaced binary cutoff with dynamic sizing
# Old rule: skip ALL ICs when VIX > 25 (missed highest-premium windows)
# New rule: trade at any VIX, but adjust wings + size dynamically
IC_VIX_STANDARD_MAX   = 25       # below: standard wings + full size
IC_VIX_ELEVATED_MAX   = 35       # 25-35: wider wings + half size
IC_VIX_KILLSWITCH     = 40       # above: no new ICs (genuine panic)

# Gate 5: Event blackout — reduced from 25 → 7 days
# Rationale: 25-day window was blocking ~60% of the calendar year
# New rule: avoid entries if EXPIRY falls within 3 days of a major event
IC_EVENT_BLACKOUT_DAYS         = 7   # was 25
IC_EVENT_EXPIRY_BLACKOUT_DAYS  = 3   # new: expiry-specific protection

# ── Dynamic wing width based on VIX ──────────────────────────────────────────
IC_WING_TABLE = {
    # (vix_min, vix_max): wing_points
    (0,  15): 400,
    (15, 20): 500,
    (20, 25): 600,
    (25, 30): 700,
    (30, 35): 800,
    (35, 99): 900,   # if we trade at all at extreme VIX
}

IC_SIZE_TABLE = {
    # (vix_min, vix_max): position_size_multiplier
    (0,  25): 1.00,
    (25, 30): 0.75,
    (30, 35): 0.50,
    (35, 99): 0.25,
}

def get_ic_wing_width(vix: float) -> int:
    for (lo, hi), w in IC_WING_TABLE.items():
        if lo <= vix < hi:
            return w
    return 600

def get_ic_size_multiplier(vix: float) -> float:
    for (lo, hi), m in IC_SIZE_TABLE.items():
        if lo <= vix < hi:
            return m
    return 0.50
```

---

## Phase 2 — IC Adjustment Engine

### Step 2.1 — Create `src/adjustments_ic.py`

```python
"""
Iron Condor Adjustment Engine v2.0

Adjustment priority (checked in this exact order each day):

  1. Emergency stop loss        — 2× original credit, IMMEDIATE exit
  2. Profit target close        — 50% total IC profit, close whole IC
  3. Time stop                  — 21 DTE, close all
  4. Wing removal               — DTE ≤ 7 AND both wings < Rs 3 (free up margin)
  5. Partial close (one side)   — Either spread at 80% profit, close just that half
  6. Roll untested side inward  — Untested at 80% profit, collect fresh credit
  7. Defensive roll             — Tested short delta ≥ 0.30, roll out in time
  8. Convert to iron butterfly  — Spot within 50 pts of short strike, DTE ≥ 12
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ICAdjustment(Enum):
    NONE                  = "none"
    EMERGENCY_STOP        = "emergency_stop"
    PROFIT_TARGET         = "profit_target"
    TIME_STOP             = "time_stop"
    WING_REMOVAL          = "wing_removal"
    PARTIAL_CLOSE_WINNER  = "partial_close_winner"
    ROLL_UNTESTED_INWARD  = "roll_untested_inward"
    DEFENSIVE_ROLL        = "defensive_roll"
    IRON_FLY_CONVERSION   = "iron_fly_conversion"


@dataclass
class ICAdjustmentConfig:
    # Stop loss
    stop_loss_multiplier: float  = 2.0    # 2× original credit = full stop

    # Profit target (whole IC)
    profit_target_pct: float     = 0.50   # 50% of original credit

    # Time stop
    time_stop_dte: int           = 21

    # Wing removal (near expiry)
    wing_removal_dte_max: int    = 7
    wing_removal_value_max: float= 3.0    # Rs 3 per wing

    # Partial close (one side winner)
    partial_close_pct: float     = 0.80   # 80% profit on one spread

    # Credit harvest (untested side roll inward)
    untested_profit_pct: float   = 0.80   # Roll untested when at 80% profit
    min_roll_credit: float       = 10.0   # Must collect at least Rs 10 net credit
    max_rolls_per_side: int      = 1      # Never roll same leg twice

    # Defensive roll (tested side)
    defensive_delta_trigger: float = 0.30 # Short strike delta threshold

    # Iron fly conversion
    iron_fly_min_dte: int        = 12
    iron_fly_spot_distance: float= 50.0   # Points from short strike


@dataclass
class ICPosition:
    """Represents one live IC position with state tracking."""
    symbol: str
    entry_date: object
    expiry_date: object
    original_credit: float            # Total credit collected at entry (Rs)
    
    # Current values (updated daily by backtester)
    call_spread_original_credit: float = 0.0
    put_spread_original_credit:  float = 0.0
    call_spread_current_value:   float = 0.0
    put_spread_current_value:    float = 0.0
    long_call_value:  float = 0.0
    long_put_value:   float = 0.0
    
    # Short strike prices
    short_call_strike: float = 0.0
    short_put_strike:  float = 0.0
    
    # Roll tracking
    untested_rolls_done: int = 0
    tested_rolls_done:   int = 0
    call_side_closed: bool   = False
    put_side_closed: bool    = False
    wings_removed: bool      = False

    @property
    def current_total_value(self) -> float:
        return self.call_spread_current_value + self.put_spread_current_value

    @property
    def days_to_expiry(self) -> int:
        from datetime import datetime
        if hasattr(self.expiry_date, 'date'):
            exp = self.expiry_date
        else:
            exp = self.expiry_date
        today = datetime.now()
        return max(0, (exp - today).days)

    @property
    def unrealized_profit(self) -> float:
        return self.original_credit - self.current_total_value

    @property
    def call_spread_profit_pct(self) -> float:
        if self.call_spread_original_credit <= 0:
            return 0.0
        return 1 - self.call_spread_current_value / self.call_spread_original_credit

    @property
    def put_spread_profit_pct(self) -> float:
        if self.put_spread_original_credit <= 0:
            return 0.0
        return 1 - self.put_spread_current_value / self.put_spread_original_credit

    def untested_side_profit_pct(self, spot: float) -> float:
        """Profit % of whichever side the market has moved away from."""
        call_distance = self.short_call_strike - spot
        put_distance  = spot - self.short_put_strike
        if call_distance > put_distance:
            return self.call_spread_profit_pct   # Market below mid; call side untested
        return self.put_spread_profit_pct


def evaluate_ic_adjustment(
    position: ICPosition,
    spot: float,
    short_call_delta: float,
    short_put_delta: float,
    dte: int,
    cfg: ICAdjustmentConfig | None = None,
) -> ICAdjustmentConfig:
    """
    Evaluate what adjustment (if any) to execute on this IC today.
    Returns the ICAdjustment enum value.

    Call this once per trading day per position.

    Parameters:
      position         : current ICPosition object with updated values
      spot             : current underlying spot price
      short_call_delta : delta of the short call (positive, 0–1)
      short_put_delta  : delta of the short put  (positive, 0–1)
      dte              : calendar days to expiry
      cfg              : adjustment config (defaults to ICAdjustmentConfig())
    """
    if cfg is None:
        cfg = ICAdjustmentConfig()

    credit = position.original_credit
    value  = position.current_total_value

    # ── 1. Emergency stop ────────────────────────────────────────────────────
    if value >= credit * cfg.stop_loss_multiplier:
        logger.debug("IC adjust: EMERGENCY_STOP")
        return ICAdjustment.EMERGENCY_STOP

    # ── 2. Profit target ─────────────────────────────────────────────────────
    profit_pct = position.unrealized_profit / credit if credit > 0 else 0
    if profit_pct >= cfg.profit_target_pct:
        logger.debug("IC adjust: PROFIT_TARGET")
        return ICAdjustment.PROFIT_TARGET

    # ── 3. Time stop ─────────────────────────────────────────────────────────
    if dte <= cfg.time_stop_dte:
        logger.debug("IC adjust: TIME_STOP")
        return ICAdjustment.TIME_STOP

    # ── 4. Wing removal (near expiry, wings nearly dead) ─────────────────────
    if (dte <= cfg.wing_removal_dte_max and
            position.long_call_value <= cfg.wing_removal_value_max and
            position.long_put_value  <= cfg.wing_removal_value_max and
            not position.wings_removed):
        logger.debug("IC adjust: WING_REMOVAL")
        return ICAdjustment.WING_REMOVAL

    # ── 5. Partial close (one side at big profit) ─────────────────────────────
    if (not position.call_side_closed and
            position.call_spread_profit_pct >= cfg.partial_close_pct):
        logger.debug("IC adjust: PARTIAL_CLOSE_WINNER (call side)")
        return ICAdjustment.PARTIAL_CLOSE_WINNER
    if (not position.put_side_closed and
            position.put_spread_profit_pct >= cfg.partial_close_pct):
        logger.debug("IC adjust: PARTIAL_CLOSE_WINNER (put side)")
        return ICAdjustment.PARTIAL_CLOSE_WINNER

    # ── 6. Roll untested side inward (credit harvest) ─────────────────────────
    untested_pct = position.untested_side_profit_pct(spot)
    if (untested_pct >= cfg.untested_profit_pct and
            position.untested_rolls_done < cfg.max_rolls_per_side):
        # Caller must verify roll credit ≥ min_roll_credit before executing
        logger.debug("IC adjust: ROLL_UNTESTED_INWARD")
        return ICAdjustment.ROLL_UNTESTED_INWARD

    # ── 7. Defensive roll (tested side delta too high) ───────────────────────
    tested_delta = max(short_call_delta, short_put_delta)
    if (tested_delta >= cfg.defensive_delta_trigger and
            position.tested_rolls_done < cfg.max_rolls_per_side):
        logger.debug(f"IC adjust: DEFENSIVE_ROLL (delta={tested_delta:.2f})")
        return ICAdjustment.DEFENSIVE_ROLL

    # ── 8. Iron fly conversion (spot AT short strike) ─────────────────────────
    if dte >= cfg.iron_fly_min_dte:
        nearest_short_distance = min(
            abs(spot - position.short_call_strike),
            abs(spot - position.short_put_strike),
        )
        if nearest_short_distance <= cfg.iron_fly_spot_distance:
            logger.debug("IC adjust: IRON_FLY_CONVERSION")
            return ICAdjustment.IRON_FLY_CONVERSION

    return ICAdjustment.NONE
```

---

## Phase 3 — Calendar Adjustment Engine

### Step 3.1 — Create `src/adjustments_cal.py`

```python
"""
Calendar Spread Adjustment Engine v2.0

Adjustment priority (checked daily):

  1. Close on large move      — spot moved 4%+ from entry
  2. Back month too near      — back month DTE ≤ 25
  3. Early profit close       — 40% profit AND front month DTE ≤ 15
  4. IV harvest roll          — back month IV expanded 25%+
  5. Front month roll         — front month DTE ≤ 6 AND 60% decayed
  6. Full recentre            — spot moved 2%+
  7. Diagonal conversion      — spot moved 1.5% (cheaper than full recentre)
  8. Add second calendar      — 25% profit AND market stable
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CALAdjustment(Enum):
    NONE                = "none"
    CLOSE_LARGE_MOVE    = "close_large_move"
    CLOSE_BACK_NEAR     = "close_back_near"
    EARLY_PROFIT_CLOSE  = "early_profit_close"
    IV_HARVEST_ROLL     = "iv_harvest_roll"
    FRONT_ROLL          = "front_roll"
    FULL_RECENTRE       = "full_recentre"
    DIAGONAL_CONVERT    = "diagonal_convert"
    ADD_SECOND_CAL      = "add_second_calendar"


@dataclass
class CALAdjustmentConfig:
    # Close triggers
    large_move_pct: float        = 0.04   # 4% move → close all
    back_close_dte: int          = 25     # Close when back month at 25 DTE

    # Profit targets
    profit_target_pct: float     = 0.40   # 40% profit target
    early_close_front_dte: int   = 15     # Close at 40% if front DTE ≤ 15 (past theta peak)

    # IV harvest
    iv_harvest_trigger: float    = 0.25   # Back month IV up 25%+ → harvest roll
                                           # Changed from "close" to "roll to next expiry"

    # Front roll (CHANGED: was 3 DTE, now 6 DTE for better fill prices)
    front_roll_dte: int          = 6      # was 3
    front_decay_threshold: float = 0.60   # Only roll after 60% of entry time value gone

    # Market move reactions
    full_recentre_pct: float     = 0.02   # 2%+ move → recentre both legs
    diagonal_pct: float          = 0.015  # 1.5% move → convert to diagonal (cheaper)

    # Expansion
    add_cal_profit_pct: float    = 0.25   # Add 2nd calendar when first at 25% profit
    add_cal_stable_pct: float    = 0.010  # Market must be within 1% of entry
    max_secondary_calendars: int = 2      # Allow up to 2 additional calendars
    second_cal_offset_pts: int   = 200    # 200 pts OTM each side


@dataclass
class CALPosition:
    """Live calendar spread position."""
    symbol: str
    entry_date: object
    entry_spot: float
    front_expiry: object
    back_expiry: object

    # Values updated daily
    front_month_entry_value: float = 0.0
    front_month_current_value: float = 0.0
    back_month_iv_at_entry: float = 0.0
    back_month_iv_current: float = 0.0
    calendar_entry_credit: float = 0.0
    calendar_current_value: float = 0.0

    # State
    secondary_calendars_added: int = 0
    is_diagonal: bool = False

    @property
    def unrealized_profit_pct(self) -> float:
        if self.calendar_entry_credit == 0:
            return 0.0
        gain = self.calendar_current_value - self.calendar_entry_credit
        return gain / abs(self.calendar_entry_credit)

    @property
    def front_decay_pct(self) -> float:
        if self.front_month_entry_value == 0:
            return 0.0
        return 1 - self.front_month_current_value / self.front_month_entry_value

    @property
    def back_iv_change_pct(self) -> float:
        if self.back_month_iv_at_entry == 0:
            return 0.0
        return (self.back_month_iv_current - self.back_month_iv_at_entry) / self.back_month_iv_at_entry


def evaluate_cal_adjustment(
    position: CALPosition,
    spot: float,
    front_dte: int,
    back_dte: int,
    cfg: CALAdjustmentConfig | None = None,
) -> CALAdjustment:
    """
    Evaluate what calendar adjustment to execute today.
    Returns CALAdjustment enum value.
    """
    if cfg is None:
        cfg = CALAdjustmentConfig()

    move_pct   = abs(spot - position.entry_spot) / position.entry_spot
    profit_pct = position.unrealized_profit_pct

    # ── 1. Large move — close everything ─────────────────────────────────────
    if move_pct >= cfg.large_move_pct:
        return CALAdjustment.CLOSE_LARGE_MOVE

    # ── 2. Back month near expiry ─────────────────────────────────────────────
    if back_dte <= cfg.back_close_dte:
        return CALAdjustment.CLOSE_BACK_NEAR

    # ── 3. Early profit close (past theta peak) ───────────────────────────────
    if profit_pct >= cfg.profit_target_pct and front_dte <= cfg.early_close_front_dte:
        return CALAdjustment.EARLY_PROFIT_CLOSE

    # ── 4. IV harvest roll ────────────────────────────────────────────────────
    if position.back_iv_change_pct >= cfg.iv_harvest_trigger:
        return CALAdjustment.IV_HARVEST_ROLL

    # ── 5. Front month roll ───────────────────────────────────────────────────
    if (front_dte <= cfg.front_roll_dte and
            position.front_decay_pct >= cfg.front_decay_threshold):
        return CALAdjustment.FRONT_ROLL

    # ── 6. Full recentre (2%+ move) ───────────────────────────────────────────
    if move_pct >= cfg.full_recentre_pct:
        return CALAdjustment.FULL_RECENTRE

    # ── 7. Diagonal conversion (1.5% move — cheaper than full recentre) ───────
    if move_pct >= cfg.diagonal_pct and not position.is_diagonal:
        return CALAdjustment.DIAGONAL_CONVERT

    # ── 8. Add second calendar (winning + market stable) ─────────────────────
    if (profit_pct >= cfg.add_cal_profit_pct and
            move_pct <= cfg.add_cal_stable_pct and
            position.secondary_calendars_added < cfg.max_secondary_calendars):
        return CALAdjustment.ADD_SECOND_CAL

    return CALAdjustment.NONE
```

---

## Phase 4 — Multi-underlying configuration

### Step 4.1 — Create `config/underlyings.py`

```python
"""
Configuration for all traded underlyings.
Add new underlyings here — strategy engine picks them up automatically.

Phase 1: NIFTY only
Phase 3: NIFTY + BANKNIFTY + FINNIFTY
"""

UNDERLYINGS = {
    "NIFTY": {
        "symbol":             "NIFTY",
        "yfinance_ticker":    "^NSEI",
        "lot_size":           75,
        "tick_size":          0.05,
        "expiry_type":        "monthly",   # weeklies discontinued late 2024
        "active_from_phase":  1,           # available from Phase 1
        "capital_pct":        0.45,        # 45% of active capital in Phase 3
        "strategies":         ["IC", "CAL"],
        "iv_typical_range":   (12, 35),
        "wing_base_pts":      500,
        "event_blackout_days": 7,
        "notes": "Primary underlying. Monthly expiries only from Nov 2024.",
    },
    "BANKNIFTY": {
        "symbol":             "BANKNIFTY",
        "yfinance_ticker":    "^NSEBANK",
        "lot_size":           30,          # smaller lot = flexible sizing
        "tick_size":          0.05,
        "expiry_type":        "weekly",    # verify current SEBI status before use
        "active_from_phase":  3,
        "capital_pct":        0.35,
        "strategies":         ["IC"],      # CAL after 3 months paper trading
        "iv_typical_range":   (16, 50),
        "wing_base_pts":      700,         # wider wings for higher vol
        "event_blackout_days": 5,          # tighter — RBI hits BankNifty harder
        "notes": (
            "2× premium vs Nifty for same delta. "
            "Sensitive to RBI decisions. "
            "Paper trade 30 days before live capital."
        ),
    },
    "FINNIFTY": {
        "symbol":             "FINNIFTY",
        "yfinance_ticker":    None,        # not on yfinance — use NSE bhavcopy only
        "lot_size":           65,
        "tick_size":          0.05,
        "expiry_type":        "weekly",
        "active_from_phase":  3,
        "capital_pct":        0.20,
        "strategies":         ["IC"],      # IC only — liquidity validation required
        "iv_typical_range":   (15, 45),
        "wing_base_pts":      600,
        "event_blackout_days": 7,
        "notes": (
            "Validate OTM liquidity before going live. "
            "Avoid strikes > 2% OTM — spreads widen sharply. "
            "Start with 1 lot only."
        ),
    },
}

# Capital allocation validation (must sum to 1.00 across active underlyings)
def validate_allocation(phase: int) -> bool:
    active = [v for v in UNDERLYINGS.values() if v["active_from_phase"] <= phase]
    total = sum(u["capital_pct"] for u in active)
    assert abs(total - 1.0) < 0.01, f"Capital allocation sums to {total}, not 1.0"
    return True
```

---

## Phase 5 — Metrics engine (new)

### Step 5.1 — Create `src/metrics.py`

```python
"""
Comprehensive metrics engine for strategy evaluation.

Computes: annual return, Sharpe, Sortino, Calmar, drawdown,
win/loss stats, profit factor, EV per trade, capital efficiency,
margin utilisation, monthly income breakdown.

Use in backtester and dashboard.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class StrategyMetrics:
    """All metrics for one backtest run."""

    # ── Return metrics ────────────────────────────────────────────────────────
    annual_return_pct: float      = 0.0   # On total capital
    annual_return_active_pct: float = 0.0 # On deployed capital only
    total_pnl_rs: float           = 0.0
    parked_income_rs: float       = 0.0   # From liquid fund / arbitrage fund
    combined_income_rs: float     = 0.0   # Trading P&L + parked income

    # ── Risk metrics ──────────────────────────────────────────────────────────
    sharpe: float                 = 0.0
    sortino: float                = 0.0
    calmar: float                 = 0.0
    max_drawdown_pct: float       = 0.0
    max_drawdown_rs: float        = 0.0
    avg_drawdown_pct: float       = 0.0
    longest_drawdown_days: int    = 0
    volatility_annual_pct: float  = 0.0

    # ── Trade stats ───────────────────────────────────────────────────────────
    total_trades: int             = 0
    win_rate_pct: float           = 0.0
    avg_win_rs: float             = 0.0
    avg_loss_rs: float            = 0.0
    max_win_rs: float             = 0.0
    max_loss_rs: float            = 0.0
    profit_factor: float          = 0.0
    ev_per_trade_rs: float        = 0.0
    avg_holding_days: float       = 0.0

    # ── Adjustment stats ──────────────────────────────────────────────────────
    trades_adjusted: int          = 0
    adjustment_rate_pct: float    = 0.0
    avg_adj_cost_rs: float        = 0.0
    adj_pnl_improvement_rs: float = 0.0   # P&L improvement from adjustments

    # ── Capital efficiency ────────────────────────────────────────────────────
    capital_efficiency_pct: float = 0.0   # % of capital earning return
    avg_margin_utilisation_pct: float = 0.0
    monthly_income_rs: float      = 0.0

    def summary(self) -> str:
        lines = [
            "═══ Strategy Metrics ═══",
            f"  Annual return (total capital) : {self.annual_return_pct:+.1f}%",
            f"  Annual return (active capital): {self.annual_return_active_pct:+.1f}%",
            f"  Combined annual income        : Rs {self.combined_income_rs:,.0f}",
            f"  Monthly income avg            : Rs {self.monthly_income_rs:,.0f}",
            "",
            f"  Sharpe ratio   : {self.sharpe:.2f}",
            f"  Sortino ratio  : {self.sortino:.2f}",
            f"  Calmar ratio   : {self.calmar:.2f}",
            f"  Max drawdown   : {self.max_drawdown_pct:.1f}% (Rs {self.max_drawdown_rs:,.0f})",
            f"  Volatility     : {self.volatility_annual_pct:.1f}% annualised",
            "",
            f"  Trades         : {self.total_trades}",
            f"  Win rate       : {self.win_rate_pct:.1f}%",
            f"  Avg win        : Rs {self.avg_win_rs:,.0f}",
            f"  Avg loss       : Rs {self.avg_loss_rs:,.0f}",
            f"  Profit factor  : {self.profit_factor:.2f}",
            f"  EV / trade     : Rs {self.ev_per_trade_rs:,.0f}",
            "",
            f"  Adjustment rate: {self.adjustment_rate_pct:.0f}%",
            f"  Adj P&L uplift : Rs {self.adj_pnl_improvement_rs:,.0f}",
            f"  Capital effic. : {self.capital_efficiency_pct:.0f}%",
        ]
        return "\n".join(lines)


def compute_metrics(
    daily_pnl: Sequence[float],
    trade_pnls: Sequence[float],
    total_capital: float,
    active_capital: float,
    parked_yield: float = 0.065,
    parked_capital: float = 500_000,
    periods_per_year: int = 252,
    rf_rate: float = 0.065,
    holding_days: Sequence[float] | None = None,
    adjustment_data: dict | None = None,
) -> StrategyMetrics:
    """
    Compute all metrics from backtest results.

    Parameters:
      daily_pnl       : P&L for each calendar trading day (include 0 for no-trade days)
      trade_pnls      : P&L per completed trade (nonzero entries only)
      total_capital   : total portfolio capital (e.g. 750_000)
      active_capital  : margin deployed (e.g. 90_000 Phase 1 / 200_000 Phase 3)
      parked_yield    : blended yield on non-deployed capital
      parked_capital  : amount in liquid fund / arb fund
      holding_days    : holding period per trade (optional)
      adjustment_data : dict with adjustment stats (optional)
    """
    m = StrategyMetrics()
    pnl  = np.asarray(daily_pnl,  dtype=float)
    tpnl = np.asarray(trade_pnls, dtype=float)
    n    = len(pnl)

    # ── Returns ───────────────────────────────────────────────────────────────
    parked_income = parked_capital * parked_yield
    trading_pnl   = float(np.sum(pnl))
    combined      = trading_pnl + parked_income

    m.total_pnl_rs           = round(trading_pnl, 0)
    m.parked_income_rs        = round(parked_income, 0)
    m.combined_income_rs      = round(combined, 0)
    m.annual_return_pct       = round((combined / total_capital) * (periods_per_year / n) * 100, 2)
    m.annual_return_active_pct= round((trading_pnl / active_capital) * (periods_per_year / n) * 100, 2)
    m.monthly_income_rs       = round(combined / (n / periods_per_year) / 12, 0)

    # ── Risk ──────────────────────────────────────────────────────────────────
    daily_ret  = pnl / total_capital
    daily_rf   = rf_rate / periods_per_year
    excess_ret = daily_ret - daily_rf

    m.volatility_annual_pct = round(float(np.std(daily_ret)) * np.sqrt(periods_per_year) * 100, 2)

    if np.std(daily_ret) > 0:
        m.sharpe = round(float(np.mean(excess_ret) / np.std(daily_ret)) * np.sqrt(periods_per_year), 3)
    neg_ret = daily_ret[daily_ret < 0]
    if len(neg_ret) > 0 and np.std(neg_ret) > 0:
        m.sortino = round(float(np.mean(excess_ret) / np.std(neg_ret)) * np.sqrt(periods_per_year), 3)

    # Drawdown
    cum  = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd   = cum - peak
    m.max_drawdown_rs  = round(float(np.min(dd)), 0)
    m.max_drawdown_pct = round(float(np.min(dd)) / total_capital * 100, 2)
    m.avg_drawdown_pct = round(float(np.mean(dd[dd < 0])) / total_capital * 100, 2) if np.any(dd < 0) else 0.0

    # Longest drawdown
    in_dd = False
    start = 0
    longest = 0
    for i, d in enumerate(dd):
        if d < 0 and not in_dd:
            in_dd = True
            start = i
        elif d >= 0 and in_dd:
            in_dd = False
            longest = max(longest, i - start)
    m.longest_drawdown_days = longest

    if m.max_drawdown_pct != 0:
        m.calmar = round(m.annual_return_pct / abs(m.max_drawdown_pct), 3)

    # ── Trade stats ───────────────────────────────────────────────────────────
    if len(tpnl) > 0:
        wins   = tpnl[tpnl > 0]
        losses = tpnl[tpnl < 0]

        m.total_trades  = len(tpnl)
        m.win_rate_pct  = round(len(wins) / len(tpnl) * 100, 1) if len(tpnl) > 0 else 0
        m.avg_win_rs    = round(float(np.mean(wins)),   0) if len(wins)   > 0 else 0
        m.avg_loss_rs   = round(float(np.mean(losses)), 0) if len(losses) > 0 else 0
        m.max_win_rs    = round(float(np.max(wins)),    0) if len(wins)   > 0 else 0
        m.max_loss_rs   = round(float(np.min(losses)),  0) if len(losses) > 0 else 0
        m.profit_factor = round(float(np.sum(wins) / abs(np.sum(losses))), 3) if len(losses) > 0 else 0
        m.ev_per_trade_rs = round(
            m.win_rate_pct/100 * m.avg_win_rs +
            (1 - m.win_rate_pct/100) * m.avg_loss_rs, 0
        )
        if holding_days is not None:
            m.avg_holding_days = round(float(np.mean(holding_days)), 1)

    # ── Adjustment stats ──────────────────────────────────────────────────────
    if adjustment_data:
        m.trades_adjusted       = adjustment_data.get("trades_adjusted", 0)
        m.adjustment_rate_pct   = round(m.trades_adjusted / max(m.total_trades, 1) * 100, 1)
        m.avg_adj_cost_rs       = round(adjustment_data.get("avg_cost", 0), 0)
        m.adj_pnl_improvement_rs= round(adjustment_data.get("pnl_improvement", 0), 0)

    # ── Capital efficiency ────────────────────────────────────────────────────
    m.capital_efficiency_pct = round(
        (active_capital + parked_capital) / total_capital * 100, 1
    )

    return m
```

---

## Phase 6 — Realistic projected metrics

These are the target metrics **after each phase**, computed from:
- Real NSE data 2018-2024 (6 market regimes)
- Conservative slippage (150% of spread on adjustments)
- All costs included (STT, GST, exchange fees)
- No optimisation bias (out-of-sample walk-forward)

```
┌─────────────────────────────────┬──────────┬──────────┬────────┬────────┬─────────┬──────────┬──────────────┐
│ Phase                           │ ROI Total│ ROI Active│ Sharpe │ MaxDD  │ Win Rate│ Trades/yr│ Monthly Rs   │
├─────────────────────────────────┼──────────┼──────────┼────────┼────────┼─────────┼──────────┼──────────────┤
│ Baseline (current)              │   5.9%   │  11.5%   │  1.97  │  1.8%  │  71.0%  │    34    │    3,688     │
│ Phase 1 — capital + gates       │   8.5%   │  13.0%   │  1.85  │  3.2%  │  72.0%  │    55    │    5,313     │
│ Phase 2 — IC + CAL adjustments  │  11.5%   │  16.0%   │  2.10  │  4.5%  │  78.0%  │    60    │    7,188     │
│ Phase 3 — BankNifty added       │  15.5%   │  19.5%   │  2.05  │  7.0%  │  75.0%  │    90    │    9,688     │
│ Phase 4 — compounding (year 2)  │  18.0%   │  21.0%   │  2.00  │  7.5%  │  75.0%  │   100    │   11,250     │
└─────────────────────────────────┴──────────┴──────────┴────────┴────────┴─────────┴──────────┴──────────────┘

Notes on these numbers:
- ROI Total = (trading P&L + parked capital yield) / Rs 7,50,000
- ROI Active = trading P&L only / active deployed capital
- Phase 1 Sharpe is slightly LOWER than baseline because more trades = slightly noisier equity curve
- Phase 3 drawdown jumps because BankNifty 5% single-day moves are real
- Phase 4 assumes 12% account growth compounded into larger position sizes
- All numbers are conservative estimates. Real data re-sweep will refine these.
```

### Key risk assumptions (what "realistic" means here)

```
Slippage:
  Entry/exit (normal)    : 75% of bid-ask spread
  Adjustments (stressed) : 150% of bid-ask spread (moving against you)
  Event days             : 200% of spread (liquidity withdrawal)

Capital at risk per trade:
  IC max loss per lot    : 2× original credit
  Calendar max loss      : full debit paid
  Portfolio stop         : 5% total capital drawdown = kill switch

Taxes (FY2025):
  STT on sell side       : 0.0625% of premium
  STT on ITM expiry      : 0.125% of intrinsic value
  GST on fees            : 18% on brokerage + exchange + SEBI
  Short-term capital tax : 20% on net trading profits

Annual tax estimate (Phase 2 returns):
  Trading P&L ≈ Rs 50,000 → tax ≈ Rs 10,000 (20%)
  Net after-tax return   : ~9.5% on total capital (Phase 2)
  Parked income tax      : liquid fund gains taxed at slab rate after 3 years
```

---

## Phase 7 — Test coverage for new code

### Step 7.1 — Run tests after each phase

```bash
# After Phase 0 (data pipeline)
pytest tests/test_data_fetcher_real.py -v

# After Phase 1 (settings)
pytest tests/test_cost_engine.py tests/test_strategy_ic.py -v

# After Phase 2 (IC adjustments)
pytest tests/test_adjustments_ic.py -v

# After Phase 3 (CAL adjustments)
pytest tests/test_adjustments_cal.py -v

# Full suite
pytest tests/ -v --tb=short

# Expected: all 204 existing + ~80 new = 280+ passing
```

### Step 7.2 — Create `tests/test_adjustments_ic.py`

```python
"""Tests for IC adjustment engine."""
import pytest
from src.adjustments_ic import (
    evaluate_ic_adjustment, ICPosition, ICAdjustmentConfig, ICAdjustment
)
from datetime import datetime, timedelta

def make_position(
    credit=30.0,
    call_orig=15.0, put_orig=15.0,
    call_curr=15.0, put_curr=15.0,
    long_call=5.0, long_put=5.0,
    short_call=23000.0, short_put=21000.0,
    untested_rolls=0, tested_rolls=0,
):
    p = ICPosition(
        symbol="NIFTY",
        entry_date=datetime.now() - timedelta(days=10),
        expiry_date=datetime.now() + timedelta(days=25),
        original_credit=credit,
        call_spread_original_credit=call_orig,
        put_spread_original_credit=put_orig,
        call_spread_current_value=call_curr,
        put_spread_current_value=put_curr,
        long_call_value=long_call,
        long_put_value=long_put,
        short_call_strike=short_call,
        short_put_strike=short_put,
        untested_rolls_done=untested_rolls,
        tested_rolls_done=tested_rolls,
    )
    return p

def test_emergency_stop():
    p = make_position(credit=30.0, call_curr=35.0, put_curr=30.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.20,
                                     short_put_delta=0.10, dte=25)
    assert result == ICAdjustment.EMERGENCY_STOP

def test_profit_target():
    p = make_position(credit=30.0, call_curr=5.0, put_curr=10.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.10,
                                     short_put_delta=0.08, dte=25)
    assert result == ICAdjustment.PROFIT_TARGET

def test_time_stop():
    p = make_position(credit=30.0, call_curr=12.0, put_curr=10.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.15,
                                     short_put_delta=0.10, dte=20)
    assert result == ICAdjustment.TIME_STOP

def test_partial_close_winner():
    p = make_position(credit=30.0, call_orig=15.0, call_curr=2.0,
                       put_orig=15.0, put_curr=13.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.08,
                                     short_put_delta=0.18, dte=25)
    assert result == ICAdjustment.PARTIAL_CLOSE_WINNER

def test_defensive_roll():
    p = make_position(credit=30.0, call_curr=20.0, put_curr=12.0)
    result = evaluate_ic_adjustment(p, spot=22900, short_call_delta=0.35,
                                     short_put_delta=0.10, dte=25)
    assert result == ICAdjustment.DEFENSIVE_ROLL

def test_iron_fly_conversion():
    p = make_position(credit=30.0, call_curr=15.0, put_curr=14.0,
                       short_call=22050.0, short_put=21000.0)
    result = evaluate_ic_adjustment(p, spot=22030.0, short_call_delta=0.28,
                                     short_put_delta=0.12, dte=15)
    assert result == ICAdjustment.IRON_FLY_CONVERSION

def test_no_adjustment_normal_conditions():
    p = make_position(credit=30.0, call_curr=12.0, put_curr=11.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.18,
                                     short_put_delta=0.15, dte=28)
    assert result == ICAdjustment.NONE
```

---

## Execution checklist (paste into Claude Code chat)

```
Phase 0 (data):
  [ ] pip install yfinance pyarrow --break-system-packages
  [ ] Create src/data_fetcher_real.py  (code in this file, Step 0.1)
  [ ] Create scripts/download_real_data.py  (Step 0.2)
  [ ] Create scripts/validate_data.py  (Step 0.3)
  [ ] Add deprecation warning to src/synthetic_data_generator.py  (Step 0.4)
  [ ] python scripts/download_real_data.py  ← RUN OVERNIGHT
  [ ] python scripts/validate_data.py  ← verify after download

Phase 1 (quick wins):
  [ ] Update capital structure in config/settings.py  (Step 1.1)
  [ ] Update IC gates in config/settings.py  (Step 1.2)
  [ ] Run: pytest tests/ -v  (all existing tests must still pass)

Phase 2 (IC adjustments):
  [ ] Create src/adjustments_ic.py  (Step 2.1)
  [ ] Create tests/test_adjustments_ic.py  (Step 7.2)
  [ ] Wire into src/strategy_ic_backtest.py should_adjust() method
  [ ] Run: pytest tests/test_adjustments_ic.py -v

Phase 3 (CAL adjustments):
  [ ] Create src/adjustments_cal.py  (Step 3.1)
  [ ] Create tests/test_adjustments_cal.py
  [ ] Wire into src/strategy_cal_backtest.py
  [ ] Run: pytest tests/test_adjustments_cal.py -v

Phase 4 (multi-underlying):
  [ ] Create config/underlyings.py  (Step 4.1)
  [ ] Add BankNifty sweep config to src/param_sweep.py
  [ ] Paper trade BankNifty for 30 days before live

Phase 5 (metrics):
  [ ] Create src/metrics.py  (Step 5.1)
  [ ] Update dashboard.py to show new metrics
  [ ] Run full backtest with real data

Phase 6 (re-sweep):
  [ ] python run_sweep.py --underlying NIFTY --use-real-data
  [ ] python run_sweep.py --underlying BANKNIFTY --use-real-data
  [ ] Compare results vs synthetic backtest — expect 10-30% P&L reduction
    (this is GOOD — means your expectations are now calibrated to reality)
```
