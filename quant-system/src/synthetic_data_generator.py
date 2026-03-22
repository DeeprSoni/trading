"""
Synthetic Data Generator — generates realistic historical options data for backtesting.

NSE does not provide free historical options chain data at strike-level granularity.
This module generates synthetic option chains by applying Black-Scholes pricing
to actual Nifty spot price history, with a realistic volatility smile model.

IMPORTANT: This is synthetic data for strategy validation only.
Before deploying real capital, validate with paper trading or a paid data provider.

DEPRECATED: Use src/data_fetcher_real.py instead — real NSE F&O data from 2018-2024.
Synthetic generator is retained only for live paper trading simulation
when real-time data is unavailable.
"""

import logging
import warnings

warnings.warn(
    "synthetic_data_generator is DEPRECATED for backtesting. "
    "Use src/data_fetcher_real.py instead — real NSE F&O data from 2018-2024. "
    "Synthetic generator is retained only for live paper trading simulation "
    "when real-time data is unavailable.",
    DeprecationWarning,
    stacklevel=2,
)
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from src.iv_calculator import IVCalculator

logger = logging.getLogger(__name__)

HISTORICAL_DIR = Path("data/historical")


class SyntheticDataGenerator:
    """Generates realistic historical option chain snapshots for backtesting."""

    def __init__(self, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()

    def generate_historical_chains(
        self,
        spot_history: pd.DataFrame,
        vix_history: pd.DataFrame | None = None,
        symbol: str = "NIFTY",
        strike_interval: int = 50,
        num_strikes_each_side: int = 20,
    ) -> None:
        """
        Generate daily option chain snapshots for backtesting.

        Args:
            spot_history: DataFrame with columns [date, open, high, low, close]
            vix_history: DataFrame with columns [date, vix]. If None, estimated from returns.
            symbol: Underlying symbol (default "NIFTY")
            strike_interval: Distance between strikes (default 50 for Nifty)
            num_strikes_each_side: Number of strikes above and below ATM (default 20)
        """
        HISTORICAL_DIR.mkdir(parents=True, exist_ok=True)

        if vix_history is None:
            vix_history = self._estimate_vix_from_returns(spot_history)

        # Merge spot and vix
        spot_history = spot_history.copy()
        spot_history["date"] = pd.to_datetime(spot_history["date"])
        vix_history = vix_history.copy()
        vix_history["date"] = pd.to_datetime(vix_history["date"])

        merged = spot_history.merge(vix_history, on="date", how="left")
        merged["vix"] = merged["vix"].ffill().bfill()

        # Generate all monthly expiry dates in the range
        start_date = merged["date"].min()
        end_date = merged["date"].max()
        expiries = self._generate_monthly_expiries(start_date, end_date)

        total_days = len(merged)
        for idx, row in merged.iterrows():
            current_date = row["date"]
            spot_close = row["close"]
            atm_iv = row["vix"] / 100  # VIX is in percentage, convert to decimal

            # Find active expiries (those that haven't expired yet)
            active_expiries = [e for e in expiries if e > current_date]
            if not active_expiries:
                continue

            # Take up to 3 nearest expiries
            active_expiries = active_expiries[:3]

            chain_rows = []
            atm_strike = round(spot_close / strike_interval) * strike_interval

            for expiry in active_expiries:
                dte = (expiry - current_date).days
                if dte <= 0:
                    continue
                T = dte / 365

                for offset in range(-num_strikes_each_side, num_strikes_each_side + 1):
                    strike = atm_strike + offset * strike_interval
                    if strike <= 0:
                        continue

                    moneyness = strike / spot_close

                    for opt_type in ["CE", "PE"]:
                        iv = self._apply_vol_skew(atm_iv, moneyness, dte)

                        # Black-Scholes price
                        bs_price = self.iv_calc._bs_price(
                            spot_close, strike, T, 0.065, iv, opt_type
                        )

                        # Add realistic noise
                        noise = np.random.uniform(-1.5, 1.5)
                        ltp = max(0.5, bs_price + noise)

                        # Bid-ask spread
                        spread = max(0.50, ltp * 0.02)
                        bid = max(0.05, ltp - spread / 2)
                        ask = ltp + spread / 2

                        # Greeks
                        delta = self.iv_calc._bs_delta(
                            spot_close, strike, T, 0.065, iv, opt_type
                        )
                        gamma = self.iv_calc._bs_gamma(
                            spot_close, strike, T, 0.065, iv
                        )
                        theta = self.iv_calc._bs_theta(
                            spot_close, strike, T, 0.065, iv, opt_type
                        )
                        vega = self.iv_calc._bs_vega(
                            spot_close, strike, T, 0.065, iv
                        )

                        # Synthetic OI
                        oi = self._generate_synthetic_oi(strike, spot_close)

                        # Synthetic volume
                        volume = max(10, int(oi * np.random.uniform(0.05, 0.30)))

                        chain_rows.append({
                            "date": current_date.strftime("%Y-%m-%d"),
                            "symbol": symbol,
                            "expiry": expiry.strftime("%Y-%m-%d"),
                            "strike": strike,
                            "option_type": opt_type,
                            "bid": round(bid, 2),
                            "ask": round(ask, 2),
                            "ltp": round(ltp, 2),
                            "close": round(ltp, 2),
                            "iv": round(iv * 100, 2),  # Store as percentage
                            "delta": round(delta, 4),
                            "gamma": round(gamma, 6),
                            "theta": round(theta, 2),
                            "vega": round(vega, 2),
                            "oi": oi,
                            "volume": volume,
                            "underlying_value": round(spot_close, 2),
                        })

            if chain_rows:
                date_str = current_date.strftime("%Y-%m-%d")
                df = pd.DataFrame(chain_rows)
                df.to_csv(
                    HISTORICAL_DIR / f"{symbol}_chain_{date_str}.csv",
                    index=False,
                )

            if (idx + 1) % 100 == 0:
                logger.info(
                    "Generated %d/%d days of synthetic data", idx + 1, total_days
                )

        logger.info(
            "Synthetic data generation complete: %d trading days for %s",
            total_days, symbol,
        )

    def _apply_vol_skew(
        self, atm_iv: float, moneyness: float, dte: int
    ) -> float:
        """
        Realistic IV smile/skew model for Indian index options.

        - Negative skew: puts are more expensive (protective demand)
        - Smile: deep OTM wings have higher IV
        - Term structure: skew flattens with longer DTE
        """
        # Steeper skew: Nifty OTM puts carry significant fear premium
        # Real market: 5% OTM put has ~2-4 vol points higher IV than ATM
        skew_factor = -0.25 * (moneyness - 1.0)
        smile_factor = 0.20 * (moneyness - 1.0) ** 2
        term_adjustment = 1.0 / (1.0 + dte / 365)

        adjusted_iv = atm_iv * (1 + (skew_factor + smile_factor) * term_adjustment)
        return max(adjusted_iv, 0.06)  # Floor at 6% IV

    def _generate_monthly_expiries(
        self, start_date, end_date
    ) -> list:
        """
        Generate last-Thursday-of-month dates between start and end.
        These are the NSE monthly expiry dates for Nifty.
        """
        if isinstance(start_date, str):
            start_date = pd.Timestamp(start_date)
        if isinstance(end_date, str):
            end_date = pd.Timestamp(end_date)

        expiries = []
        current = start_date.replace(day=1)

        while current <= end_date + timedelta(days=90):  # Look ahead for far-month expiries
            # Find last Thursday of this month
            # Go to next month's 1st, then back to find last Thursday
            if current.month == 12:
                next_month = current.replace(year=current.year + 1, month=1, day=1)
            else:
                next_month = current.replace(month=current.month + 1, day=1)

            last_day = next_month - timedelta(days=1)

            # Find last Thursday (weekday 3 = Thursday)
            days_since_thursday = (last_day.weekday() - 3) % 7
            last_thursday = last_day - timedelta(days=days_since_thursday)

            expiries.append(pd.Timestamp(last_thursday))

            # Move to next month
            current = next_month

        return sorted(expiries)

    def _generate_synthetic_oi(
        self, strike: float, underlying: float, total_oi_atm: int = 50000
    ) -> int:
        """
        OI is highest at ATM, decays at wings using Gaussian distribution.
        """
        distance = (strike - underlying) / (underlying * 0.05)
        oi = total_oi_atm * np.exp(-0.5 * distance**2)
        return max(100, int(oi))

    def _estimate_vix_from_returns(
        self, spot_history: pd.DataFrame, window: int = 21
    ) -> pd.DataFrame:
        """
        Estimate VIX from realized volatility when actual VIX history is unavailable.

        VIX typically runs ~15% above realized volatility.
        """
        df = spot_history.copy()
        df["returns"] = df["close"].pct_change()
        df["realized_vol"] = df["returns"].rolling(window).std() * np.sqrt(252)
        df["vix"] = df["realized_vol"] * 100 * 1.15  # Convert to percentage, add premium

        # Fill NaN at the start with a reasonable default
        df["vix"] = df["vix"].bfill().fillna(15.0)

        return df[["date", "vix"]]

    def validate_synthetic_data(self, chain_df: pd.DataFrame) -> dict:
        """
        Sanity checks on generated data.

        Returns dict: {"passed": bool, "failures": list of failure descriptions}
        """
        failures = []

        # 1. No negative prices
        if (chain_df["ltp"] < 0).any():
            failures.append("Negative LTP values found")

        if (chain_df["bid"] < 0).any():
            failures.append("Negative bid values found")

        # 2. CE prices should decrease as strike increases (for same expiry)
        for expiry in chain_df["expiry"].unique():
            ce_data = chain_df[
                (chain_df["expiry"] == expiry) & (chain_df["option_type"] == "CE")
            ].sort_values("strike")
            if len(ce_data) > 1:
                prices = ce_data["ltp"].values
                # Allow small violations due to noise
                violations = sum(
                    1 for i in range(1, len(prices))
                    if prices[i] > prices[i - 1] + 5  # Allow Rs 5 tolerance
                )
                if violations > len(prices) * 0.1:  # >10% violations
                    failures.append(
                        f"CE prices not monotonically decreasing for expiry {expiry}"
                    )

        # 3. PE prices should increase as strike increases
        for expiry in chain_df["expiry"].unique():
            pe_data = chain_df[
                (chain_df["expiry"] == expiry) & (chain_df["option_type"] == "PE")
            ].sort_values("strike")
            if len(pe_data) > 1:
                prices = pe_data["ltp"].values
                violations = sum(
                    1 for i in range(1, len(prices))
                    if prices[i] < prices[i - 1] - 5
                )
                if violations > len(prices) * 0.1:
                    failures.append(
                        f"PE prices not monotonically increasing for expiry {expiry}"
                    )

        # 4. IV > 0 for all rows
        if (chain_df["iv"] <= 0).any():
            failures.append("IV <= 0 found")

        # 5. ATM delta approximately 0.50
        if "underlying_value" in chain_df.columns and "delta" in chain_df.columns:
            underlying = chain_df["underlying_value"].iloc[0]
            atm_ce = chain_df[
                (chain_df["option_type"] == "CE")
                & ((chain_df["strike"] - underlying).abs() < 60)
            ]
            if not atm_ce.empty:
                avg_atm_delta = atm_ce["delta"].mean()
                if not (0.40 < avg_atm_delta < 0.60):
                    failures.append(
                        f"ATM CE delta is {avg_atm_delta:.3f}, expected ~0.50"
                    )

        # 6. Put-call parity (spot check on ATM)
        for expiry in chain_df["expiry"].unique()[:1]:  # Check first expiry only
            underlying = chain_df["underlying_value"].iloc[0]
            atm_strike = round(underlying / 50) * 50
            ce_row = chain_df[
                (chain_df["strike"] == atm_strike)
                & (chain_df["option_type"] == "CE")
                & (chain_df["expiry"] == expiry)
            ]
            pe_row = chain_df[
                (chain_df["strike"] == atm_strike)
                & (chain_df["option_type"] == "PE")
                & (chain_df["expiry"] == expiry)
            ]
            if not ce_row.empty and not pe_row.empty:
                c = ce_row["ltp"].iloc[0]
                p = pe_row["ltp"].iloc[0]
                dte = (pd.Timestamp(expiry) - pd.Timestamp(chain_df["date"].iloc[0])).days
                T = max(dte, 1) / 365
                parity_rhs = underlying - atm_strike * np.exp(-0.065 * T)
                parity_diff = abs((c - p) - parity_rhs)
                tolerance = underlying * 0.05  # 5% of underlying
                if parity_diff > tolerance:
                    failures.append(
                        f"Put-call parity violated: C-P={c-p:.1f}, "
                        f"S-Ke^(-rT)={parity_rhs:.1f}, diff={parity_diff:.1f}"
                    )

        return {
            "passed": len(failures) == 0,
            "failures": failures,
        }
