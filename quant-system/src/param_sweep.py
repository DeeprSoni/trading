"""
Parameter Sweep Engine — runs cartesian product of strategy parameter
variations through the backtester and ranks results.

Uses ProcessPoolExecutor for parallel execution across CPU cores.
"""

import itertools
import logging
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from src.backtester import Backtester
from src.cost_engine import CostEngine, SlippageModel
from src.models import BacktestResult, MarketState

logger = logging.getLogger(__name__)


@dataclass
class SweepConfig:
    """Configuration for a parameter sweep run."""
    strategy_class: type                    # e.g. ICBacktestAdapter
    param_grid: dict[str, list]            # e.g. {"short_delta": [0.10, 0.16, 0.20]}
    slippage_models: list[SlippageModel] = field(
        default_factory=lambda: [SlippageModel.REALISTIC]
    )
    capital: float = 750000.0
    max_open_positions: int = 2


@dataclass
class SweepResult:
    """Result of a parameter sweep — all backtest results ranked."""
    total_combinations: int
    completed: int
    failed: int
    elapsed_seconds: float
    results: list[BacktestResult]
    ranked_by: str = "sharpe_ratio"


def _run_single_backtest(
    strategy_class: type,
    params: dict,
    daily_states_data: list[dict],
    slippage_model: str,
    capital: float,
    max_open_positions: int,
) -> BacktestResult | None:
    """
    Run a single backtest (designed to be called in a subprocess).

    daily_states_data is serialised dicts because MarketState may not pickle cleanly.
    """
    try:
        # Reconstruct MarketState objects
        states = []
        for sd in daily_states_data:
            states.append(MarketState(
                date=datetime.fromisoformat(sd["date"]),
                underlying_price=sd["underlying_price"],
                india_vix=sd["india_vix"],
                iv_rank=sd["iv_rank"],
                option_chain=sd["option_chain"],
                expiry_dates=sd["expiry_dates"],
            ))

        slippage = SlippageModel(slippage_model)
        strategy = strategy_class(params=params)
        cost_engine = CostEngine(slippage_model=slippage)
        backtester = Backtester(
            strategy=strategy,
            cost_engine=cost_engine,
            capital=capital,
            max_open_positions=max_open_positions,
        )
        return backtester.run(states)
    except Exception as e:
        logger.error("Backtest failed for params %s: %s", params, e)
        return None


