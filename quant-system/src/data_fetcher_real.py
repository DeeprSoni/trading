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
# UDiFF format (works as of 2025+). Old format discontinued by NSE.
NSE_FO_UDIFF_BASE = "https://nsearchives.nseindia.com/content/fo"
NSE_VIX_URL       = "https://nsearchives.nseindia.com/content/indices/hist_vix_data.csv"
CACHE_DIR         = Path("data/real_data_cache")

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
    Fetch F&O bhavcopy for one trading day using NSE UDiFF format.

    URL format (UDiFF, works 2024+):
      https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip

    Normalizes UDiFF column names to legacy format for backward compatibility:
      TckrSymb → SYMBOL, XpryDt → EXPIRY_DT, StrkPric → STRIKE_PR,
      OptnTp → OPTION_TYP, ClsPric → CLOSE, SttlmPric → SETTLE_PR,
      OpnIntrst → OPEN_INT, TtlTradgVol → CONTRACTS, TradDt → TIMESTAMP,
      FinInstrmTp → INSTRUMENT

    Returns None on weekends, holidays, or future dates (404 from NSE).
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    date_str = date.strftime("%d%b%Y").upper()
    cache_path = CACHE_DIR / f"fo_{date_str}.parquet"

    if cache_path.exists():
        return pd.read_parquet(cache_path)

    # UDiFF URL format
    ymd = date.strftime("%Y%m%d")
    url = f"{NSE_FO_UDIFF_BASE}/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"

    if session is None:
        session = _get_nse_session()

    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            df = pd.read_csv(zf.open(zf.namelist()[0]))

        # ── Normalize UDiFF columns to legacy names ────────────────────────
        col_map = {
            "TckrSymb":      "SYMBOL",
            "FinInstrmTp":   "INSTRUMENT",
            "XpryDt":        "EXPIRY_DT",
            "StrkPric":      "STRIKE_PR",
            "OptnTp":        "OPTION_TYP",
            "OpnPric":       "OPEN",
            "HghPric":       "HIGH",
            "LwPric":        "LOW",
            "ClsPric":       "CLOSE",
            "SttlmPric":     "SETTLE_PR",
            "OpnIntrst":     "OPEN_INT",
            "ChngInOpnIntrst": "CHG_IN_OI",
            "TtlTradgVol":   "CONTRACTS",
            "TtlTrfVal":     "VAL_INLAKH",
            "TradDt":        "TIMESTAMP",
        }
        df = df.rename(columns=col_map)

        # Map UDiFF instrument types to legacy: IDO→OPTIDX, IDF→FUTIDX, STO→OPTSTK, STF→FUTSTK
        instr_map = {"IDO": "OPTIDX", "IDF": "FUTIDX", "STO": "OPTSTK", "STF": "FUTSTK"}
        if "INSTRUMENT" in df.columns:
            df["INSTRUMENT"] = df["INSTRUMENT"].map(instr_map).fillna(df["INSTRUMENT"])

        # Parse dates and numerics
        df["EXPIRY_DT"]  = pd.to_datetime(df["EXPIRY_DT"], errors="coerce")
        df["TIMESTAMP"]  = pd.to_datetime(df["TIMESTAMP"], errors="coerce")
        df["STRIKE_PR"]  = pd.to_numeric(df["STRIKE_PR"],  errors="coerce")
        df["CLOSE"]      = pd.to_numeric(df["CLOSE"],      errors="coerce")
        df["SETTLE_PR"]  = pd.to_numeric(df["SETTLE_PR"],  errors="coerce")
        df["OPEN_INT"]   = pd.to_numeric(df["OPEN_INT"],   errors="coerce")
        df["CONTRACTS"]  = pd.to_numeric(df["CONTRACTS"],  errors="coerce")

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
    from src.iv_calculator import find_iv_from_price

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
