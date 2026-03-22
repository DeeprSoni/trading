"""
Backtest Statistical Analysis — confidence intervals, Monte Carlo,
walk-forward validation, and regime-based analysis.

Answers the question: "Is this backtest result real or just noise?"
"""

import logging
import random
import statistics
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from src.models import BacktestResult, TradeResult

logger = logging.getLogger(__name__)


@dataclass
class ConfidenceInterval:
    """Bootstrap confidence interval for a metric."""
    metric: str
    point_estimate: float
    lower: float
    upper: float
    confidence_level: float
    n_samples: int


@dataclass
class MonteCarloResult:
    """Result of Monte Carlo forward simulation."""
    n_simulations: int
    horizon_trades: int
    median_pnl: float
    mean_pnl: float
    pct_5: float          # 5th percentile (worst case)
    pct_25: float
    pct_75: float
    pct_95: float         # 95th percentile (best case)
    prob_profit: float    # P(cumulative P&L > 0)
    prob_ruin: float      # P(drawdown > ruin_threshold)
    ruin_threshold: float


@dataclass
class WalkForwardResult:
    """Result of walk-forward (out-of-sample) validation."""
    n_folds: int
    in_sample_sharpe: list[float]
    out_of_sample_sharpe: list[float]
    is_sharpe_mean: float
    oos_sharpe_mean: float
    degradation_pct: float  # how much Sharpe drops OOS
    is_consistent: bool     # OOS Sharpe > 0 in majority of folds


@dataclass
class RegimeAnalysis:
    """Performance breakdown by market regime."""
    regime_name: str
    n_trades: int
    win_rate: float
    avg_pnl: float
    total_pnl: float
    sharpe: float


@dataclass
class FullStatisticalReport:
    """Complete statistical report for a backtest result."""
    strategy_name: str
    total_trades: int
    sharpe_ci: ConfidenceInterval | None
    pnl_ci: ConfidenceInterval | None
    win_rate_ci: ConfidenceInterval | None
    monte_carlo: MonteCarloResult | None
    walk_forward: WalkForwardResult | None
    regime_analysis: list[RegimeAnalysis]
    verdict: str  # "STRONG" / "MARGINAL" / "WEAK" / "INSUFFICIENT_DATA"


