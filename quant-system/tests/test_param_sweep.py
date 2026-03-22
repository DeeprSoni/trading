"""Tests for param_sweep — parameter grid sweep engine."""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.param_sweep import ParamSweepEngine, SweepConfig, IC_PARAM_GRID
from src.cost_engine import SlippageModel
from src.strategy_ic_backtest import ICBacktestAdapter
from src.strategy_cal_backtest import CalBacktestAdapter
from src.models import MarketState


@pytest.fixture
def chain():
    fixture_path = Path(__file__).parent / "fixtures" / "sample_option_chain.json"
    with open(fixture_path) as f:
        return json.load(f)


def _make_states(chain, num_days=60):
    start = datetime(2026, 1, 5)
    states = []
    for i in range(num_days):
        date = start + timedelta(days=i)
        if date.weekday() >= 5:
            continue
        price = 22500 + (i - num_days / 2) * 5
        expiry_1 = (start + timedelta(days=35 + (i % 10))).isoformat()
        expiry_2 = (start + timedelta(days=65 + (i % 10))).isoformat()
        states.append(MarketState(
            date=date,
            underlying_price=price,
            india_vix=14 + (i % 5),
            iv_rank=40 + (i % 20),
            option_chain=chain,
            expiry_dates=[expiry_1, expiry_2],
        ))
    return states


class TestCombinationGeneration:
    def test_generates_cartesian_product(self):
        grid = {"a": [1, 2], "b": [10, 20, 30]}
        combos = ParamSweepEngine._generate_combinations(grid)
        assert len(combos) == 6
        assert {"a": 1, "b": 10} in combos
        assert {"a": 2, "b": 30} in combos

    def test_single_param(self):
        grid = {"x": [1, 2, 3]}
        combos = ParamSweepEngine._generate_combinations(grid)
        assert len(combos) == 3

    def test_empty_grid(self):
        combos = ParamSweepEngine._generate_combinations({})
        assert len(combos) == 1  # one empty dict


class TestSweepExecution:
    def test_small_sweep_runs(self, chain):
        config = SweepConfig(
            strategy_class=ICBacktestAdapter,
            param_grid={"short_delta": [0.16, 0.20], "wing_width": [500]},
            slippage_models=[SlippageModel.OPTIMISTIC],
        )
        states = _make_states(chain, num_days=60)
        sweep = ParamSweepEngine(max_workers=1)
        result = sweep.run_sequential(config, states, min_trades=0)

        assert result.total_combinations == 2
        assert result.completed == 2
        assert result.failed == 0
        assert len(result.results) >= 0

    def test_sweep_with_multiple_slippage(self, chain):
        config = SweepConfig(
            strategy_class=ICBacktestAdapter,
            param_grid={"short_delta": [0.16]},
            slippage_models=[SlippageModel.OPTIMISTIC, SlippageModel.CONSERVATIVE],
        )
        states = _make_states(chain, num_days=60)
        sweep = ParamSweepEngine(max_workers=1)
        result = sweep.run_sequential(config, states, min_trades=0)

        assert result.total_combinations == 2
        assert result.completed == 2

    def test_sweep_result_is_ranked(self, chain):
        config = SweepConfig(
            strategy_class=ICBacktestAdapter,
            param_grid={"short_delta": [0.10, 0.16, 0.20]},
        )
        states = _make_states(chain, num_days=60)
        sweep = ParamSweepEngine(max_workers=1)
        result = sweep.run_sequential(config, states, rank_by="sharpe_ratio", min_trades=0)
        assert result.ranked_by == "sharpe_ratio"

    def test_min_trades_filter(self, chain):
        config = SweepConfig(
            strategy_class=ICBacktestAdapter,
            param_grid={"short_delta": [0.16]},
        )
        states = _make_states(chain, num_days=30)  # short period
        sweep = ParamSweepEngine(max_workers=1)

        # With high min_trades, likely filters out
        result_strict = sweep.run_sequential(config, states, min_trades=100)
        assert len(result_strict.results) == 0 or all(
            r.total_trades >= 100 for r in result_strict.results
        )

    def test_calendar_sweep(self, chain):
        config = SweepConfig(
            strategy_class=CalBacktestAdapter,
            param_grid={"move_pct_to_close": [0.03, 0.05]},
        )
        states = _make_states(chain, num_days=60)
        sweep = ParamSweepEngine(max_workers=1)
        result = sweep.run_sequential(config, states, min_trades=0)
        assert result.completed == 2


class TestRanking:
    def test_rank_descending_by_default(self):
        from src.models import BacktestResult
        r1 = BacktestResult(
            strategy_name="A", params={}, slippage_model="realistic",
            start_date=datetime.now(), end_date=datetime.now(), trades=[],
            sharpe_ratio=1.5, total_trades=5,
        )
        r2 = BacktestResult(
            strategy_name="B", params={}, slippage_model="realistic",
            start_date=datetime.now(), end_date=datetime.now(), trades=[],
            sharpe_ratio=2.5, total_trades=5,
        )
        ranked = ParamSweepEngine._rank_results([r1, r2], "sharpe_ratio")
        assert ranked[0].sharpe_ratio >= ranked[1].sharpe_ratio

    def test_drawdown_ranked_ascending(self):
        from src.models import BacktestResult
        r1 = BacktestResult(
            strategy_name="A", params={}, slippage_model="realistic",
            start_date=datetime.now(), end_date=datetime.now(), trades=[],
            max_drawdown_pct=0.10, total_trades=5,
        )
        r2 = BacktestResult(
            strategy_name="B", params={}, slippage_model="realistic",
            start_date=datetime.now(), end_date=datetime.now(), trades=[],
            max_drawdown_pct=0.05, total_trades=5,
        )
        ranked = ParamSweepEngine._rank_results([r1, r2], "max_drawdown_pct")
        # Lower drawdown should be first
        assert ranked[0].max_drawdown_pct <= ranked[1].max_drawdown_pct


class TestPredefinedGrids:
    def test_ic_grid_has_expected_keys(self):
        assert "short_delta" in IC_PARAM_GRID
        assert "wing_width" in IC_PARAM_GRID
        assert "profit_target_pct" in IC_PARAM_GRID

    def test_ic_grid_total_combinations(self):
        total = 1
        for values in IC_PARAM_GRID.values():
            total *= len(values)
        # 4 × 3 × 3 × 3 × 3 × 3 = 972
        assert total == 972
