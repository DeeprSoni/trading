"""Tests for strategy_strangle — Strangle-to-IC Conversion adapter."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_strangle import StrangleToICAdapter
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
        india_vix=overrides.pop("india_vix", 30.0),   # Strangle needs 28-35
        iv_rank=overrides.pop("iv_rank", 50.0),        # Strangle needs >= 35
        option_chain=chain,
        expiry_dates=overrides.pop("expiry_dates", [expiry_35, expiry_65]),
    )


def _make_strangle_adapter(**overrides):
    """Create strangle adapter with test-friendly defaults."""
    params = {"min_premium": 10}
    params.update(overrides)
    return StrangleToICAdapter(params=params)


def _make_strangle_position(state, adapter):
    """Helper to create a Position from a strangle entry."""
    entry = adapter.generate_entry(state)
    assert entry.should_enter, f"Entry failed: {entry.reason}"
    return Position(
        position_id="STR_001",
        strategy_name=adapter.name,
        entry_date=state.date,
        legs=entry.legs,
        lots=1,
        lot_size=75,
        net_premium_per_unit=entry.net_premium_per_unit,
        margin_required=entry.margin_required,
        metadata=entry.metadata,
    )


# --- Test: Entry requires high VIX ---

class TestStrangleEntryGates:
    def test_entry_requires_high_vix(self, chain):
        """VIX < 28 should be rejected — strangle needs elevated premium."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain, india_vix=25.0)
        assert adapter.should_enter(state) is False

    def test_entry_rejects_too_high_vix(self, chain):
        """VIX > 35 should also be rejected — too volatile for naked exposure."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain, india_vix=40.0)
        assert adapter.should_enter(state) is False

    def test_entry_requires_high_ivr(self, chain):
        """IVR < 35 should be rejected — higher threshold than IC."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain, iv_rank=30.0)
        assert adapter.should_enter(state) is False

    def test_entry_accepts_valid_conditions(self, chain):
        """All gates passed: VIX 28-35, IVR >= 35, valid DTE."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        assert adapter.should_enter(state) is True

    def test_entry_rejects_no_dte_window(self, chain):
        """No expiry within 30-45 DTE should be rejected."""
        adapter = _make_strangle_adapter()
        today = datetime(2026, 3, 10)
        state = _make_state(chain, expiry_dates=[(today + timedelta(days=10)).isoformat()])
        assert adapter.should_enter(state) is False


# --- Test: Initial position has 2 legs ---

class TestStrangleLegs:
    def test_initial_position_has_2_legs(self, chain):
        """Strangle entry should have exactly 2 legs: short call + short put, no wings."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter is True
        assert len(entry.legs) == 2

    def test_both_legs_are_sells(self, chain):
        """Both legs should be SELL — naked short strangle."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert all(leg.side == "SELL" for leg in entry.legs)

    def test_one_ce_one_pe(self, chain):
        """Should have one CE and one PE."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        types = {leg.option_type for leg in entry.legs}
        assert types == {"CE", "PE"}

    def test_net_premium_positive(self, chain):
        """Net premium should be positive (credit trade)."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.net_premium_per_unit > 0

    def test_metadata_has_entry_underlying(self, chain):
        """Metadata should store entry_underlying for emergency wing check."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert "entry_underlying" in entry.metadata
        assert entry.metadata["entry_underlying"] == 22500.0

    def test_metadata_converted_false(self, chain):
        """Metadata should have converted=False at entry."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.metadata["converted"] is False


# --- Test: Conversion adds wings ---

class TestStrangleConversion:
    def test_conversion_adds_wings(self, chain):
        """When profit >= 30%, should_adjust returns 2 new BUY legs (wings)."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        # Create a state where the position is profitable (options have decayed)
        decayed_chain = json.loads(json.dumps(chain))
        for rec in decayed_chain["records"]:
            # Reduce all premiums to simulate theta decay -> profit
            rec["ltp"] = rec.get("ltp", 100) * 0.3
            rec["bid"] = rec.get("bid", 100) * 0.3
            rec["ask"] = rec.get("ask", 100) * 0.3

        profit_state = MarketState(
            date=state.date + timedelta(days=10),
            underlying_price=22500.0,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=decayed_chain,
            expiry_dates=state.expiry_dates,
        )

        adj = adapter.should_adjust(pos, profit_state)
        assert adj.should_adjust is True
        assert adj.action == "CONVERT_TO_IC"
        assert len(adj.new_legs) == 2
        # Both new legs should be BUY (wings)
        assert all(leg.side == "BUY" for leg in adj.new_legs)
        # One CE wing and one PE wing
        wing_types = {leg.option_type for leg in adj.new_legs}
        assert wing_types == {"CE", "PE"}

    def test_conversion_wing_strikes_correct(self, chain):
        """Wing strikes should be at short_strike +/- wing_width (500 pts)."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        short_call_strike = pos.metadata["short_call_strike"]
        short_put_strike = pos.metadata["short_put_strike"]

        # Decayed chain for profit
        decayed_chain = json.loads(json.dumps(chain))
        for rec in decayed_chain["records"]:
            rec["ltp"] = rec.get("ltp", 100) * 0.3
            rec["bid"] = rec.get("bid", 100) * 0.3
            rec["ask"] = rec.get("ask", 100) * 0.3

        profit_state = MarketState(
            date=state.date + timedelta(days=10),
            underlying_price=22500.0,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=decayed_chain,
            expiry_dates=state.expiry_dates,
        )

        adj = adapter.should_adjust(pos, profit_state)
        assert adj.should_adjust is True

        ce_wing = [l for l in adj.new_legs if l.option_type == "CE"][0]
        pe_wing = [l for l in adj.new_legs if l.option_type == "PE"][0]
        assert ce_wing.strike == short_call_strike + 500
        assert pe_wing.strike == short_put_strike - 500

    def test_no_conversion_when_already_converted(self, chain):
        """After conversion, should_adjust should return False."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)
        pos.metadata["converted"] = True

        next_state = MarketState(
            date=state.date + timedelta(days=5),
            underlying_price=22500.0,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )

        adj = adapter.should_adjust(pos, next_state)
        assert adj.should_adjust is False


