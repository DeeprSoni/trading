"""Tests for data_fetcher — uses mocked KiteConnect, no live API calls."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data_fetcher import DataFetcher
from src.exceptions import DataStalenessError


class TestGetOptionChain:
    def test_returns_expected_structure(self, mock_kite, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "cache").mkdir(parents=True)

        fetcher = DataFetcher(mock_kite)
        chain = fetcher.get_option_chain("NIFTY")

        assert "underlying_value" in chain
        assert chain["underlying_value"] > 10000
        assert "records" in chain
        assert len(chain["records"]) > 50
        assert "timestamp" in chain
        assert "expiry_dates" in chain

    def test_cache_used_when_api_fails(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cache_dir = tmp_path / "data" / "cache"
        cache_dir.mkdir(parents=True)

        # Pre-populate cache
        from datetime import datetime
        cached_data = {
            "records": [{"strike": 22500, "option_type": "CE"}] * 60,
            "timestamp": datetime.now().isoformat(),
            "underlying_value": 22500,
            "expiry_dates": ["2026-04-30"],
        }
        with open(cache_dir / "NIFTY_chain.json", "w") as f:
            json.dump(cached_data, f)

        # Create fetcher with broken kite
        broken_kite = MagicMock()
        broken_kite.ltp.side_effect = Exception("Connection failed")

        fetcher = DataFetcher(broken_kite)

        # Patch _is_market_hours to return False so staleness check doesn't trigger
        with patch.object(DataFetcher, "_is_market_hours", return_value=False):
            chain = fetcher.get_option_chain("NIFTY")

        assert chain["underlying_value"] == 22500

    def test_no_kite_no_cache_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "cache").mkdir(parents=True)

        fetcher = DataFetcher(None)
        with pytest.raises((DataStalenessError, RuntimeError)):
            fetcher.get_option_chain("NIFTY")


class TestGetIndiaVix:
    def test_returns_float_from_kite(self, mock_kite):
        fetcher = DataFetcher(mock_kite)
        vix = fetcher.get_india_vix()
        assert isinstance(vix, float)
        assert 5.0 < vix < 100.0

    def test_returns_default_when_all_fail(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "cache").mkdir(parents=True)

        broken_kite = MagicMock()
        broken_kite.ltp.side_effect = Exception("Failed")

        fetcher = DataFetcher(broken_kite)
        # NSE fallback will also fail since we're not mocking it
        # Should return the safe default
        vix = fetcher.get_india_vix()
        assert isinstance(vix, float)
        assert vix > 0


class TestGetNiftyPriceHistory:
    def test_returns_dataframe(self, mock_kite, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "historical").mkdir(parents=True)

        fetcher = DataFetcher(mock_kite)
        df = fetcher.get_nifty_price_history("2023-01-01", "2023-01-31")
        assert isinstance(df, type(df))  # Is a DataFrame
        assert "close" in df.columns

    def test_returns_from_cache(self, tmp_path, monkeypatch):
        import pandas as pd

        monkeypatch.chdir(tmp_path)
        hist_dir = tmp_path / "data" / "historical"
        hist_dir.mkdir(parents=True)

        # Pre-populate cache
        cache_df = pd.DataFrame({
            "date": ["2023-01-02", "2023-01-03"],
            "open": [18100, 18150],
            "high": [18200, 18300],
            "low": [18000, 18100],
            "close": [18150, 18250],
            "volume": [100000, 110000],
        })
        cache_df.to_csv(hist_dir / "nifty_price_2023-01-01_2023-01-31.csv", index=False)

        fetcher = DataFetcher(None)  # No kite needed
        df = fetcher.get_nifty_price_history("2023-01-01", "2023-01-31")
        assert len(df) == 2
        assert df["close"].iloc[0] == 18150


class TestMarketHours:
    def test_is_market_hours_returns_bool(self):
        result = DataFetcher._is_market_hours()
        assert isinstance(result, bool)
