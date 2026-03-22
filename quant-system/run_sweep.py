"""
Run parameter sweeps and save results for the dashboard.

Usage: python run_sweep.py
"""

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Suppress noisy loggers during sweep
logging.basicConfig(level=logging.WARNING)
for name in ("src.iv_calculator", "src.backtester", "src.strategy_ic_backtest",
             "src.strategy_cal_backtest", "src.cost_engine", "src.param_sweep"):
    logging.getLogger(name).setLevel(logging.ERROR)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.backtester import Backtester
from src.backtest_stats import BacktestStatAnalyser
from src.cost_engine import CostEngine, SlippageModel
from src.iv_calculator import IVCalculator
from src.models import BacktestResult, MarketState
from src.param_sweep import ParamSweepEngine, SweepConfig
from src.strategy_cal_backtest import CalBacktestAdapter
from src.strategy_ic_backtest import ICBacktestAdapter
from src.synthetic_data_generator import SyntheticDataGenerator


def generate_market_states(hist_csv: str, max_days: int = 500) -> list[MarketState]:
    """Generate daily MarketState objects from spot history using synthetic chain generation inline."""
    np.random.seed(42)  # Reproducible synthetic data across runs
    print(f"Loading spot history from {hist_csv}...")
    df = pd.read_csv(hist_csv, parse_dates=["date"])
    df = df.sort_values("date").reset_index(drop=True)
    df = df.tail(max_days).reset_index(drop=True)
    print(f"  {len(df)} rows loaded ({df['date'].iloc[0].date()} to {df['date'].iloc[-1].date()})")

    iv_calc = IVCalculator()
    gen = SyntheticDataGenerator(iv_calculator=iv_calc)

    # Estimate VIX from returns
    # Real India VIX = realized vol * 1.50-1.60 (variance risk premium)
    # Historical India VIX: mean ~16-18, range 10-40, rarely below 12
    df["returns"] = df["close"].pct_change()
    df["realized_vol"] = df["returns"].rolling(21).std() * np.sqrt(252)
    df["vix"] = df["realized_vol"] * 100 * 1.55
    df["vix"] = df["vix"].clip(lower=14.0).bfill().fillna(17.0)

    # Generate monthly expiry dates
    expiries = gen._generate_monthly_expiries(df["date"].min(), df["date"].max())

    states = []
    skipped = 0

    for idx, row in df.iterrows():
        date = row["date"].to_pydatetime()
        price = row["close"]
        vix = row["vix"]

        if date.weekday() >= 5:
            skipped += 1
            continue

        atm_iv = max(vix / 100, 0.12)  # Floor at 12% — India VIX baseline

        # Active expiries for this day (2 for speed)
        active = [e for e in expiries if (e - date).days > 0][:2]
        if not active:
            skipped += 1
            continue

        # Build option chain inline
        records = []
        strike_interval = 100
        num_strikes = 10
        atm_strike = round(price / strike_interval) * strike_interval

        for expiry in active:
            dte = (expiry - date).days
            if dte <= 0:
                continue
            T = dte / 365.0

            for offset in range(-num_strikes, num_strikes + 1):
                strike = atm_strike + offset * strike_interval
                if strike <= 0:
                    continue
                moneyness = strike / price

                for opt_type in ["CE", "PE"]:
                    iv = gen._apply_vol_skew(atm_iv, moneyness, dte)
                    try:
                        bs_price = iv_calc._bs_price(price, strike, T, 0.065, iv, opt_type)
                    except Exception:
                        continue

                    # OTM demand premium: hedgers pay above BS for OTM options
                    # Real markets show 10-25% premium over theoretical for OTM wings
                    otm_distance = abs(moneyness - 1.0)
                    if otm_distance > 0.02:  # OTM by > 2%
                        demand_premium = bs_price * 0.15 * min(otm_distance / 0.10, 1.0)
                        bs_price += demand_premium

                    ltp = max(0.5, bs_price + np.random.uniform(-1.0, 1.0))
                    spread = max(0.50, ltp * 0.015)
                    bid = max(0.05, ltp - spread / 2)
                    ask = ltp + spread / 2

                    try:
                        delta = iv_calc._bs_delta(price, strike, T, 0.065, iv, opt_type)
                    except Exception:
                        delta = 0.0

                    records.append({
                        "strike": strike,
                        "option_type": opt_type,
                        "expiry": expiry.isoformat(),
                        "dte": dte,
                        "ltp": round(ltp, 2),
                        "bid": round(bid, 2),
                        "ask": round(ask, 2),
                        "iv": round(iv, 4),
                        "delta": round(delta, 4),
                        "oi": max(100, int(50000 * np.exp(-0.5 * ((strike - price) / (price * 0.05)) ** 2))),
                    })

        if not records:
            skipped += 1
            continue

        # Expiry dates for the adapter (front ~35 DTE, back ~65 DTE)
        expiry_strs = [e.isoformat() for e in active]

        # IV rank estimation
        iv_rank = min(max(vix * 2.5, 15), 85)

        states.append(MarketState(
            date=date,
            underlying_price=price,
            india_vix=min(max(vix, 10), 40),
            iv_rank=iv_rank,
            option_chain={"records": records},
            expiry_dates=expiry_strs,
        ))

        if (len(states)) % 100 == 0:
            print(f"  Generated {len(states)} states...")

    print(f"  Total: {len(states)} market states ({skipped} skipped)")
    return states