# --- Test: Emergency wing buy on 2% move ---

class TestEmergencyWingBuy:
    def test_emergency_wing_buy_on_2pct_move(self, chain):
        """2%+ spot move should trigger immediate wing buy regardless of profit."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        # 2.5% move up (22500 -> 23062.5)
        moved_state = MarketState(
            date=state.date + timedelta(days=2),
            underlying_price=22500.0 * 1.025,
            india_vix=32.0,
            iv_rank=55.0,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )

        adj = adapter.should_adjust(pos, moved_state)
        assert adj.should_adjust is True
        assert adj.action == "CONVERT_TO_IC"
        assert len(adj.new_legs) == 2
        assert "Emergency" in adj.reason

    def test_no_emergency_on_small_move(self, chain):
        """1% move should NOT trigger emergency wing buy."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        # 1% move (22500 -> 22725) — below 2% threshold
        small_move_state = MarketState(
            date=state.date + timedelta(days=2),
            underlying_price=22500.0 * 1.01,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )

        adj = adapter.should_adjust(pos, small_move_state)
        # Should not trigger emergency (and no profit-based conversion either
        # since premiums haven't decayed)
        assert adj.should_adjust is False or "Emergency" not in adj.reason


# --- Test: Exit uses correct stop loss ---

class TestStrangleExit:
    def test_stop_loss_uses_pre_conversion_multiplier(self, chain):
        """Before conversion, stop loss should be 1.0x premium."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        # Make close cost exceed 1.0x premium -> stop loss
        bad_chain = json.loads(json.dumps(chain))
        for rec in bad_chain["records"]:
            rec["ltp"] = rec.get("ltp", 100) * 3
            rec["bid"] = rec.get("bid", 100) * 3
            rec["ask"] = rec.get("ask", 100) * 3

        bad_state = MarketState(
            date=state.date + timedelta(days=5),
            underlying_price=23500,
            india_vix=32.0,
            iv_rank=55.0,
            option_chain=bad_chain,
            expiry_dates=state.expiry_dates,
        )
        exit_d = adapter.should_exit(pos, bad_state)
        assert exit_d.should_exit is True
        assert exit_d.exit_type == "STOP_LOSS"

    def test_no_exit_when_within_params(self, chain):
        """Normal conditions should not trigger exit."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        next_state = MarketState(
            date=state.date + timedelta(days=1),
            underlying_price=22500,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )
        exit_d = adapter.should_exit(pos, next_state)
        assert exit_d.should_exit is False

    def test_time_stop_triggers(self, chain):
        """DTE <= 21 should trigger time stop."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        expiry = pos.legs[0].expiry_date
        near_expiry_date = expiry - timedelta(days=15)
        late_state = MarketState(
            date=near_expiry_date,
            underlying_price=22500,
            india_vix=30.0,
            iv_rank=50.0,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )
        exit_d = adapter.should_exit(pos, late_state)
        assert exit_d.should_exit is True
        assert exit_d.exit_type == "TIME_STOP"


# --- Test: Reprice works for both 2 and 4 legs ---

class TestStrangleReprice:
    def test_reprice_2_legs(self, chain):
        """Reprice should work for initial 2-leg strangle."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)
        close_cost = adapter.reprice_position(pos, state)
        assert close_cost >= 0

    def test_reprice_4_legs(self, chain):
        """Reprice should work after conversion to 4-leg IC."""
        adapter = _make_strangle_adapter()
        state = _make_state(chain)
        pos = _make_strangle_position(state, adapter)

        # Add wing legs manually to simulate conversion
        short_call_strike = pos.metadata["short_call_strike"]
        short_put_strike = pos.metadata["short_put_strike"]
        expiry = pos.legs[0].expiry_date

        lc_mid = adapter._get_mid(chain, short_call_strike + 500, "CE")
        lp_mid = adapter._get_mid(chain, short_put_strike - 500, "PE")

        pos.legs.append(Leg(short_call_strike + 500, "CE", "BUY", lc_mid, expiry))
        pos.legs.append(Leg(short_put_strike - 500, "PE", "BUY", lp_mid, expiry))
        pos.metadata["converted"] = True

        close_cost = adapter.reprice_position(pos, state)
        assert close_cost >= 0
        assert len(pos.legs) == 4


# --- Test: Protocol conformance ---

class TestStrangleProtocol:
    def test_conforms_to_protocol(self):
        """StrangleToICAdapter must implement the BacktestStrategy protocol."""
        adapter = StrangleToICAdapter()
        assert isinstance(adapter, BacktestStrategy)

    def test_has_name(self):
        adapter = StrangleToICAdapter()
        assert "STRANGLE" in adapter.name

    def test_has_params(self):
        adapter = StrangleToICAdapter()
        p = adapter.params
        assert "short_delta" in p
        assert "wing_width" in p
        assert "min_vix" in p
        assert "max_vix" in p
        assert "min_iv_rank" in p
        assert "conversion_profit_pct" in p
        assert "emergency_wing_move_pct" in p
        assert p["min_vix"] == 28
        assert p["max_vix"] == 35
        assert p["min_iv_rank"] == 35
        assert p["stop_loss_multiplier"] == 1.0
        assert p["converted_stop_loss"] == 2.0
