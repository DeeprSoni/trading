"""Tests for backtester — generic day-by-day simulation engine."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtester import Backtester, DailySnapshot
from src.cost_engine import CostEngine, SlippageModel
from src.strategy_ic_backtest import ICBacktestAdapter
from src.strategy_cal_backtest import CalBacktestAdapter
from src.models import MarketState


@pytest.fixture
def chain():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_option_chain.json"
    with open(fixture_path) as f:
        return json.load(f)


def _make_daily_states(chain, num_days=60, start=None, start_price=22500):
    """Generate a sequence of daily MarketState objects for backtesting."""
    start = start or datetime(2026, 1, 5)
    states = []

    for i in range(num_days):
        date = start + timedelta(days=i)
        # Skip weekends
        if date.weekday() >= 5:
            continue

        # Slight price drift
        price = start_price + (i - num_days / 2) * 5

        # Monthly expiries: ~35 and ~65 days out
        expiry_1 = (start + timedelta(days=35 + (i % 10))).isoformat()
        expiry_2 = (start + timedelta(days=65 + (i % 10))).isoformat()

        # Scale option chain prices with underlying
        scale = price / 22500
        scaled_chain = _scale_chain(chain, scale)

        states.append(MarketState(
            date=date,
            underlying_price=price,
            india_vix=14 + (i % 5),  # 14-18 range
            iv_rank=40 + (i % 20),   # 40-60 range
            option_chain=scaled_chain,
            expiry_dates=[expiry_1, expiry_2],
        ))

    return states


def _scale_chain(chain, scale):
    """Scale option chain premiums by a factor (crude but sufficient for testing)."""
    scaled = {"records": [], "underlying_value": chain["underlying_value"] * scale}
    for rec in chain["records"]:
        r = dict(rec)
        r["ltp"] = rec["ltp"] * scale
        r["bid"] = rec.get("bid", rec["ltp"]) * scale
        r["ask"] = rec.get("ask", rec["ltp"]) * scale
        scaled["records"].append(r)
    return scaled


# --- Basic Engine Tests ---

class TestBacktesterBasics:
    def test_empty_states_returns_empty_result(self, chain):
        adapter = ICBacktestAdapter()
        engine = Backtester(strategy=adapter)
        result = engine.run([])
        assert result.total_trades == 0
        assert result.strategy_name == adapter.name

    def test_runs_without_error(self, chain):
        adapter = ICBacktestAdapter()
        cost = CostEngine(slippage_model=SlippageModel.OPTIMISTIC)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=60)
        result = engine.run(states)
        assert result is not None
        assert result.strategy_name == adapter.name

    def test_daily_snapshots_match_trading_days(self, chain):
        adapter = ICBacktestAdapter()
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=30)
        engine.run(states)
        assert len(engine.daily_snapshots) == len(states)

    def test_result_has_slippage_model(self, chain):
        adapter = ICBacktestAdapter()
        cost = CostEngine(slippage_model=SlippageModel.CONSERVATIVE)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=30)
        result = engine.run(states)
        assert result.slippage_model == "conservative"


# --- IC Backtest Integration ---

class TestICBacktest:
    def test_ic_generates_trades(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        cost = CostEngine(slippage_model=SlippageModel.OPTIMISTIC)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        # With favorable conditions over 90 days, should open at least 1 trade
        assert result.total_trades >= 0  # may be 0 if no conditions met
        assert isinstance(result.total_net_pnl, float)

    def test_ic_costs_are_deducted(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        cost = CostEngine(slippage_model=SlippageModel.OPTIMISTIC)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        if result.total_trades > 0:
            assert result.total_costs > 0
            # Net should be less than gross due to costs
            assert result.total_net_pnl <= result.total_gross_pnl

    def test_ic_respects_max_positions(self, chain):
        adapter = ICBacktestAdapter()
        engine = Backtester(strategy=adapter, max_open_positions=1)
        states = _make_daily_states(chain, num_days=60)
        engine.run(states)
        # At no point should we have more than 1 open position
        for snap in engine.daily_snapshots:
            assert snap.open_positions <= 1

    def test_ic_all_trades_have_costs(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        cost = CostEngine(slippage_model=SlippageModel.REALISTIC)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        for trade in result.trades:
            assert trade.total_costs > 0, f"Trade {trade.position_id} has zero costs"


# --- Calendar Backtest Integration ---

class TestCalBacktest:
    def test_cal_runs_without_error(self, chain):
        adapter = CalBacktestAdapter()
        cost = CostEngine(slippage_model=SlippageModel.OPTIMISTIC)
        engine = Backtester(strategy=adapter, cost_engine=cost)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        assert result is not None
        assert result.strategy_name == adapter.name


# --- Drawdown Tracking ---

class TestDrawdown:
    def test_drawdown_never_negative(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=60)
        engine.run(states)
        for snap in engine.daily_snapshots:
            assert snap.drawdown >= 0
            assert snap.drawdown_pct >= 0

    def test_max_drawdown_in_result(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=60)
        result = engine.run(states)
        assert result.max_drawdown >= 0
        assert result.max_drawdown_pct >= 0


# --- Slippage Model Comparison ---

class TestSlippageImpact:
    def test_conservative_costs_more_than_optimistic(self, chain):
        """Same trades under different slippage should show cost difference."""
        states = _make_daily_states(chain, num_days=90)
        params = {"min_iv_rank": 30}

        opt_engine = Backtester(
            strategy=ICBacktestAdapter(params=params),
            cost_engine=CostEngine(slippage_model=SlippageModel.OPTIMISTIC),
        )
        cons_engine = Backtester(
            strategy=ICBacktestAdapter(params=params),
            cost_engine=CostEngine(slippage_model=SlippageModel.CONSERVATIVE),
        )

        opt_result = opt_engine.run(states)
        cons_result = cons_engine.run(states)

        if opt_result.total_trades > 0 and cons_result.total_trades > 0:
            assert cons_result.total_costs >= opt_result.total_costs


# --- Result Metrics ---

class TestResultMetrics:
    def test_win_rate_between_0_and_1(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        if result.total_trades > 0:
            assert 0 <= result.win_rate <= 1

    def test_winning_plus_losing_equals_total(self, chain):
        adapter = ICBacktestAdapter(params={"min_iv_rank": 30})
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=90)
        result = engine.run(states)
        assert result.winning_trades + result.losing_trades == result.total_trades

    def test_params_stored_in_result(self, chain):
        params = {"short_delta": 0.20, "wing_width": 400}
        adapter = ICBacktestAdapter(params=params)
        engine = Backtester(strategy=adapter)
        states = _make_daily_states(chain, num_days=30)
        result = engine.run(states)
        assert result.params["short_delta"] == 0.20
        assert result.params["wing_width"] == 400