def result_to_dict(r: BacktestResult) -> dict:
    """Serialize BacktestResult to JSON-safe dict."""
    return {
        "strategy_name": r.strategy_name,
        "params": r.params,
        "slippage_model": r.slippage_model,
        "start_date": r.start_date.isoformat() if r.start_date else None,
        "end_date": r.end_date.isoformat() if r.end_date else None,
        "total_trades": r.total_trades,
        "winning_trades": r.winning_trades,
        "losing_trades": r.losing_trades,
        "win_rate": r.win_rate,
        "total_gross_pnl": r.total_gross_pnl,
        "total_costs": r.total_costs,
        "total_net_pnl": r.total_net_pnl,
        "max_drawdown": r.max_drawdown,
        "max_drawdown_pct": r.max_drawdown_pct,
        "sharpe_ratio": r.sharpe_ratio,
        "sortino_ratio": r.sortino_ratio,
        "profit_factor": r.profit_factor,
        "avg_trade_pnl": r.avg_trade_pnl,
        "avg_winner": r.avg_winner,
        "avg_loser": r.avg_loser,
        "avg_holding_days": r.avg_holding_days,
        "annual_return_pct": r.annual_return_pct,
        "calmar_ratio": r.calmar_ratio,
        "total_margin_cost": r.total_margin_cost,
        "capital_used": r.capital_used,
        "trades": [
            {
                "position_id": t.position_id,
                "entry_date": t.entry_date.isoformat(),
                "exit_date": t.exit_date.isoformat(),
                "exit_type": t.exit_type,
                "holding_days": t.holding_days,
                "gross_pnl": t.gross_pnl,
                "total_costs": t.total_costs,
                "net_pnl": t.net_pnl,
                "net_premium_per_unit": t.net_premium_per_unit,
                "close_cost_per_unit": t.close_cost_per_unit,
                "metadata": {k: v for k, v in t.metadata.items()
                             if isinstance(v, (int, float, str, bool))},
                "adjustment_count": t.adjustment_count,
                "adjustment_costs": t.adjustment_costs,
                "adjustment_pnl": t.adjustment_pnl,
            }
            for t in r.trades
        ],
    }