class BacktestStatAnalyser:
    """
    Statistical analysis suite for backtest results.

    Usage:
        analyser = BacktestStatAnalyser()
        report = analyser.full_report(backtest_result)
    """

    def __init__(self, seed: int = 42):
        self.rng = np.random.default_rng(seed)

    def full_report(
        self,
        result: BacktestResult,
        ruin_threshold: float = 0.15,
        mc_simulations: int = 10000,
        mc_horizon: int = 100,
        wf_folds: int = 5,
    ) -> FullStatisticalReport:
        """Generate a complete statistical report for a backtest result."""
        trades = result.trades
        n = len(trades)

        if n < 5:
            return FullStatisticalReport(
                strategy_name=result.strategy_name,
                total_trades=n,
                sharpe_ci=None,
                pnl_ci=None,
                win_rate_ci=None,
                monte_carlo=None,
                walk_forward=None,
                regime_analysis=[],
                verdict="INSUFFICIENT_DATA",
            )

        pnls = [t.net_pnl for t in trades]

        sharpe_ci = self.bootstrap_ci(pnls, self._sharpe_from_pnls, "sharpe_ratio")
        pnl_ci = self.bootstrap_ci(pnls, lambda x: sum(x), "total_pnl")
        win_rate_ci = self.bootstrap_ci(
            pnls, lambda x: sum(1 for p in x if p > 0) / len(x), "win_rate"
        )

        mc = self.monte_carlo(pnls, mc_simulations, mc_horizon, ruin_threshold, result.capital_used)
        wf = self.walk_forward(pnls, wf_folds) if n >= 10 else None
        regimes = self.regime_breakdown(trades)

        verdict = self._determine_verdict(sharpe_ci, mc, wf)

        return FullStatisticalReport(
            strategy_name=result.strategy_name,
            total_trades=n,
            sharpe_ci=sharpe_ci,
            pnl_ci=pnl_ci,
            win_rate_ci=win_rate_ci,
            monte_carlo=mc,
            walk_forward=wf,
            regime_analysis=regimes,
            verdict=verdict,
        )

    def bootstrap_ci(
        self,
        data: list[float],
        statistic_fn,
        metric_name: str,
        n_samples: int = 5000,
        confidence: float = 0.95,
    ) -> ConfidenceInterval:
        """
        Bootstrap confidence interval for any statistic.

        Resamples with replacement and computes percentile interval.
        """
        point_estimate = statistic_fn(data)
        n = len(data)
        boot_stats = []

        data_arr = np.array(data)
        for _ in range(n_samples):
            sample = self.rng.choice(data_arr, size=n, replace=True)
            boot_stats.append(statistic_fn(sample.tolist()))

        alpha = 1 - confidence
        lower = float(np.percentile(boot_stats, alpha / 2 * 100))
        upper = float(np.percentile(boot_stats, (1 - alpha / 2) * 100))

        return ConfidenceInterval(
            metric=metric_name,
            point_estimate=round(point_estimate, 4),
            lower=round(lower, 4),
            upper=round(upper, 4),
            confidence_level=confidence,
            n_samples=n_samples,
        )

    def monte_carlo(
        self,
        trade_pnls: list[float],
        n_simulations: int = 10000,
        horizon: int = 100,
        ruin_threshold: float = 0.15,
        capital: float = 750000,
    ) -> MonteCarloResult:
        """
        Monte Carlo forward simulation.

        Randomly samples from historical trade P&Ls to simulate
        future equity paths. Computes probability of profit and ruin.
        """
        pnl_arr = np.array(trade_pnls)
        final_pnls = []
        ruin_count = 0

        for _ in range(n_simulations):
            # Sample horizon trades with replacement
            path = self.rng.choice(pnl_arr, size=horizon, replace=True)
            cumulative = np.cumsum(path)
            final_pnls.append(float(cumulative[-1]))

            # Check if drawdown ever exceeds ruin threshold
            running_max = np.maximum.accumulate(cumulative + capital)
            drawdowns = (running_max - (cumulative + capital)) / running_max
            if np.any(drawdowns > ruin_threshold):
                ruin_count += 1

        final_arr = np.array(final_pnls)

        return MonteCarloResult(
            n_simulations=n_simulations,
            horizon_trades=horizon,
            median_pnl=round(float(np.median(final_arr)), 2),
            mean_pnl=round(float(np.mean(final_arr)), 2),
            pct_5=round(float(np.percentile(final_arr, 5)), 2),
            pct_25=round(float(np.percentile(final_arr, 25)), 2),
            pct_75=round(float(np.percentile(final_arr, 75)), 2),
            pct_95=round(float(np.percentile(final_arr, 95)), 2),
            prob_profit=round(float(np.mean(final_arr > 0)), 4),
            prob_ruin=round(ruin_count / n_simulations, 4),
            ruin_threshold=ruin_threshold,
        )

    def walk_forward(
        self,
        trade_pnls: list[float],
        n_folds: int = 5,
    ) -> WalkForwardResult:
        """
        Walk-forward (out-of-sample) validation.

        Splits trades into n_folds sequential segments. For each fold,
        trains on all prior segments and tests on the current segment.
        Checks if in-sample performance holds out-of-sample.
        """
        n = len(trade_pnls)
        fold_size = n // n_folds
        if fold_size < 3:
            # Not enough data for meaningful walk-forward
            return WalkForwardResult(
                n_folds=n_folds,
                in_sample_sharpe=[],
                out_of_sample_sharpe=[],
                is_sharpe_mean=0,
                oos_sharpe_mean=0,
                degradation_pct=100,
                is_consistent=False,
            )

        is_sharpes = []
        oos_sharpes = []

        for i in range(1, n_folds):
            # In-sample: all folds before i
            is_end = i * fold_size
            in_sample = trade_pnls[:is_end]

            # Out-of-sample: fold i
            oos_start = is_end
            oos_end = min(oos_start + fold_size, n)
            out_of_sample = trade_pnls[oos_start:oos_end]

            if len(in_sample) >= 3 and len(out_of_sample) >= 2:
                is_sharpe = self._sharpe_from_pnls(in_sample)
                oos_sharpe = self._sharpe_from_pnls(out_of_sample)
                is_sharpes.append(round(is_sharpe, 4))
                oos_sharpes.append(round(oos_sharpe, 4))

        if not is_sharpes:
            return WalkForwardResult(0, [], [], 0, 0, 100, False)

        is_mean = statistics.mean(is_sharpes)
        oos_mean = statistics.mean(oos_sharpes)
        degradation = ((is_mean - oos_mean) / abs(is_mean) * 100) if is_mean != 0 else 100

        # Consistent if OOS Sharpe > 0 in at least 60% of folds
        positive_oos = sum(1 for s in oos_sharpes if s > 0)
        is_consistent = positive_oos / len(oos_sharpes) >= 0.6

        return WalkForwardResult(
            n_folds=len(is_sharpes) + 1,
            in_sample_sharpe=is_sharpes,
            out_of_sample_sharpe=oos_sharpes,
            is_sharpe_mean=round(is_mean, 4),
            oos_sharpe_mean=round(oos_mean, 4),
            degradation_pct=round(degradation, 1),
            is_consistent=is_consistent,
        )

    def regime_breakdown(self, trades: list[TradeResult]) -> list[RegimeAnalysis]:
        """
        Break down performance by market regime based on trade metadata.

        Regime is determined by VIX at entry:
          Low vol: VIX < 15
          Normal: 15 <= VIX <= 20
          High vol: VIX > 20
        """
        regimes = {"low_vol": [], "normal": [], "high_vol": []}

        for t in trades:
            vix = t.metadata.get("vix_at_entry", 16)
            if vix < 15:
                regimes["low_vol"].append(t)
            elif vix <= 20:
                regimes["normal"].append(t)
            else:
                regimes["high_vol"].append(t)

        results = []
        for regime_name, regime_trades in regimes.items():
            if not regime_trades:
                continue
            pnls = [t.net_pnl for t in regime_trades]
            winners = sum(1 for p in pnls if p > 0)
            results.append(RegimeAnalysis(
                regime_name=regime_name,
                n_trades=len(pnls),
                win_rate=round(winners / len(pnls), 4),
                avg_pnl=round(statistics.mean(pnls), 2),
                total_pnl=round(sum(pnls), 2),
                sharpe=round(self._sharpe_from_pnls(pnls), 4) if len(pnls) >= 2 else 0,
            ))

        return results

    @staticmethod
    def _sharpe_from_pnls(pnls: list | np.ndarray) -> float:
        """Calculate annualised Sharpe from a list of trade P&Ls."""
        if hasattr(pnls, "tolist"):
            pnls = pnls.tolist()
        if len(pnls) < 2:
            return 0.0
        mean = statistics.mean(pnls)
        std = statistics.stdev(pnls)
        if std == 0:
            return 0.0
        # Approximate annualisation: assume ~1 trade per week
        trades_per_year = 52 / max(1, len(pnls) / len(pnls))  # simplified
        return (mean / std) * (len(pnls) ** 0.5)  # √N scaling for trade-level

    @staticmethod
    def _determine_verdict(
        sharpe_ci: ConfidenceInterval | None,
        mc: MonteCarloResult | None,
        wf: WalkForwardResult | None,
    ) -> str:
        """
        Determine overall verdict based on statistical evidence.

        STRONG: Sharpe CI lower bound > 0.5, prob_profit > 70%, walk-forward consistent
        MARGINAL: Sharpe CI lower bound > 0, prob_profit > 55%
        WEAK: everything else
        """
        if sharpe_ci is None:
            return "INSUFFICIENT_DATA"

        score = 0

        # Sharpe CI check
        if sharpe_ci.lower > 0.5:
            score += 3
        elif sharpe_ci.lower > 0:
            score += 1

        # Monte Carlo check
        if mc is not None:
            if mc.prob_profit > 0.70:
                score += 2
            elif mc.prob_profit > 0.55:
                score += 1
            if mc.prob_ruin < 0.05:
                score += 1

        # Walk-forward check
        if wf is not None and wf.is_consistent:
            score += 2

        if score >= 6:
            return "STRONG"
        elif score >= 3:
            return "MARGINAL"
        else:
            return "WEAK"


