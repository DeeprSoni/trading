"""Tests for strategy_ic — Iron Condor entry gates, exit signals, trade structure."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_ic import IronCondorStrategy
from src.exceptions import InvalidTradeStructureError

ic = IronCondorStrategy()


def _make_market_data(**overrides):
    """Helper to build market_data dict with sensible defaults."""
    today = overrides.pop("today", datetime(2026, 3, 10))
    # Expiry 35 days from today (within 30-45 window)
    expiry = today + timedelta(days=35)

    data = {
        "iv_rank": 45.0,
        "india_vix": 16.0,
        "expiry_dates": [expiry.isoformat()],
        "today": today,
    }
    data.update(overrides)
    return data


# --- Entry Gate Tests ---

class TestICEntryGates:
    def test_rejects_low_iv_rank(self):
        data = _make_market_data(iv_rank=15.0)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "IV Rank" in signal.reason

    def test_rejects_none_iv_rank(self):
        data = _make_market_data(iv_rank=None)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False

    def test_rejects_high_vix(self):
        data = _make_market_data(india_vix=28.0)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "VIX" in signal.reason

    def test_rejects_insufficient_dte_too_low(self):
        today = datetime(2026, 3, 10)
        expiry = today + timedelta(days=20)  # Only 20 DTE
        data = _make_market_data(expiry_dates=[expiry.isoformat()], today=today)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "DTE" in signal.reason or "expiry" in signal.reason.lower()

    def test_rejects_insufficient_dte_too_high(self):
        today = datetime(2026, 3, 10)
        expiry = today + timedelta(days=50)  # 50 DTE, too far
        data = _make_market_data(expiry_dates=[expiry.isoformat()], today=today)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False

    def test_rejects_event_proximity(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import json
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # Event 3 days from today
        today = datetime(2026, 3, 10)
        event_date = (today + timedelta(days=3)).strftime("%Y-%m-%d")
        with open(config_dir / "events_calendar.json", "w") as f:
            json.dump({"events": [{"date": event_date, "name": "RBI Policy", "type": "RBI"}]}, f)

        data = _make_market_data(today=today)
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "event" in signal.reason.lower() or "RBI" in signal.reason

    def test_accepts_all_valid_conditions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        import json
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        # No upcoming events
        with open(config_dir / "events_calendar.json", "w") as f:
            json.dump({"events": []}, f)

        data = _make_market_data()
        signal = ic.check_entry_conditions(data)
        assert signal.should_enter is True
        assert len(signal.gate_results) == 6
        assert all(g.passed for g in signal.gate_results)

    def test_gate_results_always_populated(self):
        """Even on failure, gate_results up to the failing gate should be present."""
        data = _make_market_data(iv_rank=10.0)
        signal = ic.check_entry_conditions(data)
        assert len(signal.gate_results) >= 1
        assert signal.gate_results[0].gate_name == "IV Rank"


# --- Exit Signal Tests ---

class TestICExitSignals:
    def test_stop_loss_at_2x_premium(self):
        position = {"entry_premium": 100.0, "expiry_date": datetime(2026, 4, 30)}
        current = {"current_close_cost": 210.0}  # > 2x
        signal = ic.check_exit_conditions(position, current)
        assert signal.should_exit is True
        assert signal.exit_type == "STOP_LOSS"
        assert signal.urgency == "IMMEDIATE"

    def test_time_stop_at_21_dte(self):
        position = {"entry_premium": 100.0, "expiry_date": datetime(2026, 4, 1)}
        now = datetime(2026, 3, 15)  # 17 days to expiry (< 21)
        current = {"current_close_cost": 50.0, "now": now}
        signal = ic.check_exit_conditions(position, current)
        assert signal.should_exit is True
        assert signal.exit_type == "TIME_STOP"
        assert signal.urgency == "TODAY"

    def test_profit_target_at_50_pct(self):
        position = {"entry_premium": 100.0, "expiry_date": datetime(2026, 5, 30)}
        # Cost to close is 45 => profit = 1 - 45/100 = 55%
        current = {"current_close_cost": 45.0}
        signal = ic.check_exit_conditions(position, current)
        assert signal.should_exit is True
        assert signal.exit_type == "PROFIT_TARGET"
        assert signal.urgency == "TODAY"

    def test_no_exit_when_within_params(self):
        position = {"entry_premium": 100.0, "expiry_date": datetime(2026, 5, 30)}
        current = {"current_close_cost": 70.0}  # 30% profit, not enough
        signal = ic.check_exit_conditions(position, current)
        assert signal.should_exit is False
        assert signal.exit_type == "NONE"

    def test_stop_loss_takes_priority_over_time_stop(self):
        """If both stop loss and time stop are triggered, stop loss wins."""
        position = {"entry_premium": 100.0, "expiry_date": datetime(2026, 3, 25)}
        now = datetime(2026, 3, 15)  # 10 DTE (time stop) AND loss
        current = {"current_close_cost": 220.0, "now": now}  # > 2x (stop loss)
        signal = ic.check_exit_conditions(position, current)
        assert signal.exit_type == "STOP_LOSS"  # Higher priority


# --- Trade Structure Tests ---

class TestICTradeStructure:
    def test_structure_has_positive_net_premium(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        assert ts.net_premium > 0

    def test_structure_max_loss_within_capital_limit(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        max_allowed = 750000 * 0.05  # 5% of total capital
        assert ts.max_loss_per_lot <= max_allowed

    def test_wings_are_500_points_wide(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        assert ts.long_call_strike - ts.short_call_strike == 500
        assert ts.short_put_strike - ts.long_put_strike == 500

    def test_short_call_above_underlying(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        assert ts.short_call_strike > 22500

    def test_short_put_below_underlying(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        assert ts.short_put_strike < 22500

    def test_profit_target_is_half_premium(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        # profit_target_close_price = premium * (1 - 0.50) = premium * 0.50
        expected = ts.net_premium * 0.50
        assert abs(ts.profit_target_close_price - expected) < 0.01

    def test_stop_loss_is_2x_premium(self, sample_option_chain):
        ts = ic.generate_trade_structure(sample_option_chain, 22500.0)
        expected = ts.net_premium * 2.0
        assert abs(ts.stop_loss_close_price - expected) < 0.01
