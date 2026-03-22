"""Tests for strategy_bwb — Broken Wing Butterfly adapter."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_bwb import BrokenWingButterflyAdapter
from src.strategy_ic_backtest import ICBacktestAdapter
from src.strategy_protocol import BacktestStrategy
from src.models import Leg, MarketState, Position


# --- Fixtures ---

@pytest.fixture
def chain():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_option_chain.json"
    with open(fixture_path) as f:
        return json.load(f)


def _make_state(chain, **overrides):
    today = overrides.pop("date", datetime(2026, 3, 10))
    expiry_35 = (today + timedelta(days=35)).isoformat()
    expiry_65 = (today + timedelta(days=65)).isoformat()
    return MarketState(
        date=today,
        underlying_price=overrides.pop("underlying_price", 22500.0),
        india_vix=overrides.pop("india_vix", 16.0),
        iv_rank=overrides.pop("iv_rank", 45.0),
        option_chain=chain,
        expiry_dates=overrides.pop("expiry_dates", [expiry_35, expiry_65]),
    )


def _make_bwb_adapter(**overrides):
    """Create BWB adapter with test-friendly defaults."""
    params = {"min_premium": 10}
    params.update(overrides)
    return BrokenWingButterflyAdapter(params=params)


def _make_bwb_position(state, adapter):
    """Helper to create a Position from a BWB entry."""
    entry = adapter.generate_entry(state)
    assert entry.should_enter, f"Entry failed: {entry.reason}"
    return Position(
        position_id="BWB_001",
        strategy_name=adapter.name,
        entry_date=state.date,
        legs=entry.legs,
        lots=1,
        lot_size=25,
        net_premium_per_unit=entry.net_premium_per_unit,
        margin_required=entry.margin_required,
        metadata=entry.metadata,
    )


# --- Test: entry gates same as IC ---

class TestBWBEntryGates:
    def test_entry_gates_same_as_ic(self, chain):
        """BWB should reject on same conditions as IC: low IV rank, high VIX, no DTE."""
        bwb = _make_bwb_adapter()
        ic = ICBacktestAdapter(params={"min_premium": 10})

        # Low IV rank
        state_low_iv = _make_state(chain, iv_rank=10.0)
        assert bwb.should_enter(state_low_iv) is False
        assert ic.should_enter(state_low_iv) is False

        # High VIX
        state_high_vix = _make_state(chain, india_vix=30.0)
        assert bwb.should_enter(state_high_vix) is False
        assert ic.should_enter(state_high_vix) is False

        # No valid DTE
        today = datetime(2026, 3, 10)
        state_no_dte = _make_state(chain, expiry_dates=[(today + timedelta(days=10)).isoformat()])
        assert bwb.should_enter(state_no_dte) is False
        assert ic.should_enter(state_no_dte) is False

        # Valid conditions — both should accept
        state_valid = _make_state(chain)
        assert bwb.should_enter(state_valid) is True
        assert ic.should_enter(state_valid) is True


# --- Test: has 5 legs ---

class TestBWBLegs:
    def test_has_5_legs(self, chain):
        """BWB should have 5 legs: 2 short puts, 1 long put, 1 short call, 1 long call."""
        adapter = _make_bwb_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter is True
        assert len(entry.legs) == 5

    def test_leg_composition(self, chain):
        """Verify the exact composition: 2 short puts, 1 long put, 1 short call, 1 long call."""
        adapter = _make_bwb_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter is True

        short_puts = [l for l in entry.legs if l.option_type == "PE" and l.side == "SELL"]
        long_puts = [l for l in entry.legs if l.option_type == "PE" and l.side == "BUY"]
        short_calls = [l for l in entry.legs if l.option_type == "CE" and l.side == "SELL"]
        long_calls = [l for l in entry.legs if l.option_type == "CE" and l.side == "BUY"]

        assert len(short_puts) == 2, f"Expected 2 short puts, got {len(short_puts)}"
        assert len(long_puts) == 1, f"Expected 1 long put, got {len(long_puts)}"
        assert len(short_calls) == 1, f"Expected 1 short call, got {len(short_calls)}"
        assert len(long_calls) == 1, f"Expected 1 long call, got {len(long_calls)}"


# --- Test: stop loss tighter than IC ---

class TestBWBStopLoss:
    def test_stop_loss_tighter_than_ic(self):
        """BWB default stop loss multiplier (1.5x) should be less than IC (2.0x)."""
        bwb = BrokenWingButterflyAdapter()
        ic = ICBacktestAdapter()
        assert bwb.params["stop_loss_multiplier"] == 1.5
        assert ic.params["stop_loss_multiplier"] == 2.0
        assert bwb.params["stop_loss_multiplier"] < ic.params["stop_loss_multiplier"]


# --- Test: extra credit from second put ---

class TestBWBExtraCredit:
    def test_extra_credit_from_second_put(self, chain):
        """BWB should collect more premium than IC due to the second short put."""
        bwb = _make_bwb_adapter()
        ic = ICBacktestAdapter(params={"min_premium": 10})

        state = _make_state(chain)
        bwb_entry = bwb.generate_entry(state)
        ic_entry = ic.generate_entry(state)

        assert bwb_entry.should_enter is True
        assert ic_entry.should_enter is True
        # BWB has 2 short puts vs IC's 1, so it collects more premium
        assert bwb_entry.net_premium_per_unit > ic_entry.net_premium_per_unit


# --- Test: conforms to protocol ---

class TestBWBProtocol:
    def test_conforms_to_protocol(self):
        """BWB adapter must implement the BacktestStrategy protocol."""
        adapter = BrokenWingButterflyAdapter()
        assert isinstance(adapter, BacktestStrategy)

    def test_has_name(self):
        adapter = BrokenWingButterflyAdapter()
        assert "BWB" in adapter.name

    def test_has_params(self):
        adapter = BrokenWingButterflyAdapter()
        p = adapter.params
        assert "short_delta" in p
        assert "wing_width" in p
        assert "bwb_put_ratio" in p
        assert p["bwb_put_ratio"] == 2