def select_robust_params(sweep_results: list[dict]) -> dict:
    """
    Walk-forward parameter selection: picks the most robust parameter set
    from a list of sweep results.

    Each entry in sweep_results must be a dict with at least:
      - "params": dict of parameters
      - "sharpe_ratio": float — overall Sharpe ratio
      - "max_drawdown_pct": float — maximum drawdown percentage
      - "walk_forward_folds": list[dict] with "is_sharpe" and "oos_sharpe" keys
        (one dict per fold)

    Selection criteria (in order):
      1. Positive OOS Sharpe in >= 4 of 5 walk-forward folds
      2. OOS Sharpe mean >= 70% of IS Sharpe mean
      3. Among qualifying, pick the one with the lowest max_drawdown_pct

    Falls back to the entry with the best overall Sharpe ratio if no
    entries qualify.

    Returns the "params" dict of the selected entry.
    """
    if not sweep_results:
        return {}

    qualifying = []

    for entry in sweep_results:
        folds = entry.get("walk_forward_folds", [])
        if not folds:
            continue

        oos_sharpes = [f.get("oos_sharpe", 0) for f in folds]
        is_sharpes = [f.get("is_sharpe", 0) for f in folds]

        # Criterion 1: positive OOS Sharpe in >= 4 of 5 folds
        positive_oos = sum(1 for s in oos_sharpes if s > 0)
        n_folds = len(folds)
        min_positive = max(1, int(n_folds * 0.8))  # 4 out of 5
        if positive_oos < min_positive:
            continue

        # Criterion 2: OOS Sharpe mean >= 70% of IS Sharpe mean
        is_mean = sum(is_sharpes) / len(is_sharpes) if is_sharpes else 0
        oos_mean = sum(oos_sharpes) / len(oos_sharpes) if oos_sharpes else 0
        if is_mean > 0 and oos_mean < 0.70 * is_mean:
            continue

        qualifying.append(entry)

    if qualifying:
        # Criterion 3: lowest max drawdown among qualifying
        best = min(qualifying, key=lambda e: e.get("max_drawdown_pct", float("inf")))
        return best.get("params", {})

    # Fallback: best overall Sharpe
    best_sharpe = max(sweep_results, key=lambda e: e.get("sharpe_ratio", float("-inf")))
    return best_sharpe.get("params", {})
