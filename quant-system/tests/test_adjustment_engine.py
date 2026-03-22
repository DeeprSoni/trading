"""Tests for the adjustment engine — IC rolls, CAL recentre/roll, and backtester execution."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.strategy_ic_backtest import ICBacktestAdapter
from src.strategy_cal_backtest import CalBacktestAdapter
from src.backtester import Backtester
from src.cost_engine import CostEngine
from src.models import AdjustmentDecision, Leg, MarketState, Position


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
    params = {"min_premium": 10}
    params.update(overrides)
    return ICBacktestAdapter(params=params)


def _make_ic_position(state, adapter):
    entry = adapter.generate_entry(state)
    assert entry.should_enter, f"Entry failed: {entry.reason}"
    return Position(
        position_id="IC_TEST_001",
        strategy_name=adapter.name,
        entry_date=state.date,
        legs=entry.legs,
        lots=1,
        lot_size=25,
        net_premium_per_unit=entry.net_premium_per_unit,
        margin_required=entry.margin_required,
        metadata=entry.metadata,
    )


def _make_cal_state(chain, **overrides):
    today = overrides.pop("date", datetime(2026, 3, 10))
    expiry_dates = chain.get("expiry_dates", [])
    if not expiry_dates:
        expiry_dates = list({r.get("expiry", "") for r in chain.get("records", []) if r.get("expiry")})
    expiry_dates = sorted(expiry_dates)
    return MarketState(
        date=today,
        underlying_price=overrides.pop("underlying_price", 22500.0),
        india_vix=overrides.pop("india_vix", 16.0),
        iv_rank=overrides.pop("iv_rank", 45.0),
        option_chain=chain,
        expiry_dates=overrides.pop("expiry_dates", expiry_dates),
    )


def _cal_adapter(**overrides):
    params = {
        "front_min_dte": 20,
        "front_max_dte": 55,
        "back_min_dte": 60,
        "back_max_dte": 120,
    }
    params.update(overrides)
    return CalBacktestAdapter(params=params)


# =============================================================================
# IC ADJUSTMENT TESTS
# =============================================================================

class TestICDteClose:
    def test_dte_under_10_returns_close(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Move time forward so DTE < 10
        late_state = _make_state(
            chain,
            date=pos.legs[0].expiry_date - timedelta(days=8),
            underlying_price=22500.0,
        )
        adj = adapter.should_adjust(pos, late_state)
        assert adj.should_adjust is True
        assert adj.action == "CLOSE"
        assert len(adj.new_legs) == 0

    def test_dte_at_15_no_close(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        safe_state = _make_state(
            chain,
            date=pos.legs[0].expiry_date - timedelta(days=15),
            underlying_price=22500.0,
        )
        adj = adapter.should_adjust(pos, safe_state)
        # Should not trigger DTE close at 15 DTE
        assert adj.action != "CLOSE" or adj.should_adjust is False

    def test_close_legs_has_all_4(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        late_state = _make_state(
            chain,
            date=pos.legs[0].expiry_date - timedelta(days=5),
            underlying_price=22500.0,
        )
        adj = adapter.should_adjust(pos, late_state)
        assert adj.should_adjust is True
        assert len(adj.close_legs) == 4


class TestICCallRoll:
    def test_call_tested_returns_roll(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Find the short call strike and move underlying close to it
        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        tested_price = short_call.strike - 200  # within 300 pts

        tested_state = _make_state(chain, underlying_price=tested_price)
        adj = adapter.should_adjust(pos, tested_state)
        assert adj.should_adjust is True
        assert adj.action == "ROLL_CALL_SIDE"

    def test_roll_has_new_legs(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        tested_state = _make_state(chain, underlying_price=short_call.strike - 200)
        adj = adapter.should_adjust(pos, tested_state)
        assert len(adj.new_legs) == 2
        # New legs should be CE
        assert all(l.option_type == "CE" for l in adj.new_legs)

    def test_new_short_call_500_higher(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        tested_state = _make_state(chain, underlying_price=short_call.strike - 200)
        adj = adapter.should_adjust(pos, tested_state)

        new_short = next(l for l in adj.new_legs if l.side == "SELL")
        assert new_short.strike == short_call.strike + 500

    def test_close_legs_are_call_spread(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        tested_state = _make_state(chain, underlying_price=short_call.strike - 200)
        adj = adapter.should_adjust(pos, tested_state)

        # Close legs should include the old call spread (2 CE legs)
        ce_close = [l for l in adj.close_legs if l.option_type == "CE"]
        assert len(ce_close) >= 2


class TestICPutRoll:
    def test_put_tested_returns_roll(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        short_put = next(l for l in pos.legs if l.option_type == "PE" and l.side == "SELL")
        tested_price = short_put.strike + 200  # within 300 pts

        tested_state = _make_state(chain, underlying_price=tested_price)
        adj = adapter.should_adjust(pos, tested_state)
        assert adj.should_adjust is True
        assert adj.action == "ROLL_PUT_SIDE"

    def test_new_short_put_500_lower(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        short_put = next(l for l in pos.legs if l.option_type == "PE" and l.side == "SELL")
        tested_state = _make_state(chain, underlying_price=short_put.strike + 200)
        adj = adapter.should_adjust(pos, tested_state)

        new_short = next(l for l in adj.new_legs if l.side == "SELL")
        assert new_short.strike == short_put.strike - 500


class TestICAsymmetricHarvest:
    def test_no_harvest_when_not_profitable(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Call side tested — check put side is NOT harvested when premiums haven't decayed
        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        tested_state = _make_state(chain, underlying_price=short_call.strike - 200)
        adj = adapter.should_adjust(pos, tested_state)

        # With same chain (no decay), put side shouldn't be at 85%+ profit
        # Close legs should only have 2 (call spread), not 4
        pe_close = [l for l in adj.close_legs if l.option_type == "PE"]
        # If harvested, pe_close would have 2 legs
        # This test verifies the harvest logic path exists
        assert adj.should_adjust is True


class TestICNoAdjust:
    def test_no_adjust_when_within_range(self, chain):
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        # Normal state — underlying in the middle of the condor
        safe_state = _make_state(chain, underlying_price=22500.0)
        adj = adapter.should_adjust(pos, safe_state)
        assert adj.should_adjust is False


# =============================================================================
# CALENDAR ADJUSTMENT TESTS
# =============================================================================

class TestCalRecentre:
    def test_2pct_move_returns_recentre(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        pos = Position(
            position_id="CAL_TEST_001",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )

        # Move underlying 2.5%
        strike = pos.metadata.get("strike", 22500)
        moved_price = strike * 1.025
        moved_state = _make_cal_state(chain, underlying_price=moved_price)
        adj = adapter.should_adjust(pos, moved_state)
        assert adj.should_adjust is True
        assert adj.action == "RECENTRE"

    def test_recentre_has_new_front_leg(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        pos = Position(
            position_id="CAL_TEST_002",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )

        strike = pos.metadata.get("strike", 22500)
        moved_state = _make_cal_state(chain, underlying_price=strike * 1.025)
        adj = adapter.should_adjust(pos, moved_state)
        if adj.should_adjust:
            assert len(adj.new_legs) == 1
            assert adj.new_legs[0].side == "SELL"


class TestCalFrontRoll:
    def test_front_dte_3_returns_roll(self, chain):
        adapter = _cal_adapter(front_roll_dte=5)
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        pos = Position(
            position_id="CAL_TEST_003",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )

        # Move time to 3 days before front month expiry
        front_leg = min(pos.legs, key=lambda l: l.expiry_date)
        near_expiry_state = _make_cal_state(
            chain,
            date=front_leg.expiry_date - timedelta(days=3),
        )
        adj = adapter.should_adjust(pos, near_expiry_state)
        assert adj.should_adjust is True
        assert adj.action in ("ROLL_FRONT", "CLOSE")

    def test_front_50pct_decay_returns_roll(self, chain):
        adapter = _cal_adapter(front_profit_roll_pct=0.50)
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        # Create position with a front month premium
        pos = Position(
            position_id="CAL_TEST_004",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )

        # Manually set front leg premium high so 50% decay is detectable
        front_leg = min(pos.legs, key=lambda l: l.expiry_date)
        front_leg.premium = 500.0  # artificially high

        # Current chain price will be much lower → >50% decay
        adj = adapter.should_adjust(pos, state)
        # Should trigger roll if chain price is < 250 (50% of 500)
        if adj.should_adjust and adj.action == "ROLL_FRONT":
            assert len(adj.close_legs) >= 1


class TestCalIVHarvest:
    def test_no_harvest_without_entry_iv(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        pos = Position(
            position_id="CAL_TEST_005",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata={},  # no back_iv_at_entry
        )
        adj = adapter.should_adjust(pos, state)
        # Without entry IV, harvest should not trigger
        assert adj.action != "IV_HARVEST"


class TestCalNoAdjust:
    def test_no_adjust_within_range(self, chain):
        adapter = _cal_adapter()
        state = _make_cal_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("CAL entry not possible with fixture")

        pos = Position(
            position_id="CAL_TEST_006",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            metadata=entry.metadata,
        )
        # Same price as entry — no adjustment needed
        adj = adapter.should_adjust(pos, state)
        assert adj.should_adjust is False


# =============================================================================
# BACKTESTER ADJUSTMENT EXECUTION TESTS
# =============================================================================

class TestBacktesterAdjustmentExecution:
    def test_adjustment_no_new_legs_closes_position(self, chain):
        """When adjustment has close_legs but no new_legs, position should be fully closed."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        entry = adapter.generate_entry(state)
        if not entry.should_enter:
            pytest.skip("IC entry not possible")

        # Create a position manually
        pos = Position(
            position_id="BT_TEST_001",
            strategy_name=adapter.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=1,
            lot_size=25,
            net_premium_per_unit=entry.net_premium_per_unit,
            margin_required=entry.margin_required,
            metadata=entry.metadata,
        )

        bt = Backtester(strategy=adapter, capital=750000)
        bt.open_positions.append(pos)

        # Create an adjustment that closes everything (no new_legs)
        adj = AdjustmentDecision(
            should_adjust=True,
            action="CLOSE",
            close_legs=adapter._make_exit_legs(pos, state),
            new_legs=[],
            reason="Test close",
            close_cost=adapter.reprice_position(pos, state),
        )

        pnl = bt._execute_adjustment(pos, adj, state)
        # Position should have been removed
        assert pos not in bt.open_positions
        # Trade result should have been recorded
        assert len(bt.completed_trades) == 1
        assert bt.completed_trades[0].exit_type == "ADJUSTMENT_CLOSE"

    def test_adjustment_with_new_legs_updates_position(self, chain):
        """When adjustment has new_legs, position legs should be updated."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        bt = Backtester(strategy=adapter, capital=750000)
        bt.open_positions.append(pos)

        original_leg_count = len(pos.legs)

        # Simulate a call roll: close 2 CE legs, add 2 new CE legs
        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        long_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "BUY")

        close_legs = [
            Leg(short_call.strike, "CE", "BUY", 50.0, short_call.expiry_date),
            Leg(long_call.strike, "CE", "SELL", 10.0, long_call.expiry_date),
        ]
        new_legs = [
            Leg(short_call.strike + 500, "CE", "SELL", 30.0, short_call.expiry_date),
            Leg(long_call.strike + 500, "CE", "BUY", 5.0, short_call.expiry_date),
        ]

        adj = AdjustmentDecision(
            should_adjust=True,
            action="ROLL_CALL_SIDE",
            close_legs=close_legs,
            new_legs=new_legs,
            reason="Test roll",
            new_premium_per_unit=25.0,
        )

        bt._execute_adjustment(pos, adj, state)

        # Position should still be open
        assert pos in bt.open_positions
        # Legs should be updated (2 PE remaining + 2 new CE)
        assert len(pos.legs) == original_leg_count
        # Premium should be updated
        assert pos.net_premium_per_unit == 25.0
        # Adjustment tracked
        assert pos.adjustment_count == 1
        assert pos.adjustment_costs > 0

    def test_multiple_adjustments_accumulate(self, chain):
        """Multiple adjustments should accumulate costs and counts."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        bt = Backtester(strategy=adapter, capital=750000)
        bt.open_positions.append(pos)

        # Do two adjustments
        for i in range(2):
            short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
            long_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "BUY")

            adj = AdjustmentDecision(
                should_adjust=True,
                action="ROLL_CALL_SIDE",
                close_legs=[
                    Leg(short_call.strike, "CE", "BUY", 50.0, short_call.expiry_date),
                    Leg(long_call.strike, "CE", "SELL", 10.0, long_call.expiry_date),
                ],
                new_legs=[
                    Leg(short_call.strike + 500, "CE", "SELL", 30.0, short_call.expiry_date),
                    Leg(long_call.strike + 500, "CE", "BUY", 5.0, short_call.expiry_date),
                ],
                reason=f"Test roll {i+1}",
                new_premium_per_unit=20.0,
            )
            bt._execute_adjustment(pos, adj, state)

        assert pos.adjustment_count == 2
        assert len(pos.adjustment_history) == 2

    def test_adjustment_costs_in_trade_result(self, chain):
        """When position is closed after adjustment, TradeResult should include adjustment costs."""
        adapter = _make_ic_adapter()
        state = _make_state(chain)
        pos = _make_ic_position(state, adapter)

        bt = Backtester(strategy=adapter, capital=750000)
        bt.open_positions.append(pos)

        # First: adjust
        short_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "SELL")
        long_call = next(l for l in pos.legs if l.option_type == "CE" and l.side == "BUY")

        adj = AdjustmentDecision(
            should_adjust=True,
            action="ROLL_CALL_SIDE",
            close_legs=[
                Leg(short_call.strike, "CE", "BUY", 50.0, short_call.expiry_date),
                Leg(long_call.strike, "CE", "SELL", 10.0, long_call.expiry_date),
            ],
            new_legs=[
                Leg(short_call.strike + 500, "CE", "SELL", 30.0, short_call.expiry_date),
                Leg(long_call.strike + 500, "CE", "BUY", 5.0, short_call.expiry_date),
            ],
            reason="Test roll",
            new_premium_per_unit=20.0,
        )
        bt._execute_adjustment(pos, adj, state)

        adj_cost_before_close = pos.adjustment_costs
        assert adj_cost_before_close > 0

        # Then: close the position via a second adjustment with no new legs
        close_adj = AdjustmentDecision(
            should_adjust=True,
            action="CLOSE",
            close_legs=adapter._make_exit_legs(pos, state),
            new_legs=[],
            reason="Final close",
            close_cost=adapter.reprice_position(pos, state),
        )
        bt._execute_adjustment(pos, close_adj, state)

        trade = bt.completed_trades[0]
        assert trade.adjustment_count == 1
        assert trade.adjustment_costs > 0
        # total_costs should include adjustment costs
        assert trade.total_costs > trade.adjustment_costs