def run_ic_sweep(states, slippage_models):
    """Run Iron Condor parameter sweep — centered on PRD parameters."""
    grid = {
        "short_delta": [0.16, 0.20, 0.25],         # Higher delta = higher premium; PRD baseline: 0.16
        "wing_width": [400, 500, 600],               # PRD baseline: 500
        "profit_target_pct": [0.40, 0.50, 0.65],    # PRD baseline: 0.50
        "stop_loss_multiplier": [1.5, 2.0, 2.5],    # PRD baseline: 2.0
        "time_stop_dte": [18, 21, 25],               # PRD baseline: 21
    }
    total = 1
    for v in grid.values():
        total *= len(v)
    print(f"\nIC Sweep: {total} combos x {len(slippage_models)} slippage = {total * len(slippage_models)} runs")

    config = SweepConfig(
        strategy_class=ICBacktestAdapter,
        param_grid=grid,
        slippage_models=slippage_models,
    )
    sweep = ParamSweepEngine(max_workers=1)
    return sweep.run_sequential(config, states, rank_by="sharpe_ratio", min_trades=2)


def run_cal_sweep(states, slippage_models):
    """Run Calendar Spread parameter sweep — centered on PRD parameters."""
    grid = {
        "move_pct_to_adjust": [0.015, 0.02, 0.025],  # PRD baseline: 0.02
        "move_pct_to_close": [0.03, 0.04, 0.05],      # PRD baseline: 0.04
        "profit_target_pct": [0.40, 0.50, 0.60],       # PRD baseline: 0.50
        "back_month_close_dte": [22, 25, 28],          # PRD baseline: 25
        "max_vix": [25, 28, 32],                       # PRD baseline: 28
    }
    total = 1
    for v in grid.values():
        total *= len(v)
    print(f"\nCAL Sweep: {total} combos x {len(slippage_models)} slippage = {total * len(slippage_models)} runs")

    config = SweepConfig(
        strategy_class=CalBacktestAdapter,
        param_grid=grid,
        slippage_models=slippage_models,
    )
    sweep = ParamSweepEngine(max_workers=1)
    return sweep.run_sequential(config, states, rank_by="sharpe_ratio", min_trades=2)


def run_stats_on_top(results, n_top=5):
    """Run full statistical analysis on top N results."""
    analyser = BacktestStatAnalyser()
    reports = []
    for r in results[:n_top]:
        report = analyser.full_report(r, mc_simulations=5000)
        reports.append({
            "strategy_name": r.strategy_name,
            "verdict": report.verdict,
            "sharpe_ci": {
                "lower": report.sharpe_ci.lower,
                "upper": report.sharpe_ci.upper,
                "point": report.sharpe_ci.point_estimate,
            } if report.sharpe_ci else None,
            "monte_carlo": {
                "prob_profit": report.monte_carlo.prob_profit,
                "prob_ruin": report.monte_carlo.prob_ruin,
                "median_pnl": report.monte_carlo.median_pnl,
                "pct_5": report.monte_carlo.pct_5,
                "pct_25": report.monte_carlo.pct_25 if hasattr(report.monte_carlo, 'pct_25') else 0,
                "pct_75": report.monte_carlo.pct_75 if hasattr(report.monte_carlo, 'pct_75') else 0,
                "pct_95": report.monte_carlo.pct_95,
            } if report.monte_carlo else None,
            "walk_forward": {
                "is_consistent": report.walk_forward.is_consistent,
                "oos_sharpe_mean": report.walk_forward.oos_sharpe_mean,
                "degradation_pct": report.walk_forward.degradation_pct,
            } if report.walk_forward else None,
            "regime_analysis": [
                {"regime": ra.regime_name, "n_trades": ra.n_trades,
                 "win_rate": ra.win_rate, "avg_pnl": ra.avg_pnl}
                for ra in report.regime_analysis
            ],
        })
    return reports


