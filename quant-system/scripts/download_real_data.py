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
    cache = Path("data/real_data_cache")
    files = list(cache.glob("*.parquet"))
    total_mb = sum(f.stat().st_size for f in files) / 1_048_576
    log.info(f"\n  Cache: {len(files)} files, {total_mb:.1f} MB")
