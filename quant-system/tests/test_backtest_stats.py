"""Tests for backtest_stats — statistical analysis of backtest results."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.backtest_stats import BacktestStatAnalyser, ConfidenceInterval
from src.models import BacktestResult, TradeResult, Leg


def _make_trade(pnl, days_offset=0, vix=16):
    """Create a minimal TradeResult for stats testing."""
    entry = datetime(2026, 1, 10) + timedelta(days=days_offset)
    exit = entry + timedelta(days=14)
    return TradeResult(
        position_id=f"T_{days_offset}",
        strategy_name="TEST",
        entry_date=entry,
        exit_date=exit,
        entry_legs=[],
        exit_legs=[],
        lots=1,
        lot_size=25,
        net_premium_per_unit=100,
        close_cost_per_unit=50 if pnl > 0 else 150,
        gross_pnl=pnl + 100,
        total_costs=100,
        net_pnl=pnl,
        exit_type="PROFIT_TARGET" if pnl > 0 else "STOP_LOSS",
        holding_days=14,
        metadata={"vix_at_entry": vix},
    )


def _make_result(pnls, vixes=None):
    """Create a BacktestResult from a list of P&Ls."""
    if vixes is None:
        vixes = [16] * len(pnls)
    trades = [_make_trade(p, i * 15, vixes[i]) for i, p in enumerate(pnls)]
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl <= 0]
    return BacktestResult(
        strategy_name="TEST",
        params={"test": True},
        slippage_model="realistic",
        start_date=datetime(2026, 1, 1),
        end_date=datetime(2026, 12, 31),
        trades=trades,
        total_trades=len(trades),
        winning_trades=len(winners),
        losing_trades=len(losers),
        win_rate=len(winners) / len(trades) if trades else 0,
        total_net_pnl=sum(pnls),
        capital_used=750000,
    )


analyser = BacktestStatAnalyser(seed=42)


# --- Bootstrap CI Tests ---

class TestBootstrapCI:
    def test_ci_contains_point_estimate(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40]
        ci = analyser.bootstrap_ci(pnls, sum, "total_pnl")
        assert ci.lower <= ci.point_estimate <= ci.upper

    def test_ci_wider_with_more_variance(self):
        low_var = [100, 110, 105, 95, 100, 108, 102, 97, 103, 101]
        high_var = [500, -400, 300, -200, 600, -500, 400, -300, 200, -100]
        ci_low = analyser.bootstrap_ci(low_var, sum, "total_pnl")
        ci_high = analyser.bootstrap_ci(high_var, sum, "total_pnl")
        assert (ci_high.upper - ci_high.lower) > (ci_low.upper - ci_low.lower)

    def test_ci_95_pct_level(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40]
        ci = analyser.bootstrap_ci(pnls, sum, "test", confidence=0.95)
        assert ci.confidence_level == 0.95

    def test_ci_for_win_rate(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40]
        ci = analyser.bootstrap_ci(
            pnls, lambda x: sum(1 for p in x if p > 0) / len(x), "win_rate"
        )
        assert 0 <= ci.lower
        assert ci.upper <= 1


# --- Monte Carlo Tests ---

class TestMonteCarlo:
    def test_profitable_strategy_has_high_prob_profit(self):
        # Strongly profitable trades
        pnls = [200, 150, 180, 100, -50, 220, 130, 170, 90, -30]
        mc = analyser.monte_carlo(pnls, n_simulations=5000, horizon=50)
        assert mc.prob_profit > 0.7

    def test_losing_strategy_has_low_prob_profit(self):
        pnls = [-200, -150, -180, 50, -100, -220, -130, -170, 30, -90]
        mc = analyser.monte_carlo(pnls, n_simulations=5000, horizon=50)
        assert mc.prob_profit < 0.3

    def test_percentiles_ordered(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40]
        mc = analyser.monte_carlo(pnls, n_simulations=5000, horizon=50)
        assert mc.pct_5 <= mc.pct_25 <= mc.median_pnl <= mc.pct_75 <= mc.pct_95

    def test_prob_ruin_between_0_and_1(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40]
        mc = analyser.monte_carlo(pnls, n_simulations=5000, horizon=50)
        assert 0 <= mc.prob_ruin <= 1


# --- Walk-Forward Tests ---

class TestWalkForward:
    def test_walk_forward_with_enough_data(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40,
                90, -60, 180, -80, 110, 70, -20, 140, 60, -35]
        wf = analyser.walk_forward(pnls, n_folds=4)
        assert wf.n_folds > 0
        assert len(wf.in_sample_sharpe) > 0
        assert len(wf.out_of_sample_sharpe) > 0

    def test_walk_forward_insufficient_data(self):
        pnls = [100, -50, 200]
        wf = analyser.walk_forward(pnls, n_folds=5)
        assert wf.is_consistent is False

    def test_degradation_is_computed(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40,
                90, -60, 180, -80, 110, 70, -20, 140, 60, -35]
        wf = analyser.walk_forward(pnls, n_folds=4)
        assert isinstance(wf.degradation_pct, float)


# --- Regime Analysis Tests ---

class TestRegimeAnalysis:
    def test_separates_by_vix(self):
        pnls = [100, -50, 200, -100, 150, 80]
        vixes = [12, 14, 18, 22, 16, 25]  # low, low, normal, high, normal, high
        result = _make_result(pnls, vixes)
        regimes = analyser.regime_breakdown(result.trades)
        regime_names = {r.regime_name for r in regimes}
        assert "low_vol" in regime_names
        assert "normal" in regime_names
        assert "high_vol" in regime_names

    def test_trade_counts_sum_to_total(self):
        pnls = [100, -50, 200, -100, 150, 80]
        vixes = [12, 14, 18, 22, 16, 25]
        result = _make_result(pnls, vixes)
        regimes = analyser.regime_breakdown(result.trades)
        total = sum(r.n_trades for r in regimes)
        assert total == len(pnls)


# --- Full Report Tests ---

class TestFullReport:
    def test_insufficient_data(self):
        result = _make_result([100, -50])
        report = analyser.full_report(result)
        assert report.verdict == "INSUFFICIENT_DATA"

    def test_full_report_with_enough_data(self):
        pnls = [100, -50, 200, -100, 150, 80, -30, 120, 50, -40,
                90, -60, 180, -80, 110]
        result = _make_result(pnls)
        report = analyser.full_report(result, mc_simulations=1000)
        assert report.verdict in ("STRONG", "MARGINAL", "WEAK")
        assert report.sharpe_ci is not None
        assert report.pnl_ci is not None
        assert report.monte_carlo is not None

    def test_strong_strategy_gets_good_verdict(self):
        # Very consistent winners
        pnls = [200] * 20 + [-50] * 5
        result = _make_result(pnls)
        report = analyser.full_report(result, mc_simulations=2000)
        assert report.verdict in ("STRONG", "MARGINAL")

    def test_weak_strategy_gets_bad_verdict(self):
        # Mostly losers
        pnls = [-200] * 15 + [50] * 5
        result = _make_result(pnls)
        report = analyser.full_report(result, mc_simulations=2000)
        assert report.verdict == "WEAK"
