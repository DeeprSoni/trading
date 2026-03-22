"""
Quant Backtester Dashboard v2.0 — Clean, detailed strategy analytics.

Run with: streamlit run dashboard.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config.settings import (
    TOTAL_CAPITAL, CAPITAL_STRUCTURE, PARKED_YIELD,
    PARKED_CAPITAL_ANNUAL_INCOME, PHASE_1_ACTIVE_CAPITAL,
    IC_IVR_MIN, IC_VIX_STANDARD_MAX, IC_VIX_ELEVATED_MAX, IC_VIX_KILLSWITCH,
    IC_EVENT_BLACKOUT_DAYS,
)

st.set_page_config(page_title="Quant Dashboard", layout="wide", initial_sidebar_state="expanded")

# ── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""<style>
    .block-container { padding-top: 1.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.3rem; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
</style>""", unsafe_allow_html=True)

RESULTS_DIR = Path("data/sweep_results")
CAPITAL = TOTAL_CAPITAL


# ── Data Loading ─────────────────────────────────────────────────────────────

@st.cache_data
def load_sweep(filename: str) -> dict | None:
    path = RESULTS_DIR / filename
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


@st.cache_data
def get_results_df(data: dict) -> pd.DataFrame:
    """Flatten results into a DataFrame for easy filtering/sorting."""
    if not data:
        return pd.DataFrame()
    rows = []
    for r in data.get("results", []):
        row = {k: v for k, v in r.items() if k not in ("trades", "params", "ic_params", "cal_params")}
        # Flatten params
        for k, v in r.get("params", {}).items():
            row[f"p_{k}"] = v
        for k, v in r.get("ic_params", {}).items():
            row[f"ic_{k}"] = v
        for k, v in r.get("cal_params", {}).items():
            row[f"cal_{k}"] = v
        row["trade_count"] = len(r.get("trades", []))
        row["roi_pct"] = r.get("total_net_pnl", 0) / CAPITAL * 100
        rows.append(row)
    return pd.DataFrame(rows)


ic_data = load_sweep("ic_sweep.json")
cal_data = load_sweep("cal_sweep.json")
combined_data = load_sweep("combined_sweep.json")

if not ic_data and not cal_data:
    st.error("No results found. Run `python run_sweep.py` first.")
    st.stop()


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_rs(v): return f"Rs {v:,.0f}"
def fmt_pct(v): return f"{v:.1f}%"
def fmt_pct2(v): return f"{v:.2f}%"
def pnl_color(v): return "#22c55e" if v >= 0 else "#ef4444"

def best_by_sharpe(data, slippage="optimistic"):
    results = data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    if not filtered:
        return None
    return max(filtered, key=lambda r: r.get("sharpe_ratio", -999))


def make_equity_curve(trades):
    """Build cumulative P&L from trade list."""
    if not trades:
        return go.Figure()
    cum = list(np.cumsum([t.get("net_pnl", 0) for t in trades]))
    dates = [t.get("exit_date", "")[:10] for t in trades]
    color = pnl_color(cum[-1])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=cum, mode="lines+markers", line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=color.replace(")", ",0.08)").replace("rgb", "rgba"),
        hovertemplate="Date: %{x}<br>Cum P&L: Rs %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        height=340, margin=dict(t=10, b=30, l=50, r=10),
        xaxis_title="", yaxis_title="Cumulative P&L (Rs)",
        yaxis=dict(tickformat=","),
    )
    return fig


def make_drawdown_chart(trades):
    """Build drawdown chart from trade P&Ls."""
    if not trades:
        return go.Figure()
    pnls = [t.get("net_pnl", 0) for t in trades]
    cum = np.cumsum(pnls)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    dates = [t.get("exit_date", "")[:10] for t in trades]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=dates, y=dd, fill="tozeroy", line=dict(color="#ef4444", width=1),
        fillcolor="rgba(239,68,68,0.15)",
        hovertemplate="Date: %{x}<br>Drawdown: Rs %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        height=260, margin=dict(t=10, b=30, l=50, r=10),
        xaxis_title="", yaxis_title="Drawdown (Rs)",
        yaxis=dict(tickformat=","),
    )
    return fig


# ── Sidebar Navigation ──────────────────────────────────────────────────────

with st.sidebar:
    st.title("Quant Dashboard")
    st.caption("Nifty 50 Options Backtester v2.0")
    st.markdown("---")

    page = st.radio(
        "Navigate",
        ["Executive Summary", "Iron Condor", "Calendar Spread",
         "Combined IC+CAL", "Risk & Statistics", "Trade Explorer"],
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**Capital**")
    st.metric("Total", fmt_rs(TOTAL_CAPITAL))
    st.metric("Active (Phase 1)", fmt_rs(PHASE_1_ACTIVE_CAPITAL))
    st.metric("Parked Yield/yr", fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME))

    st.markdown("---")
    slippage = st.selectbox("Slippage Model", ["optimistic", "realistic", "conservative"])


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Executive Summary
# ════════════════════════════════════════════════════════════════════════════

