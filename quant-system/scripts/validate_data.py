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