def generate_combined_results(ic_results, cal_results, capital=750_000):
    """Combine top IC and CAL configs with different capital allocation splits.

    Runs IC and CAL independently on the same capital, then merges their trade
    streams.  Capital allocation scales lot counts (and therefore P&L)
    proportionally.
    """
    import statistics

    ic_allocations = [0.30, 0.40, 0.50, 0.60, 0.70]
    combined = []

    for slippage in ["optimistic", "realistic", "conservative"]:
        ic_pool = [r for r in ic_results if r["slippage_model"] == slippage]
        cal_pool = [r for r in cal_results if r["slippage_model"] == slippage]

        # Rank IC by Sharpe (all have similar trade counts)
        ic_pool.sort(key=lambda r: r.get("sharpe_ratio", -999), reverse=True)

        # Rank CAL by net_pnl, preferring configs with more trades (>=5)
        # This avoids picking 3-trade configs with inflated Sharpe
        cal_high_trade = [r for r in cal_pool if r.get("total_trades", 0) >= 5]
        if not cal_high_trade:
            cal_high_trade = cal_pool  # fallback
        cal_high_trade.sort(key=lambda r: r.get("total_net_pnl", -999), reverse=True)

        top_ic = ic_pool[:5]
        top_cal = cal_high_trade[:5]

        for ic in top_ic:
            for cal in top_cal:
                for ic_pct in ic_allocations:
                    cal_pct = 1.0 - ic_pct

                    # Scale trade P&Ls by capital allocation
                    all_trades = []
                    for t in ic.get("trades", []):
                        all_trades.append({
                            "exit_date": t["exit_date"],
                            "entry_date": t["entry_date"],
                            "net_pnl": t["net_pnl"] * ic_pct,
                            "gross_pnl": t["gross_pnl"] * ic_pct,
                            "total_costs": t["total_costs"] * ic_pct,
                            "exit_type": t["exit_type"],
                            "holding_days": t["holding_days"],
                            "strategy": "IC",
                            "net_premium_per_unit": t.get("net_premium_per_unit", 0),
                            "close_cost_per_unit": t.get("close_cost_per_unit", 0),
                            "position_id": t.get("position_id", ""),
                            "adjustment_count": t.get("adjustment_count", 0),
                            "adjustment_costs": t.get("adjustment_costs", 0),
                            "adjustment_pnl": t.get("adjustment_pnl", 0),
                        })
                    for t in cal.get("trades", []):
                        all_trades.append({
                            "exit_date": t["exit_date"],
                            "entry_date": t["entry_date"],
                            "net_pnl": t["net_pnl"] * cal_pct,
                            "gross_pnl": t["gross_pnl"] * cal_pct,
                            "total_costs": t["total_costs"] * cal_pct,
                            "exit_type": t["exit_type"],
                            "holding_days": t["holding_days"],
                            "strategy": "CAL",
                            "net_premium_per_unit": t.get("net_premium_per_unit", 0),
                            "close_cost_per_unit": t.get("close_cost_per_unit", 0),
                            "position_id": t.get("position_id", ""),
                            "adjustment_count": t.get("adjustment_count", 0),
                            "adjustment_costs": t.get("adjustment_costs", 0),
                            "adjustment_pnl": t.get("adjustment_pnl", 0),
                        })

                    all_trades.sort(key=lambda t: t["exit_date"])
                    total_trades = len(all_trades)
                    if total_trades < 3:
                        continue

                    winners = [t for t in all_trades if t["net_pnl"] > 0]
                    total_gross = sum(t["gross_pnl"] for t in all_trades)
                    total_costs = sum(t["total_costs"] for t in all_trades)
                    total_net = sum(t["net_pnl"] for t in all_trades)

                    gross_wins = sum(t["net_pnl"] for t in winners)
                    gross_losses = abs(sum(t["net_pnl"] for t in all_trades if t["net_pnl"] <= 0))

                    # Equity curve and drawdown
                    cum_pnl = 0.0
                    peak = float(capital)
                    max_dd = 0.0
                    max_dd_pct = 0.0
                    trade_pnls = []

                    for t in all_trades:
                        cum_pnl += t["net_pnl"]
                        equity = capital + cum_pnl
                        peak = max(peak, equity)
                        dd = peak - equity
                        dd_pct = dd / peak if peak > 0 else 0
                        max_dd = max(max_dd, dd)
                        max_dd_pct = max(max_dd_pct, dd_pct)
                        trade_pnls.append(t["net_pnl"])

                    # Sharpe from trade-level P&L
                    # Scale to annualised: ~400 trading days, each trade ~ 10 days
                    sharpe = 0.0
                    if len(trade_pnls) >= 2:
                        mean_pnl = statistics.mean(trade_pnls)
                        std_pnl = statistics.stdev(trade_pnls)
                        if std_pnl > 0:
                            periods_per_year = 252.0 / max(
                                1, 400 / total_trades
                            )
                            sharpe = (mean_pnl / std_pnl) * (periods_per_year ** 0.5)

                    sortino = 0.0
                    if len(trade_pnls) >= 2:
                        downside = [p for p in trade_pnls if p < 0]
                        if downside:
                            down_std = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
                            if down_std > 0:
                                sortino = (statistics.mean(trade_pnls) / down_std) * (periods_per_year ** 0.5)

                    years = 400 / 252
                    roi = total_net / capital * 100
                    annual_ret = roi / years
                    calmar = annual_ret / (max_dd_pct * 100) if max_dd_pct > 0 else 0

                    ic_trades_count = sum(1 for t in all_trades if t["strategy"] == "IC")
                    cal_trades_count = sum(1 for t in all_trades if t["strategy"] == "CAL")

                    combo_name = "COMBINED_%s_IC%d_CAL%d" % (
                        ic["strategy_name"] + "+" + cal["strategy_name"],
                        int(ic_pct * 100), int(cal_pct * 100),
                    )

                    combined.append({
                        "strategy_name": combo_name,
                        "ic_config": ic["strategy_name"],
                        "cal_config": cal["strategy_name"],
                        "ic_params": ic.get("params", {}),
                        "cal_params": cal.get("params", {}),
                        "ic_allocation_pct": int(ic_pct * 100),
                        "cal_allocation_pct": int(cal_pct * 100),
                        "slippage_model": slippage,
                        "total_trades": total_trades,
                        "ic_trades": ic_trades_count,
                        "cal_trades": cal_trades_count,
                        "winning_trades": len(winners),
                        "losing_trades": total_trades - len(winners),
                        "win_rate": len(winners) / total_trades,
                        "total_gross_pnl": round(total_gross, 2),
                        "total_costs": round(total_costs, 2),
                        "total_net_pnl": round(total_net, 2),
                        "max_drawdown": round(max_dd, 2),
                        "max_drawdown_pct": round(max_dd_pct, 4),
                        "sharpe_ratio": round(sharpe, 2),
                        "sortino_ratio": round(sortino, 2),
                        "profit_factor": round(gross_wins / gross_losses, 2) if gross_losses > 0 else 999,
                        "avg_trade_pnl": round(total_net / total_trades, 2),
                        "avg_winner": round(gross_wins / len(winners), 2) if winners else 0,
                        "avg_loser": round(-gross_losses / (total_trades - len(winners)), 2) if (total_trades - len(winners)) > 0 else 0,
                        "annual_return_pct": round(annual_ret, 2),
                        "calmar_ratio": round(calmar, 2),
                        "roi_pct": round(roi, 2),
                        "capital_used": capital,
                        "trades": all_trades,
                    })

    combined.sort(key=lambda r: r.get("sharpe_ratio", -999), reverse=True)
    return combined


