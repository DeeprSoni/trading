"""
Streamlit Dashboard — view and analyse backtest results.

Run with: streamlit run dashboard.py
Loads pre-computed sweep results from data/sweep_results/ on startup.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Quant Backtester", layout="wide")

RESULTS_DIR = Path("data/sweep_results")


# ─── Data Loading ───────────────────────────────────────────────────────────


@st.cache_data
def load_sweep(filename: str) -> dict | None:
    path = RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def summarise_strategy(data: dict, capital: float = 750_000) -> dict:
    """Compute a clean summary for one strategy type across all slippage models."""
    results = data.get("results", [])
    if not results:
        return {}

    by_slippage = {}
    for r in results:
        slip = r.get("slippage_model", "unknown")
        by_slippage.setdefault(slip, []).append(r)

    summaries = {}
    for slip, rs in by_slippage.items():
        best = max(rs, key=lambda r: r.get("sharpe_ratio", -999))
        profitable = sum(1 for r in rs if r.get("total_net_pnl", 0) > 0)
        pnls = [r.get("total_net_pnl", 0) for r in rs]
        sharpes = [r.get("sharpe_ratio", 0) for r in rs]

        best_annual_ret = best.get("annual_return_pct", 0)
        best_pnl = best.get("total_net_pnl", 0)
        best_roi = (best_pnl / capital * 100) if capital > 0 else 0

        summaries[slip] = {
            "configs_tested": len(rs),
            "profitable": profitable,
            "best_name": best.get("strategy_name", ""),
            "best_roi_pct": round(best_roi, 1),
            "best_annual_return_pct": round(best_annual_ret, 1),
            "best_sharpe": best.get("sharpe_ratio", 0),
            "best_win_rate": best.get("win_rate", 0),
            "best_max_dd_pct": best.get("max_drawdown_pct", 0),
            "best_trades": best.get("total_trades", 0),
            "best_net_pnl": best_pnl,
            "best_total_costs": best.get("total_costs", 0),
            "median_sharpe": round(float(np.median(sharpes)), 2),
            "median_pnl": round(float(np.median(pnls)), 0),
        }

    return summaries


# ─── Load Data ──────────────────────────────────────────────────────────────

ic_data = load_sweep("ic_sweep.json")
cal_data = load_sweep("cal_sweep.json")
combined_data = load_sweep("combined_sweep.json")

if not ic_data and not cal_data:
    st.error("No results found. Run `python run_sweep.py` first.")
    st.stop()

CAPITAL = 750_000
ic_summary = summarise_strategy(ic_data, CAPITAL) if ic_data else {}
cal_summary = summarise_strategy(cal_data, CAPITAL) if cal_data else {}


def summarise_combined(data: dict, capital: float = 750_000) -> dict:
    """Summarise combined IC+CAL results grouped by slippage."""
    results = data.get("results", [])
    if not results:
        return {}

    by_slippage = {}
    for r in results:
        slip = r.get("slippage_model", "unknown")
        by_slippage.setdefault(slip, []).append(r)

    summaries = {}
    for slip, rs in by_slippage.items():
        best = max(rs, key=lambda r: r.get("sharpe_ratio", -999))
        profitable = sum(1 for r in rs if r.get("total_net_pnl", 0) > 0)
        pnls = [r.get("total_net_pnl", 0) for r in rs]
        sharpes = [r.get("sharpe_ratio", 0) for r in rs]

        best_pnl = best.get("total_net_pnl", 0)
        best_roi = (best_pnl / capital * 100) if capital > 0 else 0

        summaries[slip] = {
            "configs_tested": len(rs),
            "profitable": profitable,
            "best_name": best.get("strategy_name", ""),
            "best_roi_pct": round(best_roi, 1),
            "best_annual_return_pct": round(best.get("annual_return_pct", 0), 1),
            "best_sharpe": best.get("sharpe_ratio", 0),
            "best_win_rate": best.get("win_rate", 0),
            "best_max_dd_pct": best.get("max_drawdown_pct", 0),
            "best_trades": best.get("total_trades", 0),
            "best_net_pnl": best_pnl,
            "best_total_costs": best.get("total_costs", 0),
            "best_ic_alloc": best.get("ic_allocation_pct", 50),
            "best_cal_alloc": best.get("cal_allocation_pct", 50),
            "median_sharpe": round(float(np.median(sharpes)), 2),
            "median_pnl": round(float(np.median(pnls)), 0),
        }

    return summaries


combined_summary = summarise_combined(combined_data, CAPITAL) if combined_data else {}


# ─── Navigation ─────────────────────────────────────────────────────────────

if "page" not in st.session_state:
    st.session_state.page = "overview"
if "detail_strategy" not in st.session_state:
    st.session_state.detail_strategy = None
if "detail_config" not in st.session_state:
    st.session_state.detail_config = None


def go_to_detail(strategy_type):
    st.session_state.page = "detail"
    st.session_state.detail_strategy = strategy_type


def go_to_config(strategy_type, config_name, slippage):
    st.session_state.page = "config"
    st.session_state.detail_strategy = strategy_type
    st.session_state.detail_config = (config_name, slippage)


def go_home():
    st.session_state.page = "overview"
    st.session_state.detail_strategy = None
    st.session_state.detail_config = None


# ─── PAGE: Overview ─────────────────────────────────────────────────────────

def render_overview():
    st.title("Backtest Results")

    total_configs = (len(ic_data.get("results", [])) if ic_data else 0) + \
                    (len(cal_data.get("results", [])) if cal_data else 0)
    total_profitable = sum(
        1 for r in (ic_data or {}).get("results", []) + (cal_data or {}).get("results", [])
        if r.get("total_net_pnl", 0) > 0
    )

    st.caption(f"{total_configs:,} configurations tested across 2 strategies | "
               f"Capital: Rs {CAPITAL:,} | Data: Synthetic Nifty 50 (Jun 2022 - Dec 2023)")

    st.markdown("---")

    # ── Strategy cards ──

    def render_strategy_card(name, emoji, description, summary, strategy_key):
        """Render a clean strategy overview card."""
        if not summary:
            st.info(f"No {name} results available.")
            return

        # Use realistic slippage as the headline number
        realistic = summary.get("realistic", summary.get(list(summary.keys())[0], {}))

        st.subheader(f"{emoji} {name}")
        st.caption(description)

        # Headline metrics
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Best ROI", f"{realistic['best_roi_pct']}%",
                   help="Total return on Rs 7.5L capital (realistic slippage)")
        c2.metric("Annual Return", f"{realistic['best_annual_return_pct']}%")
        c3.metric("Win Rate", f"{realistic['best_win_rate']:.0%}")
        c4.metric("Max Drawdown", f"{realistic['best_max_dd_pct']:.1%}")
        c5.metric("Trades", realistic["best_trades"])

        # Slippage comparison table
        rows = []
        for slip in ["optimistic", "realistic", "conservative"]:
            s = summary.get(slip)
            if not s:
                continue
            rows.append({
                "Scenario": slip.capitalize(),
                "Configs": s["configs_tested"],
                "Profitable": f"{s['profitable']}/{s['configs_tested']}",
                "Best ROI": f"{s['best_roi_pct']}%",
                "Best Sharpe": f"{s['best_sharpe']:.2f}",
                "Median Sharpe": f"{s['median_sharpe']:.2f}",
                "Best Net P&L": f"Rs {s['best_net_pnl']:,.0f}",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        if st.button(f"View {name} Details", key=f"btn_{strategy_key}",
                      use_container_width=True, type="primary"):
            go_to_detail(strategy_key)
            st.rerun()

    render_strategy_card(
        "Iron Condor", "IC",
        "Sell OTM call + put spreads to collect premium. Profits when market stays in a range.",
        ic_summary, "IC",
    )

    st.markdown("---")

    render_strategy_card(
        "Calendar Spread", "CAL",
        "Buy far-month ATM call, sell near-month ATM call. Profits from time decay differential.",
        cal_summary, "CAL",
    )

    st.markdown("---")

    # ── Combined IC+CAL card ──
    if combined_summary:
        _render_combined_card(combined_summary)

    # ── About section ──

    st.markdown("---")
    with st.expander("How this works"):
        st.markdown("""
