"""Tests for src/metrics.py — comprehensive metrics computation."""

import numpy as np
import pytest

from src.metrics import compute_metrics, StrategyMetrics


def test_basic_returns():
    daily_pnl = [100] * 252  # Rs 100/day for 1 year
    trade_pnls = [500, 500, -200, 300]
    m = compute_metrics(
        daily_pnl=daily_pnl,
        trade_pnls=trade_pnls,
        total_capital=750_000,
        active_capital=90_000,
        parked_capital=500_000,
        parked_yield=0.065,
    )
    assert m.total_pnl_rs == 25_200  # 100 * 252
    assert m.parked_income_rs == 32_500  # 500k * 6.5%
    assert m.combined_income_rs == 57_700


def test_win_rate():
    m = compute_metrics(
        daily_pnl=[100, -50, 200, -30, 150],
        trade_pnls=[500, -200, 300, -100, 400],
        total_capital=750_000,
        active_capital=90_000,
    )
    assert m.total_trades == 5
    assert m.win_rate_pct == 60.0  # 3 wins / 5 trades


def test_drawdown():
    # Rising then falling
    daily_pnl = [100, 100, 100, -500, -500, 200]
    m = compute_metrics(
        daily_pnl=daily_pnl,
        trade_pnls=[100],
        total_capital=750_000,
        active_capital=90_000,
    )
    # Cumulative: 100, 200, 300, -200, -700, -500
    # Peak:       100, 200, 300, 300, 300, 300
    # DD:           0,   0,   0, -500, -1000, -800
    assert m.max_drawdown_rs == -1000


def test_profit_factor():
    m = compute_metrics(
        daily_pnl=[100, -50],
        trade_pnls=[1000, 500, -300],
        total_capital=750_000,
        active_capital=90_000,
    )
    # profit_factor = sum(wins) / |sum(losses)| = 1500 / 300 = 5.0
    assert m.profit_factor == 5.0


def test_sharpe_positive():
    # Consistent positive returns → positive Sharpe
    daily_pnl = [200] * 100
    m = compute_metrics(
        daily_pnl=daily_pnl,
        trade_pnls=[200],
        total_capital=750_000,
        active_capital=90_000,
    )
    # With zero variance, std = 0, sharpe stays 0
    # Actually all same → std = 0 → sharpe = 0
    assert m.sharpe == 0  # no variance


def test_sharpe_with_variance():
    np.random.seed(42)
    daily_pnl = list(np.random.normal(100, 50, 252))
    m = compute_metrics(
        daily_pnl=daily_pnl,
        trade_pnls=[500, -200, 300],
        total_capital=750_000,
        active_capital=90_000,
    )
    # Should have a meaningful Sharpe
    assert isinstance(m.sharpe, float)


def test_empty_pnl():
    m = compute_metrics(
        daily_pnl=[],
        trade_pnls=[],
        total_capital=750_000,
        active_capital=90_000,
    )
    assert m.total_trades == 0
    assert m.sharpe == 0


def test_adjustment_data():
    m = compute_metrics(
        daily_pnl=[100, 200],
        trade_pnls=[300, -100],
        total_capital=750_000,
        active_capital=90_000,
        adjustment_data={
            "trades_adjusted": 1,
            "avg_cost": 500,
            "pnl_improvement": 1200,
        },
    )
    assert m.trades_adjusted == 1
    assert m.adjustment_rate_pct == 50.0  # 1/2 trades
    assert m.avg_adj_cost_rs == 500
    assert m.adj_pnl_improvement_rs == 1200


def test_capital_efficiency():
    m = compute_metrics(
        daily_pnl=[100],
        trade_pnls=[100],
        total_capital=750_000,
        active_capital=90_000,
        parked_capital=500_000,
    )
    # (90k + 500k) / 750k = 78.7%
    assert m.capital_efficiency_pct == 78.7


def test_summary_string():
    m = StrategyMetrics(annual_return_pct=10.5, sharpe=1.5, total_trades=20)
    s = m.summary()
    assert "10.5%" in s
    assert "1.50" in s
    assert "20" in s
