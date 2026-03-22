"""Tests for strategy_cal — Calendar Spread entry gates, rolls, and adjustments."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_cal import CalendarSpreadStrategy

cal = CalendarSpreadStrategy()


def _make_cal_market_data(**overrides):
    """Helper to build market_data dict for calendar spread tests."""
    today = overrides.pop("today", datetime(2026, 3, 10))
    # Front month ~25 DTE, back month ~65 DTE
    front_expiry = today + timedelta(days=25)
    back_expiry = today + timedelta(days=65)

    data = {
        "india_vix": 16.0,
        "expiry_dates": [front_expiry.isoformat(), back_expiry.isoformat()],
        "today": today,
    }
    data.update(overrides)
    return data


# --- Entry Gate Tests ---

class TestCalEntryGates:
    def test_rejects_high_vix(self):
        data = _make_cal_market_data(india_vix=30.0)
        signal = cal.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "VIX" in signal.reason

    def test_rejects_event_proximity(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        today = datetime(2026, 3, 10)
        event_date = (today + timedelta(days=5)).strftime("%Y-%m-%d")
        with open(config_dir / "events_calendar.json", "w") as f:
            json.dump({"events": [{"date": event_date, "name": "RBI Policy", "type": "RBI"}]}, f)

        data = _make_cal_market_data(today=today)
        signal = cal.check_entry_conditions(data)
        assert signal.should_enter is False

    def test_rejects_no_back_month_expiry(self):
        today = datetime(2026, 3, 10)
        # Only a front-month expiry, no 60-75 DTE
        front_only = today + timedelta(days=25)
        data = _make_cal_market_data(expiry_dates=[front_only.isoformat()])
        signal = cal.check_entry_conditions(data)
        assert signal.should_enter is False
        assert "expiry" in signal.reason.lower() or "DTE" in signal.reason

    def test_rejects_no_front_month_expiry(self):
        today = datetime(2026, 3, 10)
        # Only a back-month expiry, no 20-35 DTE
        back_only = today + timedelta(days=65)
        data = _make_cal_market_data(expiry_dates=[back_only.isoformat()])
        signal = cal.check_entry_conditions(data)
        assert signal.should_enter is False

    def test_accepts_all_valid_conditions(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        with open(config_dir / "events_calendar.json", "w") as f:
            json.dump({"events": []}, f)

        data = _make_cal_market_data()
        signal = cal.check_entry_conditions(data)
        assert signal.should_enter is True
        assert len(signal.gate_results) == 4
        assert all(g.passed for g in signal.gate_results)


# --- Roll Condition Tests ---

class TestCalRollConditions:
    def test_roll_when_front_expiring_in_3_days(self):
        now = datetime(2026, 3, 28)
        position = {
            "front_month_expiry": datetime(2026, 3, 30),  # 2 days
            "back_month_expiry": datetime(2026, 5, 28),
            "front_month_entry_premium": 100.0,
        }
        current = {"front_month_current_price": 60.0, "now": now}
        signal = cal.check_roll_conditions(position, current)
        assert signal.should_roll is True
        assert signal.action == "ROLL_FRONT"

    def test_early_roll_at_50_pct_profit(self):
        now = datetime(2026, 3, 10)
        position = {
            "front_month_expiry": datetime(2026, 4, 10),  # Plenty of time
            "back_month_expiry": datetime(2026, 5, 28),
            "front_month_entry_premium": 100.0,
        }
        current = {"front_month_current_price": 45.0, "now": now}  # 55% profit
        signal = cal.check_roll_conditions(position, current)
        assert signal.should_roll is True
        assert signal.action == "ROLL_FRONT"
        assert "50%" in signal.message

    def test_close_when_back_month_at_25_dte(self):
        now = datetime(2026, 5, 5)
        position = {
            "front_month_expiry": datetime(2026, 5, 20),
            "back_month_expiry": datetime(2026, 5, 28),  # 23 DTE
            "front_month_entry_premium": 100.0,
        }
        current = {"front_month_current_price": 80.0, "now": now}
        signal = cal.check_roll_conditions(position, current)
        assert signal.should_roll is True
        assert signal.action == "CLOSE_BACK_MONTH"

    def test_harvest_on_iv_expansion(self):
        now = datetime(2026, 3, 10)
        position = {
            "front_month_expiry": datetime(2026, 4, 10),
            "back_month_expiry": datetime(2026, 5, 28),
            "front_month_entry_premium": 100.0,
        }
        current = {
            "front_month_current_price": 80.0,
            "back_month_iv_change_pct": 35,  # 35% IV expansion
            "now": now,
        }
        signal = cal.check_roll_conditions(position, current)
        assert signal.should_roll is True
        assert signal.action == "HARVEST_AND_CLOSE"

    def test_no_roll_when_healthy(self):
        now = datetime(2026, 3, 10)
        position = {
            "front_month_expiry": datetime(2026, 4, 10),
            "back_month_expiry": datetime(2026, 5, 28),
            "front_month_entry_premium": 100.0,
        }
        current = {"front_month_current_price": 80.0, "now": now}
        signal = cal.check_roll_conditions(position, current)
        assert signal.should_roll is False
        assert signal.action == "NONE"


# --- Adjustment Condition Tests ---

class TestCalAdjustments:
    def test_close_on_4_pct_move(self):
        position = {"strike": 22500}
        # 4.5% move
        current = {"underlying_value": 22500 * 1.045}
        signal = cal.check_adjustment_conditions(position, current)
        assert signal.should_adjust is True
        assert signal.action == "CLOSE"
        assert signal.urgency == "IMMEDIATE"

    def test_centre_on_2_pct_move(self):
        position = {"strike": 22500}
        # 2.5% move (above 2%, below 4%)
        current = {"underlying_value": 22500 * 1.025}
        signal = cal.check_adjustment_conditions(position, current)
        assert signal.should_adjust is True
        assert signal.action == "CENTRE"
        assert signal.urgency == "TODAY"

    def test_no_adjustment_within_range(self):
        position = {"strike": 22500}
        current = {"underlying_value": 22600}  # 0.4% move
        signal = cal.check_adjustment_conditions(position, current)
        assert signal.should_adjust is False
        assert signal.action == "NONE"

    def test_close_on_downside_move(self):
        position = {"strike": 22500}
        # 5% down
        current = {"underlying_value": 22500 * 0.95}
        signal = cal.check_adjustment_conditions(position, current)
        assert signal.should_adjust is True
        assert signal.action == "CLOSE"