class ParamSweepEngine:
    """
    Runs a grid of parameter combinations through the backtester.

    Usage:
        sweep = ParamSweepEngine()
        config = SweepConfig(
            strategy_class=ICBacktestAdapter,
            param_grid={"short_delta": [0.10, 0.16, 0.20], "wing_width": [300, 500]},
        )
        result = sweep.run(config, daily_states)
    """

    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers

    def run(
        self,
        config: SweepConfig,
        daily_states: list[MarketState],
        rank_by: str = "sharpe_ratio",
        min_trades: int = 3,
    ) -> SweepResult:
        """
        Execute parameter sweep.

        rank_by: metric to sort results (sharpe_ratio, sortino_ratio, total_net_pnl,
                 profit_factor, calmar_ratio, win_rate, max_drawdown_pct)
        min_trades: minimum trades to be included in ranking (filters noise)
        """
        # Generate all param combinations
        param_combos = self._generate_combinations(config.param_grid)
        total_runs = len(param_combos) * len(config.slippage_models)

        logger.info(
            "Starting sweep: %d param combos × %d slippage models = %d runs",
            len(param_combos), len(config.slippage_models), total_runs,
        )

        # Serialise states for subprocess pickling
        states_data = self._serialise_states(daily_states)

        start_time = time.time()
        results: list[BacktestResult] = []
        failed = 0

        # Run all combinations
        jobs = []
        for params in param_combos:
            for slippage in config.slippage_models:
                jobs.append((params, slippage))

        # Use ProcessPoolExecutor for true parallelism
        if self.max_workers == 1 or total_runs <= 4:
            # Sequential for small runs or debugging
            for params, slippage in jobs:
                result = _run_single_backtest(
                    config.strategy_class, params, states_data,
                    slippage.value, config.capital, config.max_open_positions,
                )
                if result is not None:
                    results.append(result)
                else:
                    failed += 1
        else:
            with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
                futures = {}
                for params, slippage in jobs:
                    future = executor.submit(
                        _run_single_backtest,
                        config.strategy_class, params, states_data,
                        slippage.value, config.capital, config.max_open_positions,
                    )
                    futures[future] = (params, slippage)

                for future in as_completed(futures):
                    params, slippage = futures[future]
                    try:
                        result = future.result()
                        if result is not None:
                            results.append(result)
                        else:
                            failed += 1
                    except Exception as e:
                        logger.error("Future failed for %s: %s", params, e)
                        failed += 1

        elapsed = time.time() - start_time

        # Filter by minimum trades and rank
        filtered = [r for r in results if r.total_trades >= min_trades]
        ranked = self._rank_results(filtered, rank_by)

        logger.info(
            "Sweep complete: %d/%d succeeded, %d filtered (min %d trades), %.1fs elapsed",
            len(results), total_runs, len(filtered), min_trades, elapsed,
        )

        return SweepResult(
            total_combinations=total_runs,
            completed=len(results),
            failed=failed,
            elapsed_seconds=round(elapsed, 2),
            results=ranked,
            ranked_by=rank_by,
        )

    def run_sequential(
        self,
        config: SweepConfig,
        daily_states: list[MarketState],
        rank_by: str = "sharpe_ratio",
        min_trades: int = 3,
    ) -> SweepResult:
        """Run sweep sequentially (simpler, no subprocess overhead)."""
        param_combos = self._generate_combinations(config.param_grid)
        total_runs = len(param_combos) * len(config.slippage_models)

        start_time = time.time()
        results: list[BacktestResult] = []
        failed = 0

        for params in param_combos:
            for slippage in config.slippage_models:
                try:
                    strategy = config.strategy_class(params=params)
                    cost_engine = CostEngine(slippage_model=slippage)
                    backtester = Backtester(
                        strategy=strategy,
                        cost_engine=cost_engine,
                        capital=config.capital,
                        max_open_positions=config.max_open_positions,
                    )
                    result = backtester.run(daily_states)
                    results.append(result)
                except Exception as e:
                    logger.error("Backtest failed: params=%s, err=%s", params, e)
                    failed += 1

        elapsed = time.time() - start_time
        filtered = [r for r in results if r.total_trades >= min_trades]
        ranked = self._rank_results(filtered, rank_by)

        return SweepResult(
            total_combinations=total_runs,
            completed=len(results),
            failed=failed,
            elapsed_seconds=round(elapsed, 2),
            results=ranked,
            ranked_by=rank_by,
        )

    @staticmethod
    def _generate_combinations(param_grid: dict[str, list]) -> list[dict]:
        """Generate cartesian product of all parameter values."""
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    @staticmethod
    def _rank_results(results: list[BacktestResult], rank_by: str) -> list[BacktestResult]:
        """Sort results by the specified metric (descending, except drawdown)."""
        reverse = rank_by != "max_drawdown_pct"  # lower drawdown is better
        try:
            return sorted(results, key=lambda r: getattr(r, rank_by, 0), reverse=reverse)
        except (TypeError, AttributeError):
            return results

    @staticmethod
    def _serialise_states(states: list[MarketState]) -> list[dict]:
        """Convert MarketState objects to dicts for subprocess pickling."""
        return [
            {
                "date": s.date.isoformat(),
                "underlying_price": s.underlying_price,
                "india_vix": s.india_vix,
                "iv_rank": s.iv_rank,
                "option_chain": s.option_chain,
                "expiry_dates": [
                    e.isoformat() if isinstance(e, datetime) else str(e)
                    for e in s.expiry_dates
                ],
            }
            for s in states
        ]


# --- Predefined Parameter Grids ---

IC_PARAM_GRID = {
    "short_delta": [0.10, 0.16, 0.20, 0.25],
    "wing_width": [300, 500, 700],
    "profit_target_pct": [0.40, 0.50, 0.65],
    "stop_loss_multiplier": [1.5, 2.0, 3.0],
    "time_stop_dte": [14, 21, 28],
    "min_iv_rank": [20, 30, 40],
}

CAL_PARAM_GRID = {
    "move_pct_to_adjust": [0.015, 0.02, 0.03],
    "move_pct_to_close": [0.03, 0.04, 0.05],
    "profit_target_pct": [0.30, 0.50, 0.75],
    "back_month_close_dte": [20, 25, 30],
    "front_roll_dte": [2, 3, 5],
    "max_vix": [25, 28, 32],
}
