"""Tests for IC and Calendar backtest adapters — protocol conformance and logic."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_ic_backtest import ICBacktestAdapter
from src.strategy_cal_backtest import CalBacktestAdapter
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


def _make_ic_adapter(**overrides):
    """Create IC adapter with test-friendly defaults (lower min_premium for fixture data)."""
    params = {"min_premium": 10}
    params.update(overrides)
    return ICBacktestAdapter(params=params)


def _make_ic_position(state, adapter):
    """Helper to create a Position from an IC entry."""
    entry = adapter.generate_entry(state)
    assert entry.should_enter, f"Entry failed: {entry.reason}"
    return Position(
        position_id="IC_001",
        strategy_name=adapter.name,
        entry_date=state.date,
        legs=entry.legs,
        lots=1,
        lot_size=25,
        net_premium_per_unit=entry.net_premium_per_unit,
        margin_required=entry.margin_required,
        metadata=entry.metadata,
    )


# --- Protocol Conformance ---

class TestProtocolConformance:
    def test_ic_adapter_conforms(self):
        adapter = ICBacktestAdapter()
        assert isinstance(adapter, BacktestStrategy)

    def test_cal_adapter_conforms(self):
        adapter = CalBacktestAdapter()
        assert isinstance(adapter, BacktestStrategy)

    def test_ic_has_name(self):
        adapter = ICBacktestAdapter()
        assert "IC" in adapter.name

    def test_cal_has_name(self):
        adapter = CalBacktestAdapter()
        assert "CAL" in adapter.name

    def test_ic_has_params(self):
        adapter = ICBacktestAdapter()
        p = adapter.params
        assert "short_delta" in p
        assert "wing_width" in p
        assert "profit_target_pct" in p

    def test_cal_has_params(self):
        adapter = CalBacktestAdapter()
        p = adapter.params
        assert "front_min_dte" in p
        assert "back_min_dte" in p
        assert "move_pct_to_close" in p


# --- IC Entry ---

class TestICEntry:
    def test_rejects_low_iv_rank(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain, iv_rank=10.0)
        assert adapter.should_enter(state) is False

    def test_rejects_high_vix(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain, india_vix=30.0)
        assert adapter.should_enter(state) is False

    def test_rejects_no_dte_window(self, chain):
        adapter = _make_ic_adapter()
        today = datetime(2026, 3, 10)
        state = _make_state(chain, expiry_dates=[(today + timedelta(days=10)).isoformat()])
        assert adapter.should_enter(state) is False

    def test_accepts_valid_conditions(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        assert adapter.should_enter(state) is True

    def test_generate_entry_has_4_legs(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter is True
        assert len(entry.legs) == 4

    def test_entry_has_2_sells_2_buys(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        sells = [l for l in entry.legs if l.side == "SELL"]
        buys = [l for l in entry.legs if l.side == "BUY"]
        assert len(sells) == 2
        assert len(buys) == 2

    def test_entry_net_premium_positive(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.net_premium_per_unit > 0

    def test_custom_params_override(self, chain):
        adapter = ICBacktestAdapter(params={"short_delta": 0.10, "wing_width": 300})
        state = _make_state(chain)
        assert adapter.params["short_delta"] == 0.10
        assert adapter.params["wing_width"] == 300


# --- IC Exit ---

class TestICExit:
    def test_stop_loss_triggers(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Simulate a bad day — make a state where close cost > 2x premium
        bad_chain = json.loads(json.dumps(chain))
        for rec in bad_chain["records"]:
            rec["ltp"] = rec.get("ltp", 100) * 3
            rec["bid"] = rec.get("bid", 100) * 3
            rec["ask"] = rec.get("ask", 100) * 3

        bad_state = MarketState(
            date=state.date + timedelta(days=5),
            underlying_price=23500,
            india_vix=28,
            iv_rank=60,
            option_chain=bad_chain,
            expiry_dates=state.expiry_dates,
        )
        exit_decision = adapter.should_exit(pos, bad_state)
        assert exit_decision.should_exit is True
        assert exit_decision.exit_type == "STOP_LOSS"

    def test_time_stop_triggers(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        expiry = pos.legs[0].expiry_date
        near_expiry_date = expiry - timedelta(days=15)
        late_state = MarketState(
            date=near_expiry_date,
            underlying_price=22500,
            india_vix=16,
            iv_rank=45,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )
        exit_decision = adapter.should_exit(pos, late_state)
        assert exit_decision.should_exit is True
        assert exit_decision.exit_type == "TIME_STOP"

    def test_no_exit_when_within_params(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        next_state = MarketState(
            date=state.date + timedelta(days=1),
            underlying_price=22500,
            india_vix=16,
            iv_rank=45,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )
        exit_decision = adapter.should_exit(pos, next_state)
        assert exit_decision.should_exit is False

    def test_reprice_returns_positive(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)
        close_cost = adapter.reprice_position(pos, state)
        assert close_cost >= 0


# --- Calendar Entry ---

def _make_cal_state(chain):
    """Create a MarketState using the chain's actual expiry dates for calendar tests."""
    today = datetime(2026, 3, 10)
    return MarketState(
        date=today,
        underlying_price=22500.0,
        india_vix=16.0,
        iv_rank=45.0,
        option_chain=chain,
        expiry_dates=chain.get("expiry_dates", [
            (today + timedelta(days=23)).isoformat(),
            (today + timedelta(days=51)).isoformat(),
            (today + timedelta(days=107)).isoformat(),
        ]),
    )


