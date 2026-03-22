"""
Comprehensive metrics engine for strategy evaluation.

Computes: annual return, Sharpe, Sortino, Calmar, drawdown,
win/loss stats, profit factor, EV per trade, capital efficiency,
margin utilisation, monthly income breakdown.

Use in backtester and dashboard.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Sequence
import numpy as np


@dataclass
class StrategyMetrics:
    """All metrics for one backtest run."""

    # ── Return metrics ────────────────────────────────────────────────────────
    annual_return_pct: float      = 0.0   # On total capital
    annual_return_active_pct: float = 0.0 # On deployed capital only
    total_pnl_rs: float           = 0.0
    parked_income_rs: float       = 0.0   # From liquid fund / arbitrage fund
    combined_income_rs: float     = 0.0   # Trading P&L + parked income
    monthly_income_rs: float      = 0.0

    # ── Risk metrics ──────────────────────────────────────────────────────────
    sharpe: float                 = 0.0
    sortino: float                = 0.0
    calmar: float                 = 0.0
    max_drawdown_pct: float       = 0.0
    max_drawdown_rs: float        = 0.0
    avg_drawdown_pct: float       = 0.0
    longest_drawdown_days: int    = 0
    volatility_annual_pct: float  = 0.0

    # ── Trade stats ───────────────────────────────────────────────────────────
    total_trades: int             = 0
    win_rate_pct: float           = 0.0
    avg_win_rs: float             = 0.0
    avg_loss_rs: float            = 0.0
    max_win_rs: float             = 0.0
    max_loss_rs: float            = 0.0
    profit_factor: float          = 0.0
    ev_per_trade_rs: float        = 0.0
    avg_holding_days: float       = 0.0

    # ── Adjustment stats ──────────────────────────────────────────────────────
    trades_adjusted: int          = 0
    adjustment_rate_pct: float    = 0.0
    avg_adj_cost_rs: float        = 0.0
    adj_pnl_improvement_rs: float = 0.0

    # ── Capital efficiency ────────────────────────────────────────────────────
    capital_efficiency_pct: float = 0.0
    avg_margin_utilisation_pct: float = 0.0

    def summary(self) -> str:
        lines = [
            "═══ Strategy Metrics ═══",
            f"  Annual return (total capital) : {self.annual_return_pct:+.1f}%",
            f"  Annual return (active capital): {self.annual_return_active_pct:+.1f}%",
            f"  Combined annual income        : Rs {self.combined_income_rs:,.0f}",
            f"  Monthly income avg            : Rs {self.monthly_income_rs:,.0f}",
            "",
            f"  Sharpe ratio   : {self.sharpe:.2f}",
            f"  Sortino ratio  : {self.sortino:.2f}",
            f"  Calmar ratio   : {self.calmar:.2f}",
            f"  Max drawdown   : {self.max_drawdown_pct:.1f}% (Rs {self.max_drawdown_rs:,.0f})",
            f"  Volatility     : {self.volatility_annual_pct:.1f}% annualised",
            "",
            f"  Trades         : {self.total_trades}",
            f"  Win rate       : {self.win_rate_pct:.1f}%",
            f"  Avg win        : Rs {self.avg_win_rs:,.0f}",
            f"  Avg loss       : Rs {self.avg_loss_rs:,.0f}",
            f"  Profit factor  : {self.profit_factor:.2f}",
            f"  EV / trade     : Rs {self.ev_per_trade_rs:,.0f}",
            "",
            f"  Adjustment rate: {self.adjustment_rate_pct:.0f}%",
            f"  Adj P&L uplift : Rs {self.adj_pnl_improvement_rs:,.0f}",
            f"  Capital effic. : {self.capital_efficiency_pct:.0f}%",
        ]
        return "\n".join(lines)


def compute_metrics(
    daily_pnl: Sequence[float],
    trade_pnls: Sequence[float],
    total_capital: float,
    active_capital: float,
    parked_yield: float = 0.065,
    parked_capital: float = 500_000,
    periods_per_year: int = 252,
    rf_rate: float = 0.065,
    holding_days: Sequence[float] | None = None,
    adjustment_data: dict | None = None,
) -> StrategyMetrics:
    """
    Compute all metrics from backtest results.

    Parameters:
      daily_pnl       : P&L for each calendar trading day (include 0 for no-trade days)
      trade_pnls      : P&L per completed trade (nonzero entries only)
      total_capital   : total portfolio capital (e.g. 750_000)
      active_capital  : margin deployed (e.g. 90_000 Phase 1 / 200_000 Phase 3)
      parked_yield    : blended yield on non-deployed capital
      parked_capital  : amount in liquid fund / arb fund
      holding_days    : holding period per trade (optional)
      adjustment_data : dict with adjustment stats (optional)
    """
    m = StrategyMetrics()
    pnl  = np.asarray(daily_pnl,  dtype=float)
    tpnl = np.asarray(trade_pnls, dtype=float)
    n    = len(pnl)

    if n == 0:
        return m

    # ── Returns ───────────────────────────────────────────────────────────────
    parked_income = parked_capital * parked_yield
    trading_pnl   = float(np.sum(pnl))
    combined      = trading_pnl + parked_income

    m.total_pnl_rs            = round(trading_pnl, 0)
    m.parked_income_rs        = round(parked_income, 0)
    m.combined_income_rs      = round(combined, 0)
    m.annual_return_pct       = round((combined / total_capital) * (periods_per_year / n) * 100, 2)
    m.annual_return_active_pct= round((trading_pnl / active_capital) * (periods_per_year / n) * 100, 2) if active_capital > 0 else 0
    m.monthly_income_rs       = round(combined / (n / periods_per_year) / 12, 0)

    # ── Risk ──────────────────────────────────────────────────────────────────
    daily_ret  = pnl / total_capital
    daily_rf   = rf_rate / periods_per_year
    excess_ret = daily_ret - daily_rf

    m.volatility_annual_pct = round(float(np.std(daily_ret)) * np.sqrt(periods_per_year) * 100, 2)

    if np.std(daily_ret) > 0:
        m.sharpe = round(float(np.mean(excess_ret) / np.std(daily_ret)) * np.sqrt(periods_per_year), 3)
    neg_ret = daily_ret[daily_ret < 0]
    if len(neg_ret) > 0 and np.std(neg_ret) > 0:
        m.sortino = round(float(np.mean(excess_ret) / np.std(neg_ret)) * np.sqrt(periods_per_year), 3)

    # Drawdown
    cum  = np.cumsum(pnl)
    peak = np.maximum.accumulate(cum)
    dd   = cum - peak
    m.max_drawdown_rs  = round(float(np.min(dd)), 0)
    m.max_drawdown_pct = round(float(np.min(dd)) / total_capital * 100, 2)
    m.avg_drawdown_pct = round(float(np.mean(dd[dd < 0])) / total_capital * 100, 2) if np.any(dd < 0) else 0.0

    # Longest drawdown
    in_dd = False
    start = 0
    longest = 0
    for i, d in enumerate(dd):
        if d < 0 and not in_dd:
            in_dd = True
            start = i
        elif d >= 0 and in_dd:
            in_dd = False
            longest = max(longest, i - start)
    m.longest_drawdown_days = longest

    if m.max_drawdown_pct != 0:
        m.calmar = round(m.annual_return_pct / abs(m.max_drawdown_pct), 3)

    # ── Trade stats ───────────────────────────────────────────────────────────
    if len(tpnl) > 0:
        wins   = tpnl[tpnl > 0]
        losses = tpnl[tpnl < 0]

        m.total_trades  = len(tpnl)
        m.win_rate_pct  = round(len(wins) / len(tpnl) * 100, 1) if len(tpnl) > 0 else 0
        m.avg_win_rs    = round(float(np.mean(wins)),   0) if len(wins)   > 0 else 0
        m.avg_loss_rs   = round(float(np.mean(losses)), 0) if len(losses) > 0 else 0
        m.max_win_rs    = round(float(np.max(wins)),    0) if len(wins)   > 0 else 0
        m.max_loss_rs   = round(float(np.min(losses)),  0) if len(losses) > 0 else 0
        m.profit_factor = round(float(np.sum(wins) / abs(np.sum(losses))), 3) if len(losses) > 0 else 0
        m.ev_per_trade_rs = round(
            m.win_rate_pct/100 * m.avg_win_rs +
            (1 - m.win_rate_pct/100) * m.avg_loss_rs, 0
        )
        if holding_days is not None:
            m.avg_holding_days = round(float(np.mean(holding_days)), 1)

    # ── Adjustment stats ──────────────────────────────────────────────────────
    if adjustment_data:
        m.trades_adjusted       = adjustment_data.get("trades_adjusted", 0)
        m.adjustment_rate_pct   = round(m.trades_adjusted / max(m.total_trades, 1) * 100, 1)
        m.avg_adj_cost_rs       = round(adjustment_data.get("avg_cost", 0), 0)
        m.adj_pnl_improvement_rs= round(adjustment_data.get("pnl_improvement", 0), 0)

    # ── Capital efficiency ────────────────────────────────────────────────────
    m.capital_efficiency_pct = round(
        (active_capital + parked_capital) / total_capital * 100, 1
    )

    return m
