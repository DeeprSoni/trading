"""Tests for iv_calculator — Black-Scholes implementation via scipy."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.iv_calculator import IVCalculator


calc = IVCalculator()


class TestBlackScholesPrice:
    def test_bs_price_matches_known_values(self):
        """S=100, K=100, T=1, r=0.05, sigma=0.20, CE -> ~10.45"""
        price = calc._bs_price(100, 100, 1.0, 0.05, 0.20, "CE")
        assert abs(price - 10.45) < 0.10

    def test_bs_call_put_parity(self):
        """C - P = S - K*e^(-rT)"""
        import numpy as np

        S, K, T, r, sigma = 22000, 22000, 30 / 365, 0.065, 0.20
        call = calc._bs_price(S, K, T, r, sigma, "CE")
        put = calc._bs_price(S, K, T, r, sigma, "PE")
        parity = S - K * np.exp(-r * T)
        assert abs((call - put) - parity) < 1.0

    def test_deep_itm_call_near_intrinsic(self):
        """Deep ITM call price should be close to S - K*e^(-rT)."""
        import numpy as np

        S, K, T, r = 22000, 18000, 30 / 365, 0.065
        price = calc._bs_price(S, K, T, r, 0.20, "CE")
        intrinsic = S - K * np.exp(-r * T)
        assert price > intrinsic * 0.99

    def test_deep_otm_call_near_zero(self):
        """Deep OTM call should have very low price."""
        price = calc._bs_price(22000, 30000, 30 / 365, 0.065, 0.20, "CE")
        assert price < 1.0

    def test_at_expiry_returns_intrinsic(self):
        assert calc._bs_price(22000, 21000, 0, 0.065, 0.20, "CE") == 1000.0
        assert calc._bs_price(22000, 23000, 0, 0.065, 0.20, "CE") == 0.0
        assert calc._bs_price(22000, 23000, 0, 0.065, 0.20, "PE") == 1000.0
        assert calc._bs_price(22000, 21000, 0, 0.065, 0.20, "PE") == 0.0


class TestGreeks:
    def test_atm_call_delta_near_0_5(self):
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "CE")
        assert 0.45 < greeks["delta"] < 0.55

    def test_put_delta_is_negative(self):
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "PE")
        assert -0.55 < greeks["delta"] < -0.45

    def test_deep_otm_call_low_delta(self):
        greeks = calc.calculate_greeks(22000, 25000, 30 / 365, 0.20, "CE")
        assert greeks["delta"] < 0.05

    def test_gamma_positive(self):
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "CE")
        assert greeks["gamma"] > 0

    def test_theta_negative_for_long(self):
        """Theta should be negative (time decay hurts long positions)."""
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "CE")
        assert greeks["theta"] < 0

    def test_vega_positive(self):
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "CE")
        assert greeks["vega"] > 0

    def test_theoretical_price_positive(self):
        greeks = calc.calculate_greeks(22000, 22000, 30 / 365, 0.20, "CE")
        assert greeks["theoretical_price"] > 0


class TestImpliedVol:
    def test_implied_vol_roundtrips(self):
        """Price with known vol, then solve back — should recover original vol."""
        original_iv = 0.20
        price = calc._bs_price(22000, 22000, 30 / 365, 0.065, original_iv, "CE")
        recovered_iv = calc._implied_vol(price, 22000, 22000, 30 / 365, 0.065, "CE")
        assert recovered_iv is not None
        assert abs(recovered_iv - original_iv) < 0.001

    def test_implied_vol_put_roundtrips(self):
        original_iv = 0.25
        price = calc._bs_price(22000, 21500, 45 / 365, 0.065, original_iv, "PE")
        recovered_iv = calc._implied_vol(price, 22000, 21500, 45 / 365, 0.065, "PE")
        assert recovered_iv is not None
        assert abs(recovered_iv - original_iv) < 0.001

    def test_implied_vol_returns_none_for_below_intrinsic(self):
        """If market price < intrinsic, IV is undefined."""
        # ITM call with price below intrinsic
        result = calc._implied_vol(500.0, 22000, 21000, 30 / 365, 0.065, "CE")
        assert result is None

    def test_implied_vol_at_expiry_returns_none(self):
        result = calc._implied_vol(100.0, 22000, 22000, 0, 0.065, "CE")
        assert result is None


class TestIVRank:
    def test_iv_rank_returns_none_when_insufficient_history(self, tmp_path, monkeypatch):
        """< 100 days of data -> returns None."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)
        # No CSV files = no history
        rank = calc.calculate_iv_rank("NIFTY", current_iv=20.0)
        assert rank is None


class TestFindStrikeByDelta:
    def test_find_strike_by_delta_returns_correct_strike(self, sample_option_chain):
        strike = calc.find_strike_by_delta(
            sample_option_chain,
            target_delta=0.50,
            option_type="CE",
            time_to_expiry_years=30 / 365,
        )
        # ATM at 22500 — 0.50 delta should be near ATM
        assert 22000 <= strike <= 23000

    def test_find_strike_for_otm_put(self, sample_option_chain):
        strike = calc.find_strike_by_delta(
            sample_option_chain,
            target_delta=0.16,
            option_type="PE",
            time_to_expiry_years=30 / 365,
        )
        # 16-delta put should be well below ATM
        assert strike < 22500


class TestMarketRegime:
    def test_high_vol(self):
        assert calc.classify_market_regime(28, 2.0) == "HIGH_VOL"

    def test_trending(self):
        assert calc.classify_market_regime(18, 7.0) == "TRENDING"

    def test_sideways(self):
        assert calc.classify_market_regime(14, 1.5) == "SIDEWAYS"

    def test_normal(self):
        assert calc.classify_market_regime(20, 4.0) == "NORMAL"