**What was tested:**
- **Iron Condor**: 324 parameter combinations x 3 slippage scenarios = **972 backtests**
  - Parameters: short delta (0.10-0.25), wing width (300-700 pts), profit target (40-65%),
    stop loss multiplier (1.5-3x), time stop (14-28 DTE)
- **Calendar Spread**: 243 parameter combinations x 3 slippage scenarios = **729 backtests**
  - Parameters: adjustment threshold (1.5-3%), close threshold (3-5%), profit target (30-75%),
    back month close DTE (20-30), max VIX (25-32)

**Slippage models** (how much worse your fills are vs mid-price):
- **Optimistic**: 50% of bid-ask spread
- **Realistic**: 75% of bid-ask spread
- **Conservative**: 100% of spread + Rs 1 extra

**All costs included**: Brokerage (Rs 20/order), STT (0.0625%), exchange charges,
SEBI fee, stamp duty, GST (18%), margin opportunity cost.

**Data**: Synthetic option chains generated from real Nifty 50 spot prices (Jun 2022 - Dec 2023)
using Black-Scholes pricing with volatility skew. Since the data is synthetic, actual
P&L numbers are illustrative — the value is in comparing *relative* performance across
parameter combinations to find what matters most.
        """)


# ─── PAGE: Strategy Detail ─────────────────────────────────────────────────

def render_detail():
    strategy = st.session_state.detail_strategy
    data = ic_data if strategy == "IC" else cal_data
    label = "Iron Condor" if strategy == "IC" else "Calendar Spread"

    if not data:
        st.error(f"No {label} data.")
        return

    if st.button("< Back to Overview"):
        go_home()
        st.rerun()

    st.title(f"{label} — Detailed Analysis")

    results = data.get("results", [])

    # Sidebar filter
    slippage = st.radio("Slippage Model", ["realistic", "optimistic", "conservative"],
                        horizontal=True)
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered_sorted = sorted(filtered, key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} configurations | Sorted by Sharpe ratio (best first)")

    # ── Top 10 table ──

    st.subheader("Top 10 Configurations")

    top10 = filtered_sorted[:10]
    rows = []
    for i, r in enumerate(top10):
        pnl = r.get("total_net_pnl", 0)
        roi = pnl / CAPITAL * 100
        rows.append({
            "#": i + 1,
            "Name": r.get("strategy_name", ""),
            "ROI": f"{roi:.1f}%",
            "Net P&L": f"Rs {pnl:,.0f}",
            "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
            "Win Rate": f"{r.get('win_rate', 0):.0%}",
            "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
            "Trades": r.get("total_trades", 0),
            "Costs": f"Rs {r.get('total_costs', 0):,.0f}",
            "Avg Hold": f"{r.get('avg_holding_days', 0):.0f}d",
        })

    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Select a config for deeper dive ──

    config_names = [r.get("strategy_name", "") for r in filtered_sorted[:30]]
    if config_names:
        selected_name = st.selectbox("Select a configuration to inspect", config_names)
        selected = next((r for r in filtered_sorted if r.get("strategy_name") == selected_name), None)

        if selected:
            _render_config_detail(selected, label)

    # ── Parameter sensitivity ──

    st.markdown("---")
    st.subheader("What Parameters Matter?")
    st.caption("Box plots show how each parameter affects Sharpe ratio across all combinations.")

    if strategy == "IC":
        param_keys = ["short_delta", "wing_width", "profit_target_pct",
                       "stop_loss_multiplier", "time_stop_dte"]
        param_labels = {
            "short_delta": "Short Delta (how far OTM)",
            "wing_width": "Wing Width (protection spread, pts)",
            "profit_target_pct": "Profit Target (%)",
            "stop_loss_multiplier": "Stop Loss (x premium)",
            "time_stop_dte": "Time Stop (DTE to close)",
        }
    else:
        param_keys = ["move_pct_to_adjust", "move_pct_to_close",
                       "profit_target_pct", "back_month_close_dte", "max_vix"]
        param_labels = {
            "move_pct_to_adjust": "Adjustment Threshold (%)",
            "move_pct_to_close": "Close Threshold (%)",
            "profit_target_pct": "Profit Target (%)",
            "back_month_close_dte": "Back Month Close DTE",
            "max_vix": "Max VIX for Entry",
        }

    param_data = []
    for r in filtered:
        p = r.get("params", {})
        row = {"sharpe": r.get("sharpe_ratio", 0), "net_pnl": r.get("total_net_pnl", 0)}
        for k in param_keys:
            row[k] = p.get(k, 0)
        param_data.append(row)

    if param_data:
        pdf = pd.DataFrame(param_data)
        cols = st.columns(2)
        for i, param in enumerate(param_keys):
            if pdf[param].nunique() <= 1:
                continue
            with cols[i % 2]:
                fig = px.box(
                    pdf, x=param, y="sharpe",
                    title=param_labels.get(param, param),
                    labels={"sharpe": "Sharpe Ratio", param: ""},
                )
                fig.update_layout(height=280, margin=dict(t=40, b=20))
                st.plotly_chart(fig, use_container_width=True)

    # ── Distribution ──

    st.markdown("---")
    st.subheader("Results Distribution")

    c1, c2 = st.columns(2)
    with c1:
        sharpes = [r.get("sharpe_ratio", 0) for r in filtered]
        fig = px.histogram(x=sharpes, nbins=30, title="Sharpe Ratio",
                           labels={"x": "Sharpe", "y": "Count"})
        fig.add_vline(x=0, line_dash="dash", line_color="red")
        fig.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        pnls = [r.get("total_net_pnl", 0) / 1000 for r in filtered]
        fig = px.histogram(x=pnls, nbins=30, title="Net P&L",
                           labels={"x": "Net P&L (Rs '000)", "y": "Count"})
        fig.add_vline(x=0, line_dash="dash", line_color="red")
        fig.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # ── Stats ──

    stats = data.get("top_stats", [])
    if stats:
        st.markdown("---")
        st.subheader("Statistical Validation (Top 5)")
        st.caption("Bootstrap confidence intervals, Monte Carlo simulation, walk-forward testing")

        for i, stat in enumerate(stats):
            verdict = stat.get("verdict", "N/A")
            color = {"STRONG": ":green", "MARGINAL": ":orange", "WEAK": ":red"}.get(verdict, "")
            with st.expander(f"#{i+1} {stat.get('strategy_name', '')} — {color}[{verdict}]"):
                sci = stat.get("sharpe_ci")
                if sci:
                    st.write(f"**Sharpe 95% CI:** [{sci['lower']:.2f}, {sci['upper']:.2f}]")

                mc = stat.get("monte_carlo")
                if mc:
                    mc1, mc2, mc3 = st.columns(3)
                    mc1.metric("P(Profit)", f"{mc['prob_profit']:.0%}")
                    mc2.metric("P(Ruin)", f"{mc['prob_ruin']:.0%}")
                    mc3.metric("Median P&L", f"Rs {mc['median_pnl']:,.0f}")

                wf = stat.get("walk_forward")
                if wf:
                    consistent = "Yes" if wf["is_consistent"] else "No"
                    st.write(f"**Walk-Forward Consistent:** {consistent} | "
                             f"OOS Sharpe: {wf['oos_sharpe_mean']:.2f} | "
                             f"Degradation: {wf['degradation_pct']:.0f}%")

                regimes = stat.get("regime_analysis", [])
                if regimes:
                    st.dataframe(pd.DataFrame(regimes), use_container_width=True, hide_index=True)


# ─── Config detail (inline within strategy page) ───────────────────────────

def _render_config_detail(r: dict, strategy_label: str):
    """Show detailed view for one specific configuration."""
    st.markdown("---")
    st.subheader(f"Config: {r.get('strategy_name', '')}")

    # Key params
    params = r.get("params", {})
    if params:
        display_params = {k: v for k, v in params.items()
                         if k not in ("lot_size", "max_open_positions", "max_pct_capital",
                                      "min_dte", "max_dte", "min_iv_rank",
                                      "front_min_dte", "front_max_dte", "back_min_dte", "back_max_dte",
                                      "front_roll_dte", "front_profit_roll_pct", "iv_harvest_pct")}
        cols = st.columns(len(display_params))
        for i, (k, v) in enumerate(display_params.items()):
            label = k.replace("_", " ").title()
            if isinstance(v, float) and v < 1:
                cols[i].metric(label, f"{v:.0%}")
            else:
                cols[i].metric(label, v)

    # Summary metrics
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    pnl = r.get("total_net_pnl", 0)
    roi = pnl / CAPITAL * 100
    c1.metric("ROI", f"{roi:.1f}%")
    c2.metric("Net P&L", f"Rs {pnl:,.0f}")
    c3.metric("Win Rate", f"{r.get('win_rate', 0):.0%}")
    c4.metric("Max DD", f"{r.get('max_drawdown_pct', 0):.1%}")
    c5.metric("Sharpe", f"{r.get('sharpe_ratio', 0):.2f}")
    c6.metric("Profit Factor", f"{r.get('profit_factor', 0):.2f}")

    # P&L breakdown
    with st.expander("P&L Breakdown"):
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Gross P&L", f"Rs {r.get('total_gross_pnl', 0):,.0f}")
        b2.metric("Total Costs", f"Rs {r.get('total_costs', 0):,.0f}")
        b3.metric("Avg Winner", f"Rs {r.get('avg_winner', 0):,.0f}")
        b4.metric("Avg Loser", f"Rs {r.get('avg_loser', 0):,.0f}")

    # Adjustment summary
    trades = r.get("trades", [])
    adj_trades = [t for t in trades if t.get("adjustment_count", 0) > 0]
    if adj_trades:
        with st.expander("Adjustment Summary"):
            total_adj = sum(t.get("adjustment_count", 0) for t in trades)
            total_adj_cost = sum(t.get("adjustment_costs", 0) for t in trades)
            total_adj_pnl = sum(t.get("adjustment_pnl", 0) for t in trades)
            adj_winners = sum(1 for t in adj_trades if t.get("net_pnl", 0) > 0)

            a1, a2, a3, a4, a5 = st.columns(5)
            a1.metric("Trades Adjusted", f"{len(adj_trades)}/{len(trades)}")
            a2.metric("Total Adjustments", total_adj)
            a3.metric("Adj Costs", f"Rs {total_adj_cost:,.0f}")
            a4.metric("Adj Realized P&L", f"Rs {total_adj_pnl:,.0f}")
            a5.metric("Adj Trade WR", f"{adj_winners/len(adj_trades):.0%}" if adj_trades else "N/A")

    # Trade-level charts
    trades = r.get("trades", [])
    if trades:
        col_a, col_b = st.columns(2)

        with col_a:
            # Cumulative P&L curve
            cum_pnl = list(np.cumsum([t.get("net_pnl", 0) for t in trades]))
            dates = [t.get("exit_date", "")[:10] for t in trades]
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=dates, y=cum_pnl,
                mode="lines+markers",
                fill="tozeroy",
                line=dict(color="#ef4444" if cum_pnl[-1] < 0 else "#22c55e", width=2),
                fillcolor="rgba(239,68,68,0.1)" if cum_pnl[-1] < 0 else "rgba(34,197,94,0.1)",
            ))
            fig.update_layout(title="Equity Curve", height=320,
                              xaxis_title="", yaxis_title="Cumulative P&L (Rs)",
                              margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            # Exit type pie
            exit_types = [t.get("exit_type", "UNKNOWN") for t in trades]
            exit_counts = pd.Series(exit_types).value_counts()
            fig = px.pie(values=exit_counts.values, names=exit_counts.index,
                         title="How Trades Ended", hole=0.4)
            fig.update_layout(height=320, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        # Individual trade P&L bar chart
        trade_pnls = [t.get("net_pnl", 0) for t in trades]
        colors = ["#22c55e" if p > 0 else "#ef4444" for p in trade_pnls]
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=list(range(1, len(trade_pnls) + 1)), y=trade_pnls,
            marker_color=colors,
        ))
        fig.update_layout(title="Trade-by-Trade P&L", height=280,
                          xaxis_title="Trade #", yaxis_title="Net P&L (Rs)",
                          margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

        # Trade table
        with st.expander(f"All {len(trades)} Trades"):
            trade_rows = [{
                "#": i + 1,
                "Entry": t.get("entry_date", "")[:10],
                "Exit": t.get("exit_date", "")[:10],
                "Days": t.get("holding_days", 0),
                "Exit Type": t.get("exit_type", ""),
                "Gross": f"Rs {t.get('gross_pnl', 0):,.0f}",
                "Costs": f"Rs {t.get('total_costs', 0):,.0f}",
                "Net P&L": f"Rs {t.get('net_pnl', 0):,.0f}",
                "Adj": t.get("adjustment_count", 0),
                "Adj Cost": f"Rs {t.get('adjustment_costs', 0):,.0f}" if t.get("adjustment_count", 0) > 0 else "-",
                "Adj P&L": f"Rs {t.get('adjustment_pnl', 0):,.0f}" if t.get("adjustment_count", 0) > 0 else "-",
            } for i, t in enumerate(trades)]
            st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)
    else:
        st.info("Trade-level detail not available for this configuration.")


# ─── Combined Strategy Card (for Overview) ────────────────────────────────

def _render_combined_card(summary):
    """Render the combined IC+CAL overview card."""
    realistic = summary.get("realistic", summary.get(list(summary.keys())[0], {}))

    st.subheader("IC+CAL Combined Strategy")
    st.caption("Run Iron Condor and Calendar Spread simultaneously on the same capital "
               "with different allocation splits (30/70 to 70/30).")

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Best ROI", f"{realistic['best_roi_pct']}%",
              help="Total return on Rs 7.5L capital (realistic slippage)")
    c2.metric("Annual Return", f"{realistic['best_annual_return_pct']}%")
    c3.metric("Win Rate", f"{realistic['best_win_rate']:.0%}")
    c4.metric("Max Drawdown", f"{realistic['best_max_dd_pct']:.1%}")
    c5.metric("Trades", realistic["best_trades"])
    c6.metric("Best Split", f"IC{realistic['best_ic_alloc']}/CAL{realistic['best_cal_alloc']}")

    rows = []
    for slip in ["optimistic", "realistic", "conservative"]:
        s = summary.get(slip)
        if not s:
            continue
        rows.append({
            "Scenario": slip.capitalize(),
            "Configs": s["configs_tested"],
            "Profitable": f"{s['profitable']}/{s['configs_tested']}",
            "Best ROI": f"{s['best_roi_pct']}%",
            "Best Sharpe": f"{s['best_sharpe']:.2f}",
            "Best Split": f"IC{s['best_ic_alloc']}/CAL{s['best_cal_alloc']}",
            "Best Net P&L": f"Rs {s['best_net_pnl']:,.0f}",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if st.button("View Combined Details", key="btn_COMBINED",
                  use_container_width=True, type="primary"):
        go_to_detail("COMBINED")
        st.rerun()


# ─── PAGE: Combined Detail ────────────────────────────────────────────────

def render_combined_detail():
    if not combined_data:
        st.error("No combined data. Run `python run_sweep.py` first.")
        return

    if st.button("< Back to Overview"):
        go_home()
        st.rerun()

    st.title("Combined IC+CAL -- Detailed Analysis")

    results = combined_data.get("results", [])

    slippage = st.radio("Slippage Model", ["realistic", "optimistic", "conservative"],
                        horizontal=True, key="combined_slip")
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered_sorted = sorted(filtered, key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} combinations | Top IC configs x Top CAL configs x 5 allocation splits")

    # ── Top 10 table ──
    st.subheader("Top 10 Combinations")

    top10 = filtered_sorted[:10]
    rows = []
    for i, r in enumerate(top10):
        pnl = r.get("total_net_pnl", 0)
        roi = pnl / CAPITAL * 100
        rows.append({
            "#": i + 1,
            "IC Config": r.get("ic_config", ""),
            "CAL Config": r.get("cal_config", ""),
            "Split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
            "ROI": f"{roi:.1f}%",
            "Annual": f"{r.get('annual_return_pct', 0):.1f}%",
            "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
            "Win Rate": f"{r.get('win_rate', 0):.0%}",
            "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
            "Trades": f"{r.get('ic_trades', 0)}IC + {r.get('cal_trades', 0)}CAL",
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Allocation analysis ──
    st.markdown("---")
    st.subheader("Capital Allocation Impact")
    st.caption("How does the IC/CAL split affect performance?")

    alloc_data = []
    for r in filtered:
        alloc_data.append({
            "IC %": r.get("ic_allocation_pct", 50),
            "CAL %": r.get("cal_allocation_pct", 50),
            "split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
            "annual_return": r.get("annual_return_pct", 0),
            "sharpe": r.get("sharpe_ratio", 0),
            "net_pnl": r.get("total_net_pnl", 0),
            "max_dd": r.get("max_drawdown_pct", 0) * 100,
        })

    if alloc_data:
        adf = pd.DataFrame(alloc_data)

        col_a, col_b = st.columns(2)
        with col_a:
            fig = px.box(adf, x="split", y="annual_return",
                         title="Annual Return by Allocation Split",
                         labels={"annual_return": "Annual Return (%)", "split": ""})
            fig.update_layout(height=320, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_b:
            fig = px.box(adf, x="split", y="sharpe",
                         title="Sharpe Ratio by Allocation Split",
                         labels={"sharpe": "Sharpe Ratio", "split": ""})
            fig.update_layout(height=320, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        col_c, col_d = st.columns(2)
        with col_c:
            fig = px.box(adf, x="split", y="max_dd",
                         title="Max Drawdown by Allocation Split",
                         labels={"max_dd": "Max Drawdown (%)", "split": ""})
            fig.update_layout(height=320, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

        with col_d:
            # Scatter: return vs drawdown (efficient frontier)
            fig = px.scatter(adf, x="max_dd", y="annual_return", color="split",
                             title="Return vs Drawdown (Efficient Frontier)",
                             labels={"max_dd": "Max Drawdown (%)",
                                     "annual_return": "Annual Return (%)"})
            fig.update_layout(height=320, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    # ── Select and inspect one combination ──
    st.markdown("---")
    st.subheader("Inspect a Combination")

    combo_names = [f"#{i+1} {r.get('ic_config','')} + {r.get('cal_config','')} "
                   f"(IC{r.get('ic_allocation_pct',50)}/CAL{r.get('cal_allocation_pct',50)})"
                   for i, r in enumerate(filtered_sorted[:20])]

    if combo_names:
        selected_idx = combo_names.index(
            st.selectbox("Select a combination", combo_names, key="combo_select")
        )
        selected = filtered_sorted[selected_idx]
        _render_combined_config(selected)


def _render_combined_config(r: dict):
    """Show detailed view for one combined IC+CAL configuration."""
    st.markdown("---")

    # Config info
    col1, col2 = st.columns(2)
    with col1:
        st.markdown(f"**IC Config:** `{r.get('ic_config', '')}`")
        ic_p = r.get("ic_params", {})
        display = {k: v for k, v in ic_p.items()
                   if k in ("short_delta", "wing_width", "profit_target_pct",
                            "stop_loss_multiplier", "time_stop_dte")}
        if display:
            st.json(display)
    with col2:
        st.markdown(f"**CAL Config:** `{r.get('cal_config', '')}`")
        cal_p = r.get("cal_params", {})
        display = {k: v for k, v in cal_p.items()
                   if k in ("move_pct_to_adjust", "move_pct_to_close",
                            "profit_target_pct", "back_month_close_dte", "max_vix")}
        if display:
            st.json(display)

    # Summary metrics
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    pnl = r.get("total_net_pnl", 0)
    roi = pnl / CAPITAL * 100
    c1.metric("ROI", f"{roi:.1f}%")
    c2.metric("Annual Return", f"{r.get('annual_return_pct', 0):.1f}%")
    c3.metric("Win Rate", f"{r.get('win_rate', 0):.0%}")
    c4.metric("Max DD", f"{r.get('max_drawdown_pct', 0):.1%}")
    c5.metric("Sharpe", f"{r.get('sharpe_ratio', 0):.2f}")
    c6.metric("Profit Factor", f"{r.get('profit_factor', 0):.2f}")

    # P&L breakdown
    b1, b2, b3, b4 = st.columns(4)
    b1.metric("Gross P&L", f"Rs {r.get('total_gross_pnl', 0):,.0f}")
    b2.metric("Total Costs", f"Rs {r.get('total_costs', 0):,.0f}")
    b3.metric("IC Trades", r.get("ic_trades", 0))
    b4.metric("CAL Trades", r.get("cal_trades", 0))

    trades = r.get("trades", [])
    if not trades:
        return

    # Equity curve
    col_a, col_b = st.columns(2)
    with col_a:
        cum_pnl = list(np.cumsum([t.get("net_pnl", 0) for t in trades]))
        dates = [t.get("exit_date", "")[:10] for t in trades]
        colors_line = "#22c55e" if cum_pnl[-1] >= 0 else "#ef4444"
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=dates, y=cum_pnl,
            mode="lines+markers",
            fill="tozeroy",
            line=dict(color=colors_line, width=2),
            fillcolor="rgba(34,197,94,0.1)" if cum_pnl[-1] >= 0 else "rgba(239,68,68,0.1)",
        ))
        fig.update_layout(title="Combined Equity Curve", height=320,
                          xaxis_title="", yaxis_title="Cumulative P&L (Rs)",
                          margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    with col_b:
        # Strategy contribution pie
        ic_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "IC")
        cal_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "CAL")
        fig = go.Figure(data=[go.Pie(
            labels=["IC P&L", "CAL P&L"],
            values=[max(0, ic_pnl), max(0, cal_pnl)],
            hole=0.4,
            marker_colors=["#3b82f6", "#8b5cf6"],
        )])
        fig.update_layout(title="P&L Contribution by Strategy", height=320,
                          margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # Trade P&L bars colored by strategy
    trade_pnls = [t.get("net_pnl", 0) for t in trades]
    bar_colors = ["#3b82f6" if t.get("strategy") == "IC" else "#8b5cf6" for t in trades]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=list(range(1, len(trade_pnls) + 1)), y=trade_pnls,
        marker_color=bar_colors,
        text=[t.get("strategy", "") for t in trades],
        hovertemplate="Trade %{x}: %{y:,.0f}<br>%{text}<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(title="Trade-by-Trade P&L (blue=IC, purple=CAL)", height=300,
                      xaxis_title="Trade #", yaxis_title="Net P&L (Rs)",
                      margin=dict(t=40, b=20))
    st.plotly_chart(fig, use_container_width=True)

    # Adjustment summary
    adj_trades = [t for t in trades if t.get("adjustment_count", 0) > 0]
    if adj_trades:
        with st.expander("Adjustment Summary"):
            total_adj = sum(t.get("adjustment_count", 0) for t in trades)
            total_adj_cost = sum(t.get("adjustment_costs", 0) for t in trades)
            total_adj_pnl = sum(t.get("adjustment_pnl", 0) for t in trades)
            ic_adj = sum(1 for t in adj_trades if t.get("strategy") == "IC")
            cal_adj = sum(1 for t in adj_trades if t.get("strategy") == "CAL")

            a1, a2, a3, a4, a5 = st.columns(5)
            a1.metric("Trades Adjusted", f"{len(adj_trades)}/{len(trades)}")
            a2.metric("Total Adjustments", total_adj)
            a3.metric("Adj Costs", f"Rs {total_adj_cost:,.0f}")
            a4.metric("Adj Realized P&L", f"Rs {total_adj_pnl:,.0f}")
            a5.metric("IC/CAL Adj", f"{ic_adj} / {cal_adj}")

    # Trade table
    with st.expander(f"All {len(trades)} Trades"):
        trade_rows = [{
            "#": i + 1,
            "Strategy": t.get("strategy", ""),
            "Entry": t.get("entry_date", "")[:10],
            "Exit": t.get("exit_date", "")[:10],
            "Days": t.get("holding_days", 0),
            "Exit Type": t.get("exit_type", ""),
            "Gross": f"Rs {t.get('gross_pnl', 0):,.0f}",
            "Costs": f"Rs {t.get('total_costs', 0):,.0f}",
            "Net P&L": f"Rs {t.get('net_pnl', 0):,.0f}",
            "Adj": t.get("adjustment_count", 0),
            "Adj Cost": f"Rs {t.get('adjustment_costs', 0):,.0f}" if t.get("adjustment_count", 0) > 0 else "-",
        } for i, t in enumerate(trades)]
        st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)


# ─── Router ─────────────────────────────────────────────────────────────────

page = st.session_state.page

if page == "overview":
    render_overview()
elif page == "detail":
    strategy = st.session_state.detail_strategy
    if strategy == "COMBINED":
        render_combined_detail()
    else:
        render_detail()
else:
    render_overview()

# Footer
st.markdown("---")
st.caption("Quant Backtester | Nifty 50 Options | Synthetic Data")
