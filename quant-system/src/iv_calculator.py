"""
IV Calculator — Black-Scholes pricing and Greeks via scipy.

No external options math libraries (mibian, etc.) — direct implementation
using scipy.stats.norm for the normal distribution functions.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import norm

logger = logging.getLogger(__name__)


class IVCalculator:
    """Computes IV Rank, Greeks, and market regime classification."""

    # --- Core Black-Scholes ---

    @staticmethod
    def _d1(S: float, K: float, T: float, r: float, sigma: float) -> float:
        return (np.log(S / K) + (r + sigma**2 / 2) * T) / (sigma * np.sqrt(T))

    @staticmethod
    def _d2(d1: float, sigma: float, T: float) -> float:
        return d1 - sigma * np.sqrt(T)

    def _bs_price(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """
        Black-Scholes option price.

        S: underlying price
        K: strike price
        T: time to expiry in years (must be > 0)
        r: risk-free rate as decimal (e.g. 0.065)
        sigma: implied volatility as decimal (e.g. 0.20)
        option_type: "CE" (call) or "PE" (put)
        """
        if T <= 0:
            # At expiry, return intrinsic value
            if option_type == "CE":
                return max(S - K, 0.0)
            return max(K - S, 0.0)

        d1 = self._d1(S, K, T, r, sigma)
        d2 = self._d2(d1, sigma, T)

        if option_type == "CE":
            return S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            return K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

    def _bs_delta(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """
        CE delta = N(d1)       — ranges 0 to +1
        PE delta = N(d1) - 1   — ranges -1 to 0
        """
        if T <= 0:
            if option_type == "CE":
                return 1.0 if S > K else 0.0
            return -1.0 if S < K else 0.0

        d1 = self._d1(S, K, T, r, sigma)

        if option_type == "CE":
            return norm.cdf(d1)
        else:
            return norm.cdf(d1) - 1.0

    def _bs_gamma(
        self, S: float, K: float, T: float, r: float, sigma: float
    ) -> float:
        """gamma = N'(d1) / (S * sigma * sqrt(T))"""
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        return norm.pdf(d1) / (S * sigma * np.sqrt(T))

    def _bs_theta(
        self, S: float, K: float, T: float, r: float, sigma: float, option_type: str
    ) -> float:
        """Daily theta in price units (negative = time decay costs money)."""
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        d2 = self._d2(d1, sigma, T)

        common = -(S * norm.pdf(d1) * sigma) / (2 * np.sqrt(T))

        if option_type == "CE":
            annual_theta = common - r * K * np.exp(-r * T) * norm.cdf(d2)
        else:
            annual_theta = common + r * K * np.exp(-r * T) * norm.cdf(-d2)

        return annual_theta / 365  # Convert to daily

    def _bs_vega(
        self, S: float, K: float, T: float, r: float, sigma: float
    ) -> float:
        """Vega per 1% IV change (i.e. per 0.01 change in sigma)."""
        if T <= 0:
            return 0.0
        d1 = self._d1(S, K, T, r, sigma)
        return S * norm.pdf(d1) * np.sqrt(T) / 100

    def _implied_vol(
        self,
        market_price: float,
        S: float,
        K: float,
        T: float,
        r: float,
        option_type: str,
    ) -> float | None:
        """
        Solve for sigma where bs_price(sigma) = market_price.
        Uses scipy.optimize.brentq with bounds [0.01, 5.0].
        Returns None if no solution (market price below intrinsic).
        """
        if T <= 0:
            return None

        intrinsic = max(S - K, 0.0) if option_type == "CE" else max(K - S, 0.0)
        if market_price < intrinsic:
            return None

        def objective(sigma):
            return self._bs_price(S, K, T, r, sigma, option_type) - market_price

        try:
            return brentq(objective, 0.01, 5.0, xtol=1e-6)
        except ValueError:
            logger.warning(
                "IV solver failed: price=%.2f S=%.0f K=%.0f T=%.4f type=%s",
                market_price, S, K, T, option_type,
            )
            return None

    # --- Public API ---

    def calculate_greeks(
        self,
        underlying_price: float,
        strike: float,
        time_to_expiry_years: float,
        iv: float,
        option_type: str,
        risk_free_rate: float = 0.065,
    ) -> dict:
        """
        Calculate all Greeks and theoretical price for an option.

        Returns dict with keys: delta, gamma, theta, vega, theoretical_price
        """
        S, K, T, r, sigma = underlying_price, strike, time_to_expiry_years, risk_free_rate, iv

        return {
            "delta": self._bs_delta(S, K, T, r, sigma, option_type),
            "gamma": self._bs_gamma(S, K, T, r, sigma),
            "theta": self._bs_theta(S, K, T, r, sigma, option_type),
            "vega": self._bs_vega(S, K, T, r, sigma),
            "theoretical_price": self._bs_price(S, K, T, r, sigma, option_type),
        }

    def calculate_iv_rank(
        self, symbol: str, current_iv: float, lookback_days: int = 252
    ) -> float | None:
        """
        IV_Rank = (current_iv - min_iv) / (max_iv - min_iv) * 100

        Loads historical IV from data/historical CSV files.
        Returns None if fewer than 100 days of history available.
        Returns float 0 to 100.
        """
        data_dir = Path("data/historical")
        iv_values = []

        for csv_file in sorted(data_dir.glob(f"{symbol}_chain_*.csv")):
            try:
                df = pd.read_csv(csv_file)
                if "iv" in df.columns:
                    # Use ATM options' IV as representative
                    if "underlying_value" in df.columns and "strike" in df.columns:
                        underlying = df["underlying_value"].iloc[0]
                        atm_mask = (df["strike"] - underlying).abs() < 100
                        atm_ivs = df.loc[atm_mask, "iv"].dropna()
                        if not atm_ivs.empty:
                            iv_values.append(atm_ivs.mean())
                    else:
                        avg_iv = df["iv"].dropna().mean()
                        if not np.isnan(avg_iv):
                            iv_values.append(avg_iv)
            except Exception as e:
                logger.warning("Error reading %s: %s", csv_file, e)
                continue

        if len(iv_values) < 100:
            logger.warning(
                "Only %d days of IV history for %s (need 100+). IV Rank unavailable.",
                len(iv_values), symbol,
            )
            return None

        # Use last `lookback_days` values
        iv_series = iv_values[-lookback_days:]
        min_iv = min(iv_series)
        max_iv = max(iv_series)

        if max_iv == min_iv:
            return 50.0  # No range — return midpoint

        return (current_iv - min_iv) / (max_iv - min_iv) * 100

    def find_strike_by_delta(
        self,
        option_chain: dict,
        target_delta: float,
        option_type: str,
        tolerance: float = 0.03,
        underlying_price: float | None = None,
        time_to_expiry_years: float | None = None,
        risk_free_rate: float = 0.065,
    ) -> int:
        """
        Scan option chain to find strike closest to target_delta.

        For PE options, target_delta should be positive (e.g. 0.16),
        and we compare against abs(calculated_delta).

        Uses pre-computed delta from chain records when available (fast path),
        falls back to Black-Scholes recalculation otherwise.
        """
        if underlying_price is None:
            underlying_price = option_chain["underlying_value"]

        records = option_chain["records"]
        filtered = [r for r in records if r["option_type"] == option_type]

        best_strike = None
        best_distance = float("inf")

        for record in filtered:
            strike = record["strike"]

            # Fast path: use pre-computed delta if available
            if "delta" in record and record["delta"] != 0:
                delta = record["delta"]
            else:
                iv = record.get("iv", 0.20)
                if isinstance(iv, str) or iv <= 0:
                    iv = 0.20
                if iv > 1.0:
                    iv = iv / 100

                T = time_to_expiry_years
                if T is None:
                    T = 30 / 365

                delta = self._bs_delta(underlying_price, strike, T, risk_free_rate, iv, option_type)

            distance = abs(abs(delta) - target_delta)

            if distance < best_distance:
                best_distance = distance
                best_strike = strike

        if best_distance > tolerance:
            logger.debug(
                "Best delta match for %.2f %s is %.3f away (strike=%s).",
                target_delta, option_type, best_distance, best_strike,
            )

        return int(best_strike)

    def classify_market_regime(
        self, vix: float, nifty_monthly_change_pct: float
    ) -> str:
        """
        Classify current market regime. Applied in this order:
          HIGH_VOL  — VIX > 25
          TRENDING  — |monthly change| > 5%
          SIDEWAYS  — |monthly change| < 3% and VIX < 18
          NORMAL    — everything else
        """
        if vix > 25:
            return "HIGH_VOL"
        if abs(nifty_monthly_change_pct) > 5:
            return "TRENDING"
        if abs(nifty_monthly_change_pct) < 3 and vix < 18:
            return "SIDEWAYS"
        return "NORMAL"