def _cal_adapter():
    """Calendar adapter with DTE ranges matching fixture expiries (23 DTE front, 107 DTE back)."""
    return CalBacktestAdapter(params={
        "front_min_dte": 20, "front_max_dte": 55,
        "back_min_dte": 60, "back_max_dte": 120,
    })


class TestCalEntry:
    def test_rejects_high_vix(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        state.india_vix = 35.0
        assert adapter.should_enter(state) is False

    def test_rejects_no_back_month(self, chain):
        adapter = _cal_adapter()
        today = datetime(2026, 3, 10)
        state = _make_state(chain, expiry_dates=[(today + timedelta(days=25)).isoformat()])
        assert adapter.should_enter(state) is False

    def test_accepts_valid_conditions(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        assert adapter.should_enter(state) is True

    def test_generate_entry_has_2_legs(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter is True
        assert len(entry.legs) == 2

    def test_entry_has_1_buy_1_sell(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        sides = {l.side for l in entry.legs}
        assert sides == {"BUY", "SELL"}

    def test_entry_net_premium_is_debit(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        # Calendar is a debit trade — net_premium should be negative
        assert entry.net_premium_per_unit < 0


# --- Calendar Exit ---

class TestCalExit:
    def test_large_move_triggers_close(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        assert entry.should_enter, f"Entry failed: {entry.reason}"
        pos = Position(
            position_id="CAL_001",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )

        # 5% move
        moved_state = MarketState(
            date=state.date + timedelta(days=3),
            underlying_price=22500 * 1.05,
            india_vix=20,
            iv_rank=50,
            option_chain=chain,
            expiry_dates=state.expiry_dates,
        )
        exit_d = adapter.should_exit(pos, moved_state)
        assert exit_d.should_exit is True
        assert exit_d.exit_type == "ADJUSTMENT"


# --- Parameterisation ---

class TestParamVariations:
    def test_aggressive_ic_params(self, chain):
        adapter = ICBacktestAdapter(params={
            "short_delta": 0.25,
            "wing_width": 300,
            "profit_target_pct": 0.40,
            "stop_loss_multiplier": 3.0,
        })
        assert adapter.params["short_delta"] == 0.25
        assert adapter.params["wing_width"] == 300
        assert "IC" in adapter.name

    def test_tight_calendar_params(self, chain):
        adapter = CalBacktestAdapter(params={
            "move_pct_to_adjust": 0.01,
            "move_pct_to_close": 0.025,
            "profit_target_pct": 0.30,
        })
        assert adapter.params["move_pct_to_adjust"] == 0.01
        assert "CAL" in adapter.name


# --- Variable Cooldown by Exit Reason ---

class TestCooldownByExitReason:
    def test_cooldown_by_exit_reason(self, chain):
        """Cooldown should vary based on exit reason:
        PROFIT_TARGET: 2 days, STOP_LOSS: 7 days, TIME_STOP: 1 day."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)

        # Simulate PROFIT_TARGET exit — should allow entry after 2 days
        adapter._last_exit_date = state.date
        adapter._last_exit_reason = "PROFIT_TARGET"

        # 1 day later — should be blocked (< 2 days)
        state_1d = _make_state(chain, date=state.date + timedelta(days=1))
        assert adapter.should_enter(state_1d) is False

        # 2 days later — should be allowed
        state_2d = _make_state(chain, date=state.date + timedelta(days=2))
        assert adapter.should_enter(state_2d) is True

    def test_stop_loss_has_longer_cooldown(self, chain):
        """STOP_LOSS exit should have 7-day cooldown."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)

        adapter._last_exit_date = state.date
        adapter._last_exit_reason = "STOP_LOSS"

        # 5 days later — should still be blocked (< 7 days)
        state_5d = _make_state(chain, date=state.date + timedelta(days=5))
        assert adapter.should_enter(state_5d) is False

        # 7 days later — should be allowed
        state_7d = _make_state(chain, date=state.date + timedelta(days=7))
        assert adapter.should_enter(state_7d) is True

    def test_time_stop_has_shortest_cooldown(self, chain):
        """TIME_STOP exit should have 1-day cooldown."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)

        adapter._last_exit_date = state.date
        adapter._last_exit_reason = "TIME_STOP"

        # Same day — should be blocked
        assert adapter.should_enter(state) is False

        # 1 day later — should be allowed
        state_1d = _make_state(chain, date=state.date + timedelta(days=1))
        assert adapter.should_enter(state_1d) is True

    def test_exit_sets_last_exit_reason(self, chain):
        """should_exit should set _last_exit_reason alongside _last_exit_date."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Trigger stop loss
        bad_chain = json.loads(json.dumps(chain))
        for rec in bad_chain["records"]:
            rec["ltp"] = rec.get("ltp", 100) * 3
            rec["bid"] = rec.get("bid", 100) * 3
            rec["ask"] = rec.get("ask", 100) * 3

        bad_state = MarketState(
            date=state.date + timedelta(days=5),
            underlying_price=23500,
            india_vix=28,
            iv_rank=60,
            option_chain=bad_chain,
            expiry_dates=state.expiry_dates,
        )
        exit_decision = adapter.should_exit(pos, bad_state)
        assert exit_decision.exit_type == "STOP_LOSS"
        assert adapter._last_exit_reason == "STOP_LOSS"