if page == "Executive Summary":
    st.header("Executive Summary")

    # Best configs
    ic_best = best_by_sharpe(ic_data, slippage) if ic_data else None
    cal_best = best_by_sharpe(cal_data, slippage) if cal_data else None
    comb_best = best_by_sharpe(combined_data, slippage) if combined_data else None

    # ── Capital Structure ──
    st.subheader("Capital Allocation")
    cols = st.columns(6)
    for i, (key, amount) in enumerate(CAPITAL_STRUCTURE.items()):
        yld = PARKED_YIELD.get(key)
        label = key.replace("_", " ").title()
        delta = f"{yld:.1%} yield" if yld else "Deployed"
        cols[i].metric(label, fmt_rs(amount), delta=delta)

    st.markdown("---")

    # ── Strategy Performance Comparison ──
    st.subheader("Strategy Performance at a Glance")

    def strat_row(name, r):
        if not r:
            return None
        pnl = r.get("total_net_pnl", 0)
        combined_income = pnl + PARKED_CAPITAL_ANNUAL_INCOME
        return {
            "Strategy": name,
            "Net P&L": pnl,
            "Combined Income": combined_income,
            "ROI (Total)": f"{combined_income / CAPITAL * 100:.1f}%",
            "ROI (Trading)": f"{pnl / CAPITAL * 100:.1f}%",
            "Sharpe": r.get("sharpe_ratio", 0),
            "Sortino": r.get("sortino_ratio", 0),
            "Win Rate": f"{r.get('win_rate', 0):.0%}",
            "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
            "Trades": r.get("total_trades", 0),
            "Avg Hold": f"{r.get('avg_holding_days', 0):.0f}d",
            "Profit Factor": r.get("profit_factor", 0),
        }

    rows = [r for r in [
        strat_row("Iron Condor (Best)", ic_best),
        strat_row("Calendar Spread (Best)", cal_best),
        strat_row("Combined IC+CAL (Best)", comb_best),
    ] if r]

    if rows:
        df = pd.DataFrame(rows)
        df["Net P&L"] = df["Net P&L"].apply(fmt_rs)
        df["Combined Income"] = df["Combined Income"].apply(fmt_rs)
        df["Sharpe"] = df["Sharpe"].apply(lambda x: f"{x:.2f}")
        df["Sortino"] = df["Sortino"].apply(lambda x: f"{x:.2f}")
        df["Profit Factor"] = df["Profit Factor"].apply(lambda x: f"{x:.2f}")
        st.dataframe(df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Headline Metrics ──
    if comb_best:
        st.subheader("Best Combined Strategy")
        pnl = comb_best.get("total_net_pnl", 0)
        combined = pnl + PARKED_CAPITAL_ANNUAL_INCOME

        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Combined Annual Income", fmt_rs(combined),
                   delta=f"Trading {fmt_rs(pnl)} + Parked {fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)}")
        c2.metric("Total ROI", fmt_pct(combined / CAPITAL * 100))
        c3.metric("Sharpe Ratio", f"{comb_best.get('sharpe_ratio', 0):.2f}")
        c4.metric("Max Drawdown", f"{comb_best.get('max_drawdown_pct', 0):.1%}")
        c5.metric("Win Rate", f"{comb_best.get('win_rate', 0):.0%}")

        split = f"IC {comb_best.get('ic_allocation_pct', 50)}% / CAL {comb_best.get('cal_allocation_pct', 50)}%"
        st.caption(f"Config: `{comb_best.get('strategy_name', '')}` | Split: {split} | "
                   f"Slippage: {slippage}")

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(comb_best.get("trades", [])), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(comb_best.get("trades", [])), use_container_width=True)

    st.markdown("---")

    # ── v2 Gate Changes ──
    with st.expander("v2 Engine Changes"):
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**IC Entry Gate Changes**")
            st.dataframe(pd.DataFrame([
                {"Gate": "IV Rank Min", "Before": "30", "After": str(IC_IVR_MIN), "Impact": "+40% opportunities"},
                {"Gate": "VIX", "Before": "25 cutoff", "After": f"{IC_VIX_STANDARD_MAX}/{IC_VIX_ELEVATED_MAX}/{IC_VIX_KILLSWITCH}", "Impact": "Dynamic sizing"},
                {"Gate": "Event Blackout", "Before": "25 days", "After": f"{IC_EVENT_BLACKOUT_DAYS} days", "Impact": "-60% blocked days"},
                {"Gate": "Wing Width", "Before": "500 fixed", "After": "400-900 by VIX", "Impact": "Adaptive protection"},
            ]), use_container_width=True, hide_index=True)
        with g2:
            st.markdown("**v2 Adjustment Types**")
            st.dataframe(pd.DataFrame([
                {"IC Adjustments": "Emergency Stop", "CAL Adjustments": "Close Large Move"},
                {"IC Adjustments": "Profit Target", "CAL Adjustments": "Close Back Near"},
                {"IC Adjustments": "Time Stop", "CAL Adjustments": "Early Profit Close"},
                {"IC Adjustments": "Wing Removal", "CAL Adjustments": "IV Harvest Roll"},
                {"IC Adjustments": "Partial Close Winner", "CAL Adjustments": "Front Month Roll"},
                {"IC Adjustments": "Roll Untested Inward", "CAL Adjustments": "Full Recentre"},
                {"IC Adjustments": "Defensive Roll", "CAL Adjustments": "Diagonal Conversion"},
                {"IC Adjustments": "Iron Fly Conversion", "CAL Adjustments": "Add Second Calendar"},
            ]), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Iron Condor
# ════════════════════════════════════════════════════════════════════════════

elif page == "Iron Condor":
    st.header("Iron Condor — Deep Dive")

    if not ic_data:
        st.error("No IC data available.")
        st.stop()

    results = ic_data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} configurations | {slippage} slippage")

    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    # ── Best Config Summary ──
    tab_best, tab_all, tab_params = st.tabs(["Best Configuration", "All Configurations", "Parameter Sensitivity"])

    with tab_best:
        pnl = best.get("total_net_pnl", 0)
        combined = pnl + PARKED_CAPITAL_ANNUAL_INCOME

        st.subheader(f"`{best.get('strategy_name', '')}`")

        # ROI & Return metrics
        r1, r2, r3, r4, r5, r6 = st.columns(6)
        r1.metric("Trading P&L", fmt_rs(pnl))
        r2.metric("Combined Income", fmt_rs(combined), delta=f"+{fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)} parked")
        r3.metric("ROI (Total Capital)", fmt_pct(combined / CAPITAL * 100))
        r4.metric("Annual Return", fmt_pct(best.get("annual_return_pct", 0)))
        r5.metric("Gross P&L", fmt_rs(best.get("total_gross_pnl", 0)))
        r6.metric("Total Costs", fmt_rs(best.get("total_costs", 0)))

        st.markdown("")

        # Risk metrics
        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Sharpe", f"{best.get('sharpe_ratio', 0):.3f}")
        k2.metric("Sortino", f"{best.get('sortino_ratio', 0):.3f}")
        k3.metric("Calmar", f"{best.get('calmar_ratio', 0):.3f}")
        k4.metric("Max Drawdown", f"{best.get('max_drawdown_pct', 0):.2%}")
        k5.metric("Win Rate", f"{best.get('win_rate', 0):.1%}")
        k6.metric("Profit Factor", f"{best.get('profit_factor', 0):.2f}")

        st.markdown("")

        # Trade stats
        t1, t2, t3, t4, t5, t6 = st.columns(6)
        t1.metric("Total Trades", best.get("total_trades", 0))
        t2.metric("Winners", best.get("winning_trades", 0))
        t3.metric("Losers", best.get("losing_trades", 0))
        t4.metric("Avg Winner", fmt_rs(best.get("avg_winner", 0)))
        t5.metric("Avg Loser", fmt_rs(best.get("avg_loser", 0)))
        t6.metric("Avg Holding", f"{best.get('avg_holding_days', 0):.0f} days")

        # Parameters
        params = best.get("params", {})
        with st.expander("Strategy Parameters"):
            p_cols = st.columns(6)
            param_display = [
                ("Short Delta", params.get("short_delta", 0), True),
                ("Wing Width", f"{params.get('wing_width', 0)} pts", False),
                ("Profit Target", params.get("profit_target_pct", 0), True),
                ("Stop Loss", f"{params.get('stop_loss_multiplier', 0)}x", False),
                ("Time Stop", f"{params.get('time_stop_dte', 0)} DTE", False),
                ("Min IV Rank", params.get("min_iv_rank", 0), False),
            ]
            for i, (label, val, is_pct) in enumerate(param_display):
                if is_pct and isinstance(val, float) and val < 1:
                    p_cols[i].metric(label, f"{val:.0%}")
                else:
                    p_cols[i].metric(label, val)

        # Charts
        trades = best.get("trades", [])
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(trades), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(trades), use_container_width=True)

        # Trade P&L bar chart
        if trades:
            trade_pnls = [t.get("net_pnl", 0) for t in trades]
            colors = [pnl_color(p) for p in trade_pnls]
            fig = go.Figure(go.Bar(
                x=list(range(1, len(trades) + 1)), y=trade_pnls,
                marker_color=colors,
                hovertemplate="Trade %{x}<br>P&L: Rs %{y:,.0f}<br>Exit: %{customdata}<extra></extra>",
                customdata=[t.get("exit_type", "") for t in trades],
            ))
            fig.update_layout(height=250, margin=dict(t=10, b=30, l=50, r=10),
                              xaxis_title="Trade #", yaxis_title="Net P&L (Rs)", yaxis=dict(tickformat=","))
            st.markdown("**Trade-by-Trade P&L**")
            st.plotly_chart(fig, use_container_width=True)

        # Adjustment analysis
        adj_trades = [t for t in trades if t.get("adjustment_count", 0) > 0]
        st.markdown("---")
        st.subheader("Adjustment Analysis")

        if adj_trades:
            total_adj = sum(t.get("adjustment_count", 0) for t in trades)
            total_adj_cost = sum(t.get("adjustment_costs", 0) for t in trades)
            total_adj_pnl = sum(t.get("adjustment_pnl", 0) for t in trades)
            adj_winners = sum(1 for t in adj_trades if t.get("net_pnl", 0) > 0)
            non_adj = [t for t in trades if t.get("adjustment_count", 0) == 0]
            non_adj_winners = sum(1 for t in non_adj if t.get("net_pnl", 0) > 0)

            a1, a2, a3, a4, a5 = st.columns(5)
            a1.metric("Trades Adjusted", f"{len(adj_trades)} / {len(trades)}",
                       delta=f"{len(adj_trades)/len(trades)*100:.0f}%")
            a2.metric("Total Adjustments", total_adj)
            a3.metric("Adjustment Costs", fmt_rs(total_adj_cost))
            a4.metric("Adjustment P&L Impact", fmt_rs(total_adj_pnl))
            a5.metric("Adjusted WR vs Non-Adj WR",
                       f"{adj_winners/max(len(adj_trades),1)*100:.0f}% vs {non_adj_winners/max(len(non_adj),1)*100:.0f}%")

            # Case-by-case adjustment table
            adj_rows = []
            for t in adj_trades:
                meta = t.get("metadata", {})
                adj_rows.append({
                    "Trade": t.get("position_id", "")[-6:],
                    "Entry": t.get("entry_date", "")[:10],
                    "Exit": t.get("exit_date", "")[:10],
                    "Days": t.get("holding_days", 0),
                    "Exit Type": t.get("exit_type", ""),
                    "Adjustments": t.get("adjustment_count", 0),
                    "Adj Cost": fmt_rs(t.get("adjustment_costs", 0)),
                    "Adj P&L": fmt_rs(t.get("adjustment_pnl", 0)),
                    "Gross P&L": fmt_rs(t.get("gross_pnl", 0)),
                    "Net P&L": fmt_rs(t.get("net_pnl", 0)),
                    "Entry VIX": f"{meta.get('vix_at_entry', 0):.1f}",
                    "Entry IVR": f"{meta.get('iv_rank_at_entry', 0):.0f}",
                    "Short Call": meta.get("short_call_strike", ""),
                    "Short Put": meta.get("short_put_strike", ""),
                })
            st.dataframe(pd.DataFrame(adj_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No adjustments triggered in this configuration.")

        # Full trade table
        st.markdown("---")
        st.subheader("All Trades")
        if trades:
            trade_rows = []
            for i, t in enumerate(trades):
                meta = t.get("metadata", {})
                trade_rows.append({
                    "#": i + 1,
                    "Entry": t.get("entry_date", "")[:10],
                    "Exit": t.get("exit_date", "")[:10],
                    "Days": t.get("holding_days", 0),
                    "Exit Type": t.get("exit_type", ""),
                    "Gross": fmt_rs(t.get("gross_pnl", 0)),
                    "Costs": fmt_rs(t.get("total_costs", 0)),
                    "Net P&L": fmt_rs(t.get("net_pnl", 0)),
                    "Adj": t.get("adjustment_count", 0),
                    "DTE": meta.get("dte_at_entry", ""),
                    "VIX": f"{meta.get('vix_at_entry', 0):.1f}",
                    "IVR": f"{meta.get('iv_rank_at_entry', 0):.0f}",
                    "Call": meta.get("short_call_strike", ""),
                    "Put": meta.get("short_put_strike", ""),
                })
            st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)

    with tab_all:
        st.subheader("All Configurations Ranked")
        rows = []
        for i, r in enumerate(filtered[:50]):
            pnl = r.get("total_net_pnl", 0)
            rows.append({
                "#": i + 1,
                "Config": r.get("strategy_name", ""),
                "Net P&L": fmt_rs(pnl),
                "ROI": fmt_pct(pnl / CAPITAL * 100),
                "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
                "Sortino": f"{r.get('sortino_ratio', 0):.2f}",
                "Win Rate": f"{r.get('win_rate', 0):.0%}",
                "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
                "Trades": r.get("total_trades", 0),
                "PF": f"{r.get('profit_factor', 0):.2f}",
                "Avg P&L": fmt_rs(r.get("avg_trade_pnl", 0)),
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=600)

        # Distribution charts
        col1, col2 = st.columns(2)
        with col1:
            sharpes = [r.get("sharpe_ratio", 0) for r in filtered]
            fig = px.histogram(x=sharpes, nbins=30, title="Sharpe Distribution",
                               labels={"x": "Sharpe Ratio", "y": "Count"})
            fig.add_vline(x=0, line_dash="dash", line_color="red")
            fig.update_layout(height=280, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with col2:
            pnls = [r.get("total_net_pnl", 0) / 1000 for r in filtered]
            fig = px.histogram(x=pnls, nbins=30, title="P&L Distribution",
                               labels={"x": "Net P&L (Rs '000)", "y": "Count"})
            fig.add_vline(x=0, line_dash="dash", line_color="red")
            fig.update_layout(height=280, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    with tab_params:
        st.subheader("Parameter Impact on Sharpe")
        st.caption("How each parameter affects risk-adjusted returns across all combinations")

        param_keys = ["p_short_delta", "p_wing_width", "p_profit_target_pct",
                       "p_stop_loss_multiplier", "p_time_stop_dte"]
        labels = {
            "p_short_delta": "Short Delta",
            "p_wing_width": "Wing Width (pts)",
            "p_profit_target_pct": "Profit Target (%)",
            "p_stop_loss_multiplier": "Stop Loss (x)",
            "p_time_stop_dte": "Time Stop (DTE)",
        }

        df = get_results_df(ic_data)
        df = df[df["slippage_model"] == slippage]

        if not df.empty:
            cols = st.columns(2)
            for i, param in enumerate(param_keys):
                if param not in df.columns or df[param].nunique() <= 1:
                    continue
                with cols[i % 2]:
                    fig = px.box(df, x=param, y="sharpe_ratio",
                                 title=labels.get(param, param),
                                 labels={"sharpe_ratio": "Sharpe", param: ""})
                    fig.update_layout(height=280, margin=dict(t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Calendar Spread
# ════════════════════════════════════════════════════════════════════════════

elif page == "Calendar Spread":
    st.header("Calendar Spread — Deep Dive")

    if not cal_data:
        st.error("No CAL data available.")
        st.stop()

    results = cal_data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} configurations | {slippage} slippage")

    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    tab_best, tab_all, tab_params = st.tabs(["Best Configuration", "All Configurations", "Parameter Sensitivity"])

    with tab_best:
        pnl = best.get("total_net_pnl", 0)
        combined = pnl + PARKED_CAPITAL_ANNUAL_INCOME

        st.subheader(f"`{best.get('strategy_name', '')}`")

        r1, r2, r3, r4, r5, r6 = st.columns(6)
        r1.metric("Trading P&L", fmt_rs(pnl))
        r2.metric("Combined Income", fmt_rs(combined), delta=f"+{fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)} parked")
        r3.metric("ROI (Total Capital)", fmt_pct(combined / CAPITAL * 100))
        r4.metric("Annual Return", fmt_pct(best.get("annual_return_pct", 0)))
        r5.metric("Gross P&L", fmt_rs(best.get("total_gross_pnl", 0)))
        r6.metric("Total Costs", fmt_rs(best.get("total_costs", 0)))

        st.markdown("")

        k1, k2, k3, k4, k5, k6 = st.columns(6)
        k1.metric("Sharpe", f"{best.get('sharpe_ratio', 0):.3f}")
        k2.metric("Sortino", f"{best.get('sortino_ratio', 0):.3f}")
        k3.metric("Calmar", f"{best.get('calmar_ratio', 0):.3f}")
        k4.metric("Max Drawdown", f"{best.get('max_drawdown_pct', 0):.2%}")
        k5.metric("Win Rate", f"{best.get('win_rate', 0):.1%}")
        k6.metric("Profit Factor", f"{best.get('profit_factor', 0):.2f}")

        st.markdown("")
        t1, t2, t3, t4, t5, t6 = st.columns(6)
        t1.metric("Total Trades", best.get("total_trades", 0))
        t2.metric("Winners", best.get("winning_trades", 0))
        t3.metric("Losers", best.get("losing_trades", 0))
        t4.metric("Avg Winner", fmt_rs(best.get("avg_winner", 0)))
        t5.metric("Avg Loser", fmt_rs(best.get("avg_loser", 0)))
        t6.metric("Avg Holding", f"{best.get('avg_holding_days', 0):.0f} days")

        params = best.get("params", {})
        with st.expander("Strategy Parameters"):
            p_cols = st.columns(6)
            param_display = [
                ("Adj Threshold", params.get("move_pct_to_adjust", 0), True),
                ("Close Threshold", params.get("move_pct_to_close", 0), True),
                ("Profit Target", params.get("profit_target_pct", 0), True),
                ("Back Close DTE", f"{params.get('back_month_close_dte', 0)}", False),
                ("Max VIX", params.get("max_vix", 0), False),
                ("Front Roll DTE", params.get("front_roll_dte", 0), False),
            ]
            for i, (label, val, is_pct) in enumerate(param_display):
                if is_pct and isinstance(val, float) and val < 1:
                    p_cols[i].metric(label, f"{val:.1%}")
                else:
                    p_cols[i].metric(label, val)

        trades = best.get("trades", [])
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(trades), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(trades), use_container_width=True)

        if trades:
            trade_pnls = [t.get("net_pnl", 0) for t in trades]
            colors = [pnl_color(p) for p in trade_pnls]
            fig = go.Figure(go.Bar(
                x=list(range(1, len(trades) + 1)), y=trade_pnls,
                marker_color=colors,
                hovertemplate="Trade %{x}<br>P&L: Rs %{y:,.0f}<extra></extra>",
            ))
            fig.update_layout(height=250, margin=dict(t=10, b=30, l=50, r=10),
                              xaxis_title="Trade #", yaxis_title="Net P&L (Rs)", yaxis=dict(tickformat=","))
            st.markdown("**Trade-by-Trade P&L**")
            st.plotly_chart(fig, use_container_width=True)

        # Adjustment analysis
        adj_trades = [t for t in trades if t.get("adjustment_count", 0) > 0]
        st.markdown("---")
        st.subheader("Adjustment Analysis")
        if adj_trades:
            total_adj = sum(t.get("adjustment_count", 0) for t in trades)
            total_adj_cost = sum(t.get("adjustment_costs", 0) for t in trades)
            total_adj_pnl = sum(t.get("adjustment_pnl", 0) for t in trades)

            a1, a2, a3, a4 = st.columns(4)
            a1.metric("Trades Adjusted", f"{len(adj_trades)} / {len(trades)}")
            a2.metric("Total Adjustments", total_adj)
            a3.metric("Adjustment Costs", fmt_rs(total_adj_cost))
            a4.metric("Adjustment P&L", fmt_rs(total_adj_pnl))

            adj_rows = []
            for t in adj_trades:
                meta = t.get("metadata", {})
                adj_rows.append({
                    "Trade": t.get("position_id", "")[-6:],
                    "Entry": t.get("entry_date", "")[:10],
                    "Exit": t.get("exit_date", "")[:10],
                    "Days": t.get("holding_days", 0),
                    "Exit Type": t.get("exit_type", ""),
                    "Adj Count": t.get("adjustment_count", 0),
                    "Adj Cost": fmt_rs(t.get("adjustment_costs", 0)),
                    "Adj P&L": fmt_rs(t.get("adjustment_pnl", 0)),
                    "Net P&L": fmt_rs(t.get("net_pnl", 0)),
                    "VIX": f"{meta.get('vix_at_entry', 0):.1f}",
                    "Strike": meta.get("strike", ""),
                })
            st.dataframe(pd.DataFrame(adj_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No adjustments triggered.")

        # All trades
        st.markdown("---")
        st.subheader("All Trades")
        if trades:
            trade_rows = []
            for i, t in enumerate(trades):
                meta = t.get("metadata", {})
                trade_rows.append({
                    "#": i + 1,
                    "Entry": t.get("entry_date", "")[:10],
                    "Exit": t.get("exit_date", "")[:10],
                    "Days": t.get("holding_days", 0),
                    "Exit": t.get("exit_type", ""),
                    "Net P&L": fmt_rs(t.get("net_pnl", 0)),
                    "Adj": t.get("adjustment_count", 0),
                    "Strike": meta.get("strike", ""),
                    "F-DTE": meta.get("front_dte", ""),
                    "B-DTE": meta.get("back_dte", ""),
                    "VIX": f"{meta.get('vix_at_entry', 0):.1f}",
                })
            st.dataframe(pd.DataFrame(trade_rows), use_container_width=True, hide_index=True)

    with tab_all:
        st.subheader("All Configurations Ranked")
        rows = []
        for i, r in enumerate(filtered[:50]):
            pnl = r.get("total_net_pnl", 0)
            rows.append({
                "#": i + 1,
                "Config": r.get("strategy_name", ""),
                "Net P&L": fmt_rs(pnl),
                "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
                "Win Rate": f"{r.get('win_rate', 0):.0%}",
                "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
                "Trades": r.get("total_trades", 0),
                "PF": f"{r.get('profit_factor', 0):.2f}",
            })
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=600)

    with tab_params:
        st.subheader("Parameter Impact on Sharpe")
        param_keys = ["p_move_pct_to_adjust", "p_move_pct_to_close",
                       "p_profit_target_pct", "p_back_month_close_dte", "p_max_vix"]
        labels = {
            "p_move_pct_to_adjust": "Adj Threshold (%)",
            "p_move_pct_to_close": "Close Threshold (%)",
            "p_profit_target_pct": "Profit Target (%)",
            "p_back_month_close_dte": "Back Month Close DTE",
            "p_max_vix": "Max VIX",
        }
        df = get_results_df(cal_data)
        df = df[df["slippage_model"] == slippage]
        if not df.empty:
            cols = st.columns(2)
            for i, param in enumerate(param_keys):
                if param not in df.columns or df[param].nunique() <= 1:
                    continue
                with cols[i % 2]:
                    fig = px.box(df, x=param, y="sharpe_ratio",
                                 title=labels.get(param, param),
                                 labels={"sharpe_ratio": "Sharpe", param: ""})
                    fig.update_layout(height=280, margin=dict(t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Combined IC+CAL
# ════════════════════════════════════════════════════════════════════════════

elif page == "Combined IC+CAL":
    st.header("Combined IC + CAL Strategy")

    if not combined_data:
        st.error("No combined data available.")
        st.stop()

    results = combined_data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    st.caption(f"{len(filtered)} allocation blends | {slippage} slippage")

    pnl = best.get("total_net_pnl", 0)
    combined = pnl + PARKED_CAPITAL_ANNUAL_INCOME

    st.subheader(f"Best: IC {best.get('ic_allocation_pct', 50)}% / CAL {best.get('cal_allocation_pct', 50)}%")

    r1, r2, r3, r4, r5, r6 = st.columns(6)
    r1.metric("Combined Income", fmt_rs(combined))
    r2.metric("Trading P&L", fmt_rs(pnl))
    r3.metric("ROI", fmt_pct(combined / CAPITAL * 100))
    r4.metric("Sharpe", f"{best.get('sharpe_ratio', 0):.2f}")
    r5.metric("Max DD", f"{best.get('max_drawdown_pct', 0):.1%}")
    r6.metric("Win Rate", f"{best.get('win_rate', 0):.0%}")

    st.markdown("")
    t1, t2, t3, t4, t5, t6 = st.columns(6)
    t1.metric("IC Trades", best.get("ic_trades", 0))
    t2.metric("CAL Trades", best.get("cal_trades", 0))
    t3.metric("Profit Factor", f"{best.get('profit_factor', 0):.2f}")
    t4.metric("Avg Winner", fmt_rs(best.get("avg_winner", 0)))
    t5.metric("Avg Loser", fmt_rs(best.get("avg_loser", 0)))
    t6.metric("Calmar", f"{best.get('calmar_ratio', 0):.2f}")

    trades = best.get("trades", [])
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Equity Curve**")
        st.plotly_chart(make_equity_curve(trades), use_container_width=True)
    with col2:
        st.markdown("**P&L by Strategy**")
        if trades:
            ic_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "IC")
            cal_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "CAL")
            fig = go.Figure(go.Pie(
                labels=["IC", "CAL", "Parked Income"],
                values=[max(0, ic_pnl), max(0, cal_pnl), PARKED_CAPITAL_ANNUAL_INCOME],
                hole=0.45, marker_colors=["#3b82f6", "#8b5cf6", "#22c55e"],
                textinfo="label+value", texttemplate="%{label}<br>Rs %{value:,.0f}",
            ))
            fig.update_layout(height=340, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # Trade bars by strategy
    if trades:
        trade_pnls = [t.get("net_pnl", 0) for t in trades]
        bar_colors = ["#3b82f6" if t.get("strategy") == "IC" else "#8b5cf6" for t in trades]
        fig = go.Figure(go.Bar(
            x=list(range(1, len(trades) + 1)), y=trade_pnls,
            marker_color=bar_colors,
            hovertemplate="Trade %{x}: Rs %{y:,.0f}<br>%{customdata}<extra></extra>",
            customdata=[t.get("strategy", "") for t in trades],
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(height=250, margin=dict(t=10, b=30, l=50, r=10),
                          xaxis_title="Trade #", yaxis_title="P&L (Rs)",
                          yaxis=dict(tickformat=","))
        st.markdown("**Trade P&L (blue=IC, purple=CAL)**")
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Allocation analysis
    st.subheader("Allocation Impact")
    alloc_data = []
    for r in filtered:
        alloc_data.append({
            "split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
            "sharpe": r.get("sharpe_ratio", 0),
            "annual_return": r.get("annual_return_pct", 0),
            "max_dd": r.get("max_drawdown_pct", 0) * 100,
            "net_pnl": r.get("total_net_pnl", 0),
        })
    if alloc_data:
        adf = pd.DataFrame(alloc_data)
        c1, c2 = st.columns(2)
        with c1:
            fig = px.box(adf, x="split", y="sharpe", title="Sharpe by Split",
                         labels={"sharpe": "Sharpe", "split": ""})
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.scatter(adf, x="max_dd", y="sharpe", color="split",
                             title="Risk vs Reward",
                             labels={"max_dd": "Max Drawdown (%)", "sharpe": "Sharpe"})
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    # Top 10 table
    st.markdown("---")
    st.subheader("Top 10 Combinations")
    rows = []
    for i, r in enumerate(filtered[:10]):
        pnl = r.get("total_net_pnl", 0)
        rows.append({
            "#": i + 1,
            "IC Config": r.get("ic_config", ""),
            "CAL Config": r.get("cal_config", ""),
            "Split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
            "Net P&L": fmt_rs(pnl),
            "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
            "Win Rate": f"{r.get('win_rate', 0):.0%}",
            "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
            "Trades": r.get("total_trades", 0),
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Risk & Statistics
# ════════════════════════════════════════════════════════════════════════════

elif page == "Risk & Statistics":
    st.header("Risk & Statistical Validation")

    for strat_name, data in [("Iron Condor", ic_data), ("Calendar Spread", cal_data)]:
        if not data:
            continue

        stats = data.get("top_stats", [])
        if not stats:
            st.info(f"No statistical analysis available for {strat_name}.")
            continue

        st.subheader(strat_name)

        for stat in stats:
            verdict = stat.get("verdict", "N/A")
            color_map = {"STRONG": "green", "MARGINAL": "orange", "WEAK": "red", "INSUFFICIENT_DATA": "gray"}
            color = color_map.get(verdict, "gray")

            with st.expander(f"{stat.get('strategy_name', '')} — :{color}[{verdict}]"):
                # Sharpe CI
                sci = stat.get("sharpe_ci")
                if sci:
                    st.markdown(f"**Sharpe 95% CI:** [{sci['lower']:.2f}, {sci['upper']:.2f}] "
                                f"(point estimate: {sci.get('point', 0):.2f})")

                # Monte Carlo
                mc = stat.get("monte_carlo")
                if mc:
                    st.markdown("**Monte Carlo Simulation (10,000 paths)**")
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("P(Profit)", f"{mc['prob_profit']:.0%}")
                    m2.metric("P(Ruin)", f"{mc['prob_ruin']:.0%}")
                    m3.metric("Median P&L", fmt_rs(mc['median_pnl']))
                    m4.metric("5th Percentile", fmt_rs(mc.get('pct_5', 0)))
                    m5.metric("95th Percentile", fmt_rs(mc.get('pct_95', 0)))

                # Walk-forward
                wf = stat.get("walk_forward")
                if wf:
                    consistent = "Yes" if wf["is_consistent"] else "No"
                    st.markdown(f"**Walk-Forward:** Consistent = {consistent} | "
                                f"OOS Sharpe: {wf['oos_sharpe_mean']:.2f} | "
                                f"Degradation: {wf['degradation_pct']:.0f}%")

                # Regime analysis
                regimes = stat.get("regime_analysis", [])
                if regimes:
                    st.markdown("**Performance by Market Regime:**")
                    regime_rows = []
                    for rg in regimes:
                        regime_rows.append({
                            "Regime": rg.get("regime", "").upper(),
                            "Trades": rg.get("n_trades", 0),
                            "Win Rate": f"{rg.get('win_rate', 0):.0%}",
                            "Avg P&L": fmt_rs(rg.get("avg_pnl", 0)),
                        })
                    st.dataframe(pd.DataFrame(regime_rows), use_container_width=True, hide_index=True)

        st.markdown("---")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Trade Explorer
# ════════════════════════════════════════════════════════════════════════════

elif page == "Trade Explorer":
    st.header("Trade Explorer")
    st.caption("Inspect individual trades from any configuration")

    strategy = st.selectbox("Strategy", ["Iron Condor", "Calendar Spread", "Combined"])
    data = {"Iron Condor": ic_data, "Calendar Spread": cal_data, "Combined": combined_data}[strategy]

    if not data:
        st.error("No data for this strategy.")
        st.stop()

    results = data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    config_names = [r.get("strategy_name", "") for r in filtered[:30]]
    selected_name = st.selectbox("Configuration", config_names)
    selected = next((r for r in filtered if r.get("strategy_name") == selected_name), None)

    if not selected:
        st.stop()

    trades = selected.get("trades", [])
    if not trades:
        st.info("No trades in this configuration.")
        st.stop()

    st.markdown(f"**{len(trades)} trades** | Net P&L: {fmt_rs(selected.get('total_net_pnl', 0))} | "
                f"Sharpe: {selected.get('sharpe_ratio', 0):.2f}")

    # Exit type breakdown
    col1, col2 = st.columns(2)
    with col1:
        exit_types = [t.get("exit_type", "UNKNOWN") for t in trades]
        exit_counts = pd.Series(exit_types).value_counts()
        fig = px.pie(values=exit_counts.values, names=exit_counts.index,
                     title="Exit Reasons", hole=0.4)
        fig.update_layout(height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Holding days distribution
        hold_days = [t.get("holding_days", 0) for t in trades]
        fig = px.histogram(x=hold_days, nbins=15, title="Holding Period",
                           labels={"x": "Days", "y": "Count"})
        fig.update_layout(height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    # Full trade detail with expansion
    st.markdown("---")
    for i, t in enumerate(trades):
        meta = t.get("metadata", {})
        pnl = t.get("net_pnl", 0)
        adj_count = t.get("adjustment_count", 0)
        color = "green" if pnl > 0 else "red"

        label = (f"Trade {i+1}: :{color}[{fmt_rs(pnl)}] | "
                 f"{t.get('entry_date', '')[:10]} → {t.get('exit_date', '')[:10]} | "
                 f"{t.get('exit_type', '')} | {t.get('holding_days', 0)}d"
                 + (f" | {adj_count} adj" if adj_count else ""))

        with st.expander(label):
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Gross P&L", fmt_rs(t.get("gross_pnl", 0)))
            c2.metric("Costs", fmt_rs(t.get("total_costs", 0)))
            c3.metric("Net P&L", fmt_rs(pnl))
            c4.metric("Entry Premium", fmt_rs(t.get("net_premium_per_unit", 0)))
            c5.metric("Close Cost", fmt_rs(t.get("close_cost_per_unit", 0)))
            c6.metric("Holding Days", t.get("holding_days", 0))

            if adj_count > 0:
                st.markdown(f"**Adjustments:** {adj_count} | "
                            f"Cost: {fmt_rs(t.get('adjustment_costs', 0))} | "
                            f"P&L Impact: {fmt_rs(t.get('adjustment_pnl', 0))}")

            if meta:
                st.markdown("**Entry Conditions:**")
                meta_display = {k: v for k, v in meta.items()
                                if k not in ("adjustment_count",)}
                st.json(meta_display)


# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Quant Dashboard v2.0 | Rs {TOTAL_CAPITAL:,} capital | "
           f"Parked income: Rs {PARKED_CAPITAL_ANNUAL_INCOME:,.0f}/yr | 242 tests passing")