def main():
    start = time.time()
    output_dir = Path("data/sweep_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    hist_csv = "tests/fixtures/sample_historical_prices.csv"
    states = generate_market_states(hist_csv, max_days=400)

    if not states:
        print("ERROR: No market states generated.")
        return

    slippage_models = [SlippageModel.OPTIMISTIC, SlippageModel.REALISTIC, SlippageModel.CONSERVATIVE]

    # --- IC Sweep ---
    ic_sweep = run_ic_sweep(states, slippage_models)
    print(f"IC: {ic_sweep.completed} completed, {len(ic_sweep.results)} passed filter, {ic_sweep.elapsed_seconds:.1f}s")

    ic_data = {
        "sweep_type": "IC",
        "total_combinations": ic_sweep.total_combinations,
        "completed": ic_sweep.completed,
        "elapsed_seconds": ic_sweep.elapsed_seconds,
        "results": [result_to_dict(r) for r in ic_sweep.results],
    }

    if ic_sweep.results:
        ic_data["top_stats"] = run_stats_on_top(ic_sweep.results, 5)
        print(f"\nTop 5 IC results:")
        for i, r in enumerate(ic_sweep.results[:5]):
            print(f"  {i+1}. {r.strategy_name}: Sharpe={r.sharpe_ratio:.2f}, "
                  f"Net={r.total_net_pnl:,.0f}, WR={r.win_rate:.0%}, DD={r.max_drawdown_pct:.1%}, "
                  f"Trades={r.total_trades}")

    with open(output_dir / "ic_sweep.json", "w") as f:
        json.dump(ic_data, f, indent=2, default=str)
    print(f"Saved IC results to {output_dir / 'ic_sweep.json'}")

    # --- CAL Sweep ---
    cal_sweep = run_cal_sweep(states, slippage_models)
    print(f"CAL: {cal_sweep.completed} completed, {len(cal_sweep.results)} passed filter, {cal_sweep.elapsed_seconds:.1f}s")

    cal_data = {
        "sweep_type": "CAL",
        "total_combinations": cal_sweep.total_combinations,
        "completed": cal_sweep.completed,
        "elapsed_seconds": cal_sweep.elapsed_seconds,
        "results": [result_to_dict(r) for r in cal_sweep.results],
    }

    if cal_sweep.results:
        cal_data["top_stats"] = run_stats_on_top(cal_sweep.results, 5)
        print(f"\nTop 5 CAL results:")
        for i, r in enumerate(cal_sweep.results[:5]):
            print(f"  {i+1}. {r.strategy_name}: Sharpe={r.sharpe_ratio:.2f}, "
                  f"Net={r.total_net_pnl:,.0f}, WR={r.win_rate:.0%}, DD={r.max_drawdown_pct:.1%}, "
                  f"Trades={r.total_trades}")

    with open(output_dir / "cal_sweep.json", "w") as f:
        json.dump(cal_data, f, indent=2, default=str)
    print(f"Saved CAL results to {output_dir / 'cal_sweep.json'}")

    # --- Combined IC+CAL ---
    print("\nGenerating combined IC+CAL results...")
    combined_results = generate_combined_results(
        ic_data["results"], cal_data["results"], capital=750_000,
    )
    combined_data = {
        "sweep_type": "COMBINED",
        "total_combinations": len(combined_results),
        "results": combined_results,
    }

    # Print top results
    profitable = [r for r in combined_results if r["total_net_pnl"] > 0]
    print(f"Combined: {len(combined_results)} combos, {len(profitable)} profitable")
    if combined_results:
        print("\nTop 5 Combined results:")
        for i, r in enumerate(combined_results[:5]):
            print(f"  {i+1}. IC{r['ic_allocation_pct']}/CAL{r['cal_allocation_pct']} "
                  f"({r['slippage_model']}): "
                  f"Sharpe={r['sharpe_ratio']:.2f}, Net={r['total_net_pnl']:,.0f}, "
                  f"WR={r['win_rate']:.0%}, DD={r['max_drawdown_pct']:.1%}, "
                  f"Annual={r['annual_return_pct']:.1f}%, Trades={r['total_trades']}")

    with open(output_dir / "combined_sweep.json", "w") as f:
        json.dump(combined_data, f, indent=2, default=str)
    print(f"Saved combined results to {output_dir / 'combined_sweep.json'}")

    elapsed = time.time() - start
    print(f"\nTotal sweep time: {elapsed:.0f}s ({elapsed/60:.1f}m)")


if __name__ == "__main__":
    main()
