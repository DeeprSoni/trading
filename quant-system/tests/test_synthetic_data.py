"""Tests for synthetic_data_generator — validates generated options data quality."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.iv_calculator import IVCalculator
from src.synthetic_data_generator import SyntheticDataGenerator


@pytest.fixture
def generator():
    return SyntheticDataGenerator(IVCalculator())


@pytest.fixture
def small_spot_history():
    """5 days of spot data for quick tests."""
    dates = pd.bdate_range("2023-01-02", periods=5)
    np.random.seed(42)
    prices = [18100]
    for _ in range(4):
        prices.append(prices[-1] * (1 + np.random.normal(0.0003, 0.012)))
    return pd.DataFrame({
        "date": dates,
        "open": [p * 0.999 for p in prices],
        "high": [p * 1.005 for p in prices],
        "low": [p * 0.995 for p in prices],
        "close": prices,
        "volume": [300000] * 5,
    })


@pytest.fixture
def small_vix_history():
    """5 days of VIX data matching spot."""
    dates = pd.bdate_range("2023-01-02", periods=5)
    return pd.DataFrame({
        "date": dates,
        "vix": [15.0, 14.8, 15.2, 14.5, 15.1],
    })


class TestSyntheticChainGeneration:
    def test_generates_csv_files(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=5,  # Reduced for speed
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        assert len(csv_files) == 5

    def test_chain_has_required_columns(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=5,
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        chain = pd.read_csv(csv_files[0])

        required_cols = {
            "date", "symbol", "expiry", "strike", "option_type",
            "bid", "ask", "ltp", "close", "iv", "delta", "gamma",
            "theta", "vega", "oi", "volume", "underlying_value",
        }
        assert required_cols.issubset(set(chain.columns))

    def test_chain_has_both_ce_and_pe(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=5,
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        chain = pd.read_csv(csv_files[0])

        assert "CE" in chain["option_type"].values
        assert "PE" in chain["option_type"].values


class TestSyntheticDataValidation:
    def test_passes_validation(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=10,
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        chain = pd.read_csv(csv_files[0])

        result = generator.validate_synthetic_data(chain)
        assert result["passed"], f"Validation failed: {result['failures']}"

    def test_no_negative_prices(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=10,
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        chain = pd.read_csv(csv_files[0])

        assert (chain["ltp"] >= 0).all()
        assert (chain["bid"] >= 0).all()
        assert (chain["ask"] >= 0).all()

    def test_iv_always_positive(self, generator, small_spot_history, small_vix_history, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        generator.generate_historical_chains(
            small_spot_history, small_vix_history, symbol="NIFTY",
            num_strikes_each_side=10,
        )

        csv_files = list((tmp_path / "data" / "historical").glob("NIFTY_chain_*.csv"))
        chain = pd.read_csv(csv_files[0])

        assert (chain["iv"] > 0).all()


class TestVolSkew:
    def test_skew_makes_puts_more_expensive(self, generator):
        """OTM puts (moneyness < 1) should have higher IV than ATM."""
        atm_iv = 0.15
        otm_put_iv = generator._apply_vol_skew(atm_iv, 0.95, 30)
        atm_adjusted = generator._apply_vol_skew(atm_iv, 1.0, 30)
        assert otm_put_iv > atm_adjusted

    def test_skew_floor_at_5_percent(self, generator):
        """IV should never go below 5%."""
        iv = generator._apply_vol_skew(0.06, 1.0, 30)
        assert iv >= 0.05


class TestMonthlyExpiries:
    def test_generates_last_thursdays(self, generator):
        expiries = generator._generate_monthly_expiries("2023-01-01", "2023-06-30")
        assert len(expiries) >= 6

        for exp in expiries:
            # Should all be Thursdays (weekday 3)
            assert exp.weekday() == 3

    def test_expiries_are_sorted(self, generator):
        expiries = generator._generate_monthly_expiries("2023-01-01", "2023-12-31")
        for i in range(1, len(expiries)):
            assert expiries[i] > expiries[i - 1]


class TestVixEstimation:
    def test_estimate_vix_from_returns(self, generator, small_spot_history):
        vix_df = generator._estimate_vix_from_returns(small_spot_history)
        assert "date" in vix_df.columns
        assert "vix" in vix_df.columns
        assert len(vix_df) == len(small_spot_history)
        assert (vix_df["vix"] > 0).all()


class TestSyntheticOI:
    def test_oi_highest_at_atm(self, generator):
        atm_oi = generator._generate_synthetic_oi(22500, 22500)
        otm_oi = generator._generate_synthetic_oi(24000, 22500)
        assert atm_oi > otm_oi

    def test_oi_minimum_100(self, generator):
        oi = generator._generate_synthetic_oi(30000, 22500)  # Very deep OTM
        assert oi >= 100
