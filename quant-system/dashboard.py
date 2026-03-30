"""
Quant Backtester Dashboard v2.0

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
    PHASE_3_ACTIVE_CAPITAL,
    # IC entry gates (v2)
    IC_IVR_MIN, IC_IV_ABOVE_REALIZED,
    IC_VIX_STANDARD_MAX, IC_VIX_ELEVATED_MAX, IC_VIX_KILLSWITCH,
    IC_EVENT_BLACKOUT_DAYS, IC_EVENT_EXPIRY_BLACKOUT_DAYS,
    IC_SHORT_DELTA, IC_WING_WIDTH_POINTS, IC_MIN_DTE_ENTRY, IC_MAX_DTE_ENTRY,
    IC_PROFIT_TARGET_PCT, IC_STOP_LOSS_MULTIPLIER, IC_TIME_STOP_DTE,
    IC_MAX_OPEN_POSITIONS,
    # CAL parameters
    CAL_BACK_MONTH_MIN_DTE, CAL_BACK_MONTH_MAX_DTE,
    CAL_FRONT_MONTH_MIN_DTE, CAL_FRONT_MONTH_MAX_DTE,
    CAL_PROFIT_TARGET_PCT, CAL_BACK_MONTH_CLOSE_DTE,
    CAL_MAX_MOVE_PCT_TO_ADJUST, CAL_MAX_MOVE_PCT_TO_CLOSE,
    CAL_MAX_OPEN_POSITIONS,
    # Risk controls
    ACCOUNT_DRAWDOWN_SIZE_DOWN, ACCOUNT_DRAWDOWN_STOP,
)

st.set_page_config(page_title="Quant Dashboard", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>
    .block-container { padding-top: 1.5rem; }
    [data-testid="stMetricValue"] { font-size: 1.25rem; }
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


# Load both synthetic (baseline) and real data results
ic_data = load_sweep("ic_sweep.json")
cal_data = load_sweep("cal_sweep.json")
combined_data = load_sweep("combined_sweep.json")

# Real data results (2024 NSE)
ic_real = load_sweep("ic_sweep_real.json")
cal_real = load_sweep("cal_sweep_real.json")

if not ic_data and not cal_data and not ic_real:
    st.error("No results found. Run `python run_sweep.py` first.")
    st.stop()


# ── Helpers ──────────────────────────────────────────────────────────────────

def fmt_rs(v): return f"Rs {v:,.0f}"
def pnl_color(v): return "#22c55e" if v >= 0 else "#ef4444"


def best_config(data, slippage, key="sharpe_ratio"):
    results = data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    if not filtered:
        return None
    return max(filtered, key=lambda r: r.get(key, -999))


def make_equity_curve(trades):
    if not trades:
        return go.Figure()
    cum = list(np.cumsum([t.get("net_pnl", 0) for t in trades]))
    dates = [t.get("exit_date", "")[:10] for t in trades]
    color = pnl_color(cum[-1])
    fig = go.Figure(go.Scatter(
        x=dates, y=cum, mode="lines+markers", line=dict(color=color, width=2),
        fill="tozeroy", fillcolor=color.replace(")", ",0.08)").replace("rgb", "rgba"),
        hovertemplate="Date: %{x}<br>P&L: Rs %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(height=320, margin=dict(t=10, b=30, l=50, r=10),
                      yaxis_title="Cumulative P&L (Rs)", yaxis=dict(tickformat=","))
    return fig


def make_drawdown_chart(trades):
    if not trades:
        return go.Figure()
    cum = np.cumsum([t.get("net_pnl", 0) for t in trades])
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    dates = [t.get("exit_date", "")[:10] for t in trades]
    fig = go.Figure(go.Scatter(
        x=dates, y=dd, fill="tozeroy", line=dict(color="#ef4444", width=1),
        fillcolor="rgba(239,68,68,0.12)",
        hovertemplate="Date: %{x}<br>DD: Rs %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(height=250, margin=dict(t=10, b=30, l=50, r=10),
                      yaxis_title="Drawdown (Rs)", yaxis=dict(tickformat=","))
    return fig


def render_metrics_row(r, label_prefix=""):
    """Render 3 rows of 6 metrics for a backtest result."""
    pnl = r.get("total_net_pnl", 0)
    combined = pnl + PARKED_CAPITAL_ANNUAL_INCOME

    st.markdown("**Returns**")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Trading P&L", fmt_rs(pnl))
    c2.metric("+ Parked Income", fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME))
    c3.metric("Combined Income", fmt_rs(combined))
    c4.metric("ROI (Total)", f"{combined / CAPITAL * 100:.1f}%")
    c5.metric("ROI (Trading)", f"{pnl / CAPITAL * 100:.1f}%")
    c6.metric("Annual Return", f"{r.get('annual_return_pct', 0):.1f}%")

    st.markdown("**Risk**")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Sharpe", f"{r.get('sharpe_ratio', 0):.3f}")
    k2.metric("Sortino", f"{r.get('sortino_ratio', 0):.3f}")
    k3.metric("Calmar", f"{r.get('calmar_ratio', 0):.3f}")
    k4.metric("Max Drawdown", f"{r.get('max_drawdown_pct', 0):.2%}")
    k5.metric("Max DD (Rs)", fmt_rs(r.get("max_drawdown", 0)))
    k6.metric("Profit Factor", f"{r.get('profit_factor', 0):.2f}")

    st.markdown("**Trades**")
    t1, t2, t3, t4, t5, t6 = st.columns(6)
    t1.metric("Total", r.get("total_trades", 0))
    t2.metric("Win Rate", f"{r.get('win_rate', 0):.1%}")
    t3.metric("Winners / Losers", f"{r.get('winning_trades', 0)} / {r.get('losing_trades', 0)}")
    t4.metric("Avg Winner", fmt_rs(r.get("avg_winner", 0)))
    t5.metric("Avg Loser", fmt_rs(r.get("avg_loser", 0)))
    t6.metric("Avg Hold", f"{r.get('avg_holding_days', 0):.0f} days")


def render_adjustment_analysis(trades):
    """Render adjustment breakdown with case-by-case table."""
    adj_trades = [t for t in trades if t.get("adjustment_count", 0) > 0]
    non_adj = [t for t in trades if t.get("adjustment_count", 0) == 0]

    if not adj_trades:
        st.info("No adjustments triggered in this configuration.")
        return

    total_adj = sum(t.get("adjustment_count", 0) for t in trades)
    total_adj_cost = sum(t.get("adjustment_costs", 0) for t in trades)
    total_adj_pnl = sum(t.get("adjustment_pnl", 0) for t in trades)
    adj_wr = sum(1 for t in adj_trades if t.get("net_pnl", 0) > 0) / len(adj_trades) * 100
    non_adj_wr = (sum(1 for t in non_adj if t.get("net_pnl", 0) > 0) / len(non_adj) * 100) if non_adj else 0

    a1, a2, a3, a4, a5 = st.columns(5)
    a1.metric("Adjusted / Total", f"{len(adj_trades)} / {len(trades)}")
    a2.metric("Total Adjustments", total_adj)
    a3.metric("Adj Costs", fmt_rs(total_adj_cost))
    a4.metric("Adj P&L Impact", fmt_rs(total_adj_pnl))
    a5.metric("WR: Adj vs Non-Adj", f"{adj_wr:.0f}% vs {non_adj_wr:.0f}%")

    # Case-by-case table
    st.markdown("**Adjusted Trades — Case by Case**")
    rows = []
    for t in adj_trades:
        meta = t.get("metadata", {})
        rows.append({
            "ID": t.get("position_id", "")[-8:],
            "Entry": t.get("entry_date", "")[:10],
            "Exit": t.get("exit_date", "")[:10],
            "Days": t.get("holding_days", 0),
            "Exit Type": t.get("exit_type", ""),
            "Adj #": t.get("adjustment_count", 0),
            "Adj Cost": fmt_rs(t.get("adjustment_costs", 0)),
            "Adj P&L": fmt_rs(t.get("adjustment_pnl", 0)),
            "Gross": fmt_rs(t.get("gross_pnl", 0)),
            "Net P&L": fmt_rs(t.get("net_pnl", 0)),
            "VIX": f"{meta.get('vix_at_entry', 0):.1f}",
            "IVR": f"{meta.get('iv_rank_at_entry', 0):.0f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_trades_table(trades, strategy_type="IC"):
    """Render full trade table."""
    rows = []
    for i, t in enumerate(trades):
        meta = t.get("metadata", {})
        row = {
            "#": i + 1,
            "Entry": t.get("entry_date", "")[:10],
            "Exit": t.get("exit_date", "")[:10],
            "Days": t.get("holding_days", 0),
            "Exit Type": t.get("exit_type", ""),
            "Gross": fmt_rs(t.get("gross_pnl", 0)),
            "Costs": fmt_rs(t.get("total_costs", 0)),
            "Net P&L": fmt_rs(t.get("net_pnl", 0)),
            "Adj": t.get("adjustment_count", 0),
        }
        if strategy_type == "IC":
            row["DTE"] = meta.get("dte_at_entry", "")
            row["VIX"] = f"{meta.get('vix_at_entry', 0):.1f}"
            row["IVR"] = f"{meta.get('iv_rank_at_entry', 0):.0f}"
            row["SC"] = meta.get("short_call_strike", "")
            row["SP"] = meta.get("short_put_strike", "")
        elif strategy_type == "CAL":
            row["Strike"] = meta.get("strike", "")
            row["F-DTE"] = meta.get("front_dte", "")
            row["B-DTE"] = meta.get("back_dte", "")
            row["VIX"] = f"{meta.get('vix_at_entry', 0):.1f}"
        rows.append(row)
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_stats_section(data, label):
    """Render statistical validation (bootstrap, MC, walk-forward, regime)."""
    stats = data.get("top_stats", [])
    if not stats:
        st.info(f"No statistical analysis for {label}.")
        return

    for stat in stats:
        verdict = stat.get("verdict", "N/A")
        cmap = {"STRONG": "green", "MARGINAL": "orange", "WEAK": "red", "INSUFFICIENT_DATA": "gray"}
        color = cmap.get(verdict, "gray")

        with st.expander(f"{stat.get('strategy_name', '')} — :{color}[{verdict}]"):
            sci = stat.get("sharpe_ci")
            if sci:
                st.markdown(f"**Sharpe 95% CI:** [{sci['lower']:.2f}, {sci['upper']:.2f}] "
                            f"(point: {sci.get('point', 0):.2f})")

            mc = stat.get("monte_carlo")
            if mc:
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("P(Profit)", f"{mc['prob_profit']:.0%}")
                m2.metric("P(Ruin)", f"{mc['prob_ruin']:.0%}")
                m3.metric("Median P&L", fmt_rs(mc['median_pnl']))
                m4.metric("5th %ile", fmt_rs(mc.get('pct_5', 0)))
                m5.metric("95th %ile", fmt_rs(mc.get('pct_95', 0)))

            wf = stat.get("walk_forward")
            if wf:
                st.markdown(f"**Walk-Forward:** Consistent = {'Yes' if wf['is_consistent'] else 'No'} | "
                            f"OOS Sharpe: {wf['oos_sharpe_mean']:.2f} | "
                            f"Degradation: {wf['degradation_pct']:.0f}%")

            regimes = stat.get("regime_analysis", [])
            if regimes:
                st.markdown("**Regime Breakdown:**")
                st.dataframe(pd.DataFrame([{
                    "Regime": rg["regime"].upper(),
                    "Trades": rg["n_trades"],
                    "Win Rate": f"{rg['win_rate']:.0%}",
                    "Avg P&L": fmt_rs(rg["avg_pnl"]),
                } for rg in regimes]), use_container_width=True, hide_index=True)


# ── Sidebar ──────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("Quant Dashboard")
    st.caption("Nifty 50 Options | v2.0")
    st.markdown("---")

    page = st.radio("", [
        "Live Market",
        "Overview",
        "Iron Condor",
        "Calendar Spread",
        "Combined IC+CAL",
        "Risk & Statistics",
        "Trade Explorer",
    ], label_visibility="collapsed")

    st.markdown("---")
    data_sources = ["Synthetic (baseline)"]
    if ic_real:
        data_sources.append("Real NSE 2024")
    data_source = st.radio("Data Source", data_sources, index=len(data_sources)-1)
    use_real = data_source == "Real NSE 2024"

    if use_real:
        slippage = "realistic"
        st.caption("Real data: realistic slippage only")
    else:
        slippage = st.selectbox("Slippage Model", ["optimistic", "realistic", "conservative"])

    st.markdown("---")
    st.caption("**Capital**")
    st.caption(f"Total: {fmt_rs(TOTAL_CAPITAL)}")
    st.caption(f"Active: {fmt_rs(PHASE_1_ACTIVE_CAPITAL)}")
    st.caption(f"Parked yield: {fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)}/yr")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Live Market
# ════════════════════════════════════════════════════════════════════════════

if page == "Live Market":
    st.header("Live Market")

    # ── Section 1: Market Status ──────────────────────────────────────────
    st.subheader("Market Status")

    ms1, ms2, ms3, ms4 = st.columns(4)
    ms1.metric("Total Capital", fmt_rs(TOTAL_CAPITAL))
    ms2.metric("Phase 1 Active", fmt_rs(PHASE_1_ACTIVE_CAPITAL))
    ms3.metric("Phase 3 Active", fmt_rs(PHASE_3_ACTIVE_CAPITAL))
    ms4.metric("Parked Yield / yr", fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME))

    # Data Status
    real_data_path = Path("data/real_data_cache")
    if real_data_path.exists():
        parquet_files = list(real_data_path.glob("*.parquet"))
        csv_files = list(real_data_path.glob("*.csv"))
        total_cache_files = len(parquet_files) + len(csv_files)
        st.success(f"Data cache found: **{total_cache_files}** files "
                   f"({len(parquet_files)} parquet, {len(csv_files)} csv) "
                   f"in `data/real_data_cache/`")
    else:
        st.warning("No real data cache found. Directory `data/real_data_cache/` does not exist. "
                   "Run the data fetcher to populate market data.")

    # Projected Metrics Table
    st.markdown("**Projected Metrics (Phase 1-4 targets)**")
    proj = pd.DataFrame([
        {"Phase": "Phase 1 -- Nifty IC+CAL", "Active Capital": fmt_rs(PHASE_1_ACTIVE_CAPITAL),
         "Target ROI": "8-12%", "Target Sharpe": ">1.5", "Max DD": "<5%",
         "Trades/yr": "50-60", "Monthly Rs": "5,000-7,500"},
        {"Phase": "Phase 2 -- v2 Adjustments", "Active Capital": fmt_rs(PHASE_1_ACTIVE_CAPITAL),
         "Target ROI": "11-16%", "Target Sharpe": ">2.0", "Max DD": "<5%",
         "Trades/yr": "55-65", "Monthly Rs": "7,000-10,000"},
        {"Phase": "Phase 3 -- BankNifty+FinNifty", "Active Capital": fmt_rs(PHASE_3_ACTIVE_CAPITAL),
         "Target ROI": "15-20%", "Target Sharpe": ">2.0", "Max DD": "<7%",
         "Trades/yr": "80-100", "Monthly Rs": "9,500-12,500"},
        {"Phase": "Phase 4 -- Compounding", "Active Capital": fmt_rs(PHASE_3_ACTIVE_CAPITAL),
         "Target ROI": "18-21%", "Target Sharpe": ">2.0", "Max DD": "<8%",
         "Trades/yr": "90-110", "Monthly Rs": "11,000-13,000"},
    ])
    st.dataframe(proj, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Section 2: Entry Signal Check ─────────────────────────────────────
    st.subheader("Entry Signal Check")

    ec1, ec2 = st.columns(2)

    with ec1:
        st.markdown("**Iron Condor v2 Entry Gates**")
        ic_gates = pd.DataFrame([
            {"Gate": "1. IV Rank", "Check": "IVR >= threshold",
             "Threshold": f"{IC_IVR_MIN}",
             "Detail": "IV rank must be above median; relaxed from 30 to 20"},
            {"Gate": "2. IV vs Realized", "Check": "IV > realized * (1 + buffer)",
             "Threshold": f"{IC_IV_ABOVE_REALIZED:.0%}",
             "Detail": "IV must be 15% above 30-day realized vol"},
            {"Gate": "3. VIX Standard", "Check": "VIX < max for full size",
             "Threshold": f"{IC_VIX_STANDARD_MAX}",
             "Detail": "Below: standard wings + full size"},
            {"Gate": "4. VIX Elevated", "Check": "VIX < max for half size",
             "Threshold": f"{IC_VIX_ELEVATED_MAX}",
             "Detail": "25-35: wider wings + half size"},
            {"Gate": "5. VIX Kill Switch", "Check": "VIX < panic threshold",
             "Threshold": f"{IC_VIX_KILLSWITCH}",
             "Detail": "Above 40: no new ICs (genuine panic)"},
            {"Gate": "6. Event Blackout", "Check": "No major event within N days",
             "Threshold": f"{IC_EVENT_BLACKOUT_DAYS}d entry / {IC_EVENT_EXPIRY_BLACKOUT_DAYS}d expiry",
             "Detail": "Avoid entries near RBI, budget, elections"},
            {"Gate": "7. Max Positions", "Check": "Open ICs < max",
             "Threshold": f"{IC_MAX_OPEN_POSITIONS}",
             "Detail": "Concurrent IC position limit"},
            {"Gate": "8. Drawdown Gate", "Check": "Account DD < stop level",
             "Threshold": f"{ACCOUNT_DRAWDOWN_SIZE_DOWN:.0%} size-down / {ACCOUNT_DRAWDOWN_STOP:.0%} stop",
             "Detail": "Auto size-down at 3% DD, full stop at 5%"},
        ])
        st.dataframe(ic_gates, use_container_width=True, hide_index=True)

        with st.expander("IC Trade Parameters"):
            ip1, ip2, ip3 = st.columns(3)
            ip1.metric("Short Delta", f"{IC_SHORT_DELTA}")
            ip2.metric("Wing Width", f"{IC_WING_WIDTH_POINTS} pts")
            ip3.metric("DTE Range", f"{IC_MIN_DTE_ENTRY}-{IC_MAX_DTE_ENTRY}")
            ip4, ip5, ip6 = st.columns(3)
            ip4.metric("Profit Target", f"{IC_PROFIT_TARGET_PCT:.0%}")
            ip5.metric("Stop Loss", f"{IC_STOP_LOSS_MULTIPLIER}x")
            ip6.metric("Time Stop", f"{IC_TIME_STOP_DTE} DTE")

    with ec2:
        st.markdown("**Calendar Spread v2 Entry Gates**")
        cal_gates = pd.DataFrame([
            {"Gate": "1. Front Month DTE", "Check": "Front DTE in range",
             "Threshold": f"{CAL_FRONT_MONTH_MIN_DTE}-{CAL_FRONT_MONTH_MAX_DTE} DTE",
             "Detail": "Monthly front month (weeklies discontinued)"},
            {"Gate": "2. Back Month DTE", "Check": "Back DTE in range",
             "Threshold": f"{CAL_BACK_MONTH_MIN_DTE}-{CAL_BACK_MONTH_MAX_DTE} DTE",
             "Detail": "Back month 60-75 DTE for theta decay"},
            {"Gate": "3. Move to Adjust", "Check": "Spot move < adjust threshold",
             "Threshold": f"{CAL_MAX_MOVE_PCT_TO_ADJUST:.0%}",
             "Detail": "Recentre if spot moves >2% from strike"},
            {"Gate": "4. Move to Close", "Check": "Spot move < close threshold",
             "Threshold": f"{CAL_MAX_MOVE_PCT_TO_CLOSE:.0%}",
             "Detail": "Close if spot moves >4% (unrecoverable)"},
            {"Gate": "5. Profit Target", "Check": "Spread value >= target",
             "Threshold": f"{CAL_PROFIT_TARGET_PCT:.0%}",
             "Detail": "Take profit at 50% of max gain"},
            {"Gate": "6. Back Close DTE", "Check": "Close back month before expiry",
             "Threshold": f"{CAL_BACK_MONTH_CLOSE_DTE} DTE",
             "Detail": "Close back leg at 25 DTE to avoid gamma"},
            {"Gate": "7. Max Positions", "Check": "Open CALs < max",
             "Threshold": f"{CAL_MAX_OPEN_POSITIONS}",
             "Detail": "Concurrent calendar position limit"},
            {"Gate": "8. Drawdown Gate", "Check": "Account DD < stop level",
             "Threshold": f"{ACCOUNT_DRAWDOWN_SIZE_DOWN:.0%} size-down / {ACCOUNT_DRAWDOWN_STOP:.0%} stop",
             "Detail": "Same account-level risk controls as IC"},
        ])
        st.dataframe(cal_gates, use_container_width=True, hide_index=True)

        with st.expander("CAL Trade Parameters"):
            cp1, cp2 = st.columns(2)
            cp1.metric("Front DTE", f"{CAL_FRONT_MONTH_MIN_DTE}-{CAL_FRONT_MONTH_MAX_DTE}")
            cp2.metric("Back DTE", f"{CAL_BACK_MONTH_MIN_DTE}-{CAL_BACK_MONTH_MAX_DTE}")
            cp3, cp4 = st.columns(2)
            cp3.metric("Adjust Threshold", f"{CAL_MAX_MOVE_PCT_TO_ADJUST:.0%}")
            cp4.metric("Close Threshold", f"{CAL_MAX_MOVE_PCT_TO_CLOSE:.0%}")

    st.markdown("---")

    # ── Section 3: Strategy Summary ───────────────────────────────────────
    st.subheader("Strategy Summary (from sweep)")

    ic_best_lm = best_config(active_ic, slippage) if active_ic else None
    cal_best_lm = best_config(cal_data, slippage) if cal_data else None
    comb_best_lm = best_config(combined_data, slippage) if combined_data else None

    sc1, sc2, sc3 = st.columns(3)

    with sc1:
        st.markdown("**Iron Condor**")
        if ic_best_lm:
            st.metric("Net P&L", fmt_rs(ic_best_lm.get("total_net_pnl", 0)))
            st.metric("Sharpe", f"{ic_best_lm.get('sharpe_ratio', 0):.2f}")
            st.metric("Win Rate", f"{ic_best_lm.get('win_rate', 0):.0%}")
            st.metric("Max DD", f"{ic_best_lm.get('max_drawdown_pct', 0):.1%}")
            st.metric("Trades", ic_best_lm.get("total_trades", 0))
            st.caption(ic_best_lm.get("strategy_name", ""))
        else:
            st.info("No IC sweep data.")

    with sc2:
        st.markdown("**Calendar Spread**")
        if cal_best_lm:
            st.metric("Net P&L", fmt_rs(cal_best_lm.get("total_net_pnl", 0)))
            st.metric("Sharpe", f"{cal_best_lm.get('sharpe_ratio', 0):.2f}")
            st.metric("Win Rate", f"{cal_best_lm.get('win_rate', 0):.0%}")
            st.metric("Max DD", f"{cal_best_lm.get('max_drawdown_pct', 0):.1%}")
            st.metric("Trades", cal_best_lm.get("total_trades", 0))
            st.caption(cal_best_lm.get("strategy_name", ""))
        else:
            st.info("No CAL sweep data.")

    with sc3:
        st.markdown("**Combined IC+CAL**")
        if comb_best_lm:
            st.metric("Net P&L", fmt_rs(comb_best_lm.get("total_net_pnl", 0)))
            st.metric("Sharpe", f"{comb_best_lm.get('sharpe_ratio', 0):.2f}")
            st.metric("Win Rate", f"{comb_best_lm.get('win_rate', 0):.0%}")
            st.metric("Max DD", f"{comb_best_lm.get('max_drawdown_pct', 0):.1%}")
            st.metric("Trades", comb_best_lm.get("total_trades", 0))
            alloc = f"IC{comb_best_lm.get('ic_allocation_pct', 50)}/CAL{comb_best_lm.get('cal_allocation_pct', 50)}"
            st.caption(f"{alloc} | {comb_best_lm.get('strategy_name', '')}")
        else:
            st.info("No combined sweep data.")

    st.markdown("---")

    # ── Section 4: Paper Trading Log ──────────────────────────────────────
    st.subheader("Paper Trading Log")

    try:
        from db.models import PaperTrade
        from db import engine
        from sqlalchemy.orm import Session as SASession
        from sqlalchemy import select, inspect

        inspector = inspect(engine)
        if inspector.has_table("paper_trades"):
            with SASession(engine) as session:
                trades_q = session.execute(
                    select(PaperTrade).order_by(PaperTrade.date.desc()).limit(20)
                ).scalars().all()

            if trades_q:
                pt_rows = []
                for pt in trades_q:
                    pt_rows.append({
                        "Date": pt.date.strftime("%Y-%m-%d %H:%M") if pt.date else "",
                        "Symbol": pt.symbol or "",
                        "Strategy": pt.strategy or "",
                        "Action": pt.action or "",
                        "Credit": fmt_rs(pt.credit_collected) if pt.credit_collected else "-",
                        "Debit": fmt_rs(pt.debit_paid) if pt.debit_paid else "-",
                        "P&L": fmt_rs(pt.realised_pnl) if pt.realised_pnl is not None else "-",
                        "Status": pt.status or "",
                        "Trigger": pt.trigger or "",
                    })
                st.dataframe(pd.DataFrame(pt_rows), use_container_width=True, hide_index=True)
                st.caption(f"Showing last {len(pt_rows)} paper trades")
            else:
                st.info("Paper trading table exists but has no trades yet. "
                        "Run the paper trading module to log simulated entries.")
        else:
            st.info("Paper trading not yet started. "
                    "The `paper_trades` table will be created when the paper trading module runs.")
    except Exception as e:
        st.info(f"Paper trading not yet started. ({type(e).__name__}: {e})")


# ── Active data source (switches based on sidebar toggle) ────────────────────
active_ic = ic_real if use_real and ic_real else ic_data
active_cal = cal_real if use_real and cal_real else cal_data
active_combined = combined_data if not use_real else None  # no combined for real yet
data_label = "Real NSE 2024" if use_real else "Synthetic (baseline)"


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Overview
# ════════════════════════════════════════════════════════════════════════════

elif page == "Overview":
    st.header("Overview")

    # ── Status Banner ──
    if use_real:
        st.success(f"**Data: Real NSE 2024** — 245 trading days, actual option prices from bhavcopy.")
    else:
        st.info("**Data: Synthetic baseline** (seed=42, 400 days, Jun 2022 — Dec 2023).")

    # ── Strategy Comparison ──
    ic_best = best_config(active_ic, slippage) if active_ic else None
    cal_best = best_config(active_cal, slippage) if active_cal else None
    comb_best = best_config(active_combined, slippage) if active_combined else None

    st.subheader("Best Configs Compared")

    def row(name, r):
        if not r: return None
        pnl = r.get("total_net_pnl", 0)
        return {
            "Strategy": name,
            "Config": r.get("strategy_name", ""),
            "Net P&L": fmt_rs(pnl),
            "Combined": fmt_rs(pnl + PARKED_CAPITAL_ANNUAL_INCOME),
            "ROI": f"{(pnl + PARKED_CAPITAL_ANNUAL_INCOME) / CAPITAL * 100:.1f}%",
            "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
            "Win Rate": f"{r.get('win_rate', 0):.0%}",
            "Max DD": f"{r.get('max_drawdown_pct', 0):.1%}",
            "Trades": r.get("total_trades", 0),
            "PF": f"{r.get('profit_factor', 0):.2f}",
        }

    rows = [r for r in [row("IC", ic_best), row("CAL", cal_best), row("Combined", comb_best)] if r]
    if rows:
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    st.caption(f"Slippage: {slippage} | Combined = Trading P&L + Parked {fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)}/yr")

    # ── Best Combined ──
    if comb_best:
        st.markdown("---")
        st.subheader("Best Combined Strategy")
        render_metrics_row(comb_best)

        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(comb_best.get("trades", [])), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(comb_best.get("trades", [])), use_container_width=True)

    # ── Phase 6 Projected Metrics ──
    st.markdown("---")
    st.subheader("Projected Metrics (targets after re-sweep)")
    st.caption("Conservative estimates based on v2 code changes. Real data re-sweep will validate.")

    proj = pd.DataFrame([
        {"Phase": "Baseline (current)", "ROI Total": "5.9%", "ROI Active": "11.5%", "Sharpe": "1.97", "Max DD": "1.8%", "Win Rate": "71%", "Trades/yr": 34, "Monthly Rs": "3,688"},
        {"Phase": "Phase 1 — gates relaxed", "ROI Total": "8.5%", "ROI Active": "13.0%", "Sharpe": "1.85", "Max DD": "3.2%", "Win Rate": "72%", "Trades/yr": 55, "Monthly Rs": "5,313"},
        {"Phase": "Phase 2 — v2 adjustments", "ROI Total": "11.5%", "ROI Active": "16.0%", "Sharpe": "2.10", "Max DD": "4.5%", "Win Rate": "78%", "Trades/yr": 60, "Monthly Rs": "7,188"},
        {"Phase": "Phase 3 — BankNifty", "ROI Total": "15.5%", "ROI Active": "19.5%", "Sharpe": "2.05", "Max DD": "7.0%", "Win Rate": "75%", "Trades/yr": 90, "Monthly Rs": "9,688"},
        {"Phase": "Phase 4 — compounding", "ROI Total": "18.0%", "ROI Active": "21.0%", "Sharpe": "2.00", "Max DD": "7.5%", "Win Rate": "75%", "Trades/yr": 100, "Monthly Rs": "11,250"},
    ])
    st.dataframe(proj, use_container_width=True, hide_index=True)
    st.caption("ROI Total = (trading P&L + parked yield) / Rs 7.5L. ROI Active = trading P&L / deployed capital only.")

    # ── Capital ──
    st.markdown("---")
    with st.expander("Capital Structure"):
        rows = []
        for key, amount in CAPITAL_STRUCTURE.items():
            yld = PARKED_YIELD.get(key)
            rows.append({
                "Bucket": key.replace("_", " ").title(),
                "Amount": fmt_rs(amount),
                "Yield": f"{yld:.1%}" if yld else "Deployed",
                "Annual": fmt_rs(amount * yld) if yld else "-",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Total parked income: {fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)}/yr ({PARKED_CAPITAL_ANNUAL_INCOME/CAPITAL*100:.1f}% of capital)")

    # ── What the sweep actually used ──
    with st.expander("Sweep Parameters (what produced these results)"):
        st.markdown("""
**Data:** Synthetic option chains from Nifty 50 spot prices (Jun 2022 — Dec 2023, 400 days, seed=42)

**IC Sweep** (243 combos x 3 slippage = 729):
- Short delta: 0.16, 0.20, 0.25
- Wing width: 400, 500, 600 pts (fixed per config)
- Profit target: 40%, 50%, 65%
- Stop loss: 1.5x, 2.0x, 2.5x
- Time stop: 18, 21, 25 DTE
- IV Rank min: 30 (fixed), VIX max: 25 (fixed)

**CAL Sweep** (243 combos x 3 slippage = 729):
- Adjust threshold: 1.5%, 2.0%, 2.5%
- Close threshold: 3%, 4%, 5%
- Profit target: 40%, 50%, 60%
- Back close DTE: 22, 25, 28
- Max VIX: 25, 28, 32

**Combined** (375 blends): Top 5 IC x Top 5 CAL x 5 allocation splits x 3 slippage
        """)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Iron Condor
# ════════════════════════════════════════════════════════════════════════════

elif page == "Iron Condor":
    st.header("Iron Condor")

    if not active_ic:
        st.error("No IC data.")
        st.stop()

    results = active_ic.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} configs | {slippage} slippage | "
               f"Sweep params: IVR>=30, VIX<=25, wings 400-600")

    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    tab1, tab2, tab3 = st.tabs(["Best Config", "All Configs", "Parameters"])

    with tab1:
        st.subheader(f"`{best.get('strategy_name', '')}`")

        # Show actual params from the sweep
        params = best.get("params", {})
        with st.expander("Configuration Parameters (from sweep)"):
            pcols = st.columns(6)
            for i, (k, v) in enumerate([(k, v) for k, v in params.items()
                                         if k in ("short_delta", "wing_width", "profit_target_pct",
                                                   "stop_loss_multiplier", "time_stop_dte", "min_iv_rank")]):
                label = k.replace("_", " ").title()
                if isinstance(v, float) and v < 1:
                    pcols[i].metric(label, f"{v:.0%}")
                else:
                    pcols[i].metric(label, v)

        render_metrics_row(best)

        # Charts
        trades = best.get("trades", [])
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(trades), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(trades), use_container_width=True)

        # Trade P&L bars
        if trades:
            pnls = [t.get("net_pnl", 0) for t in trades]
            fig = go.Figure(go.Bar(
                x=list(range(1, len(trades) + 1)), y=pnls,
                marker_color=[pnl_color(p) for p in pnls],
                hovertemplate="Trade %{x}: Rs %{y:,.0f}<br>%{customdata}<extra></extra>",
                customdata=[t.get("exit_type", "") for t in trades],
            ))
            fig.update_layout(height=240, margin=dict(t=10, b=30, l=50, r=10),
                              xaxis_title="Trade #", yaxis_title="P&L (Rs)", yaxis=dict(tickformat=","))
            st.markdown("**Trade-by-Trade P&L**")
            st.plotly_chart(fig, use_container_width=True)

        # Adjustments
        st.markdown("---")
        st.subheader("Adjustment Analysis")
        render_adjustment_analysis(trades)

        # All trades
        st.markdown("---")
        st.subheader("All Trades")
        render_trades_table(trades, "IC")

    with tab2:
        st.subheader("Top 50 Configurations")
        rows = []
        for i, r in enumerate(filtered[:50]):
            pnl = r.get("total_net_pnl", 0)
            rows.append({
                "#": i + 1, "Config": r.get("strategy_name", ""),
                "P&L": fmt_rs(pnl), "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
                "Sortino": f"{r.get('sortino_ratio', 0):.2f}",
                "WR": f"{r.get('win_rate', 0):.0%}", "DD": f"{r.get('max_drawdown_pct', 0):.1%}",
                "Trades": r.get("total_trades", 0), "PF": f"{r.get('profit_factor', 0):.2f}",
                "Avg P&L": fmt_rs(r.get("avg_trade_pnl", 0)),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=500)

        c1, c2 = st.columns(2)
        with c1:
            fig = px.histogram(x=[r.get("sharpe_ratio", 0) for r in filtered], nbins=30,
                               title="Sharpe Distribution", labels={"x": "Sharpe", "y": "Count"})
            fig.add_vline(x=0, line_dash="dash", line_color="red")
            fig.update_layout(height=280, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.histogram(x=[r.get("total_net_pnl", 0) / 1000 for r in filtered], nbins=30,
                               title="P&L Distribution", labels={"x": "P&L (Rs '000)", "y": "Count"})
            fig.add_vline(x=0, line_dash="dash", line_color="red")
            fig.update_layout(height=280, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    with tab3:
        st.subheader("Parameter Impact on Sharpe")
        param_map = {
            "short_delta": "Short Delta", "wing_width": "Wing Width",
            "profit_target_pct": "Profit Target", "stop_loss_multiplier": "Stop Loss (x)",
            "time_stop_dte": "Time Stop (DTE)",
        }
        param_data = []
        for r in filtered:
            p = r.get("params", {})
            row = {"sharpe": r.get("sharpe_ratio", 0)}
            for k in param_map:
                row[k] = p.get(k, 0)
            param_data.append(row)

        if param_data:
            pdf = pd.DataFrame(param_data)
            cols = st.columns(2)
            for i, (k, label) in enumerate(param_map.items()):
                if pdf[k].nunique() <= 1:
                    continue
                with cols[i % 2]:
                    fig = px.box(pdf, x=k, y="sharpe", title=label,
                                 labels={"sharpe": "Sharpe", k: ""})
                    fig.update_layout(height=280, margin=dict(t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Calendar Spread
# ════════════════════════════════════════════════════════════════════════════

elif page == "Calendar Spread":
    st.header("Calendar Spread")

    if not active_cal:
        st.error("No CAL data.")
        st.stop()

    results = active_cal.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    st.caption(f"{len(filtered)} configs | {slippage} slippage | {data_label}")

    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    tab1, tab2, tab3 = st.tabs(["Best Config", "All Configs", "Parameters"])

    with tab1:
        st.subheader(f"`{best.get('strategy_name', '')}`")

        params = best.get("params", {})
        with st.expander("Configuration Parameters (from sweep)"):
            pcols = st.columns(6)
            display_keys = ["move_pct_to_adjust", "move_pct_to_close", "profit_target_pct",
                            "back_month_close_dte", "max_vix", "front_roll_dte"]
            for i, k in enumerate(display_keys):
                v = params.get(k, 0)
                label = k.replace("_", " ").title()
                if isinstance(v, float) and v < 1:
                    pcols[i].metric(label, f"{v:.1%}")
                else:
                    pcols[i].metric(label, v)

        render_metrics_row(best)

        trades = best.get("trades", [])
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Equity Curve**")
            st.plotly_chart(make_equity_curve(trades), use_container_width=True)
        with col2:
            st.markdown("**Drawdown**")
            st.plotly_chart(make_drawdown_chart(trades), use_container_width=True)

        if trades:
            pnls = [t.get("net_pnl", 0) for t in trades]
            fig = go.Figure(go.Bar(
                x=list(range(1, len(trades) + 1)), y=pnls,
                marker_color=[pnl_color(p) for p in pnls],
            ))
            fig.update_layout(height=240, margin=dict(t=10, b=30, l=50, r=10),
                              xaxis_title="Trade #", yaxis_title="P&L (Rs)", yaxis=dict(tickformat=","))
            st.markdown("**Trade-by-Trade P&L**")
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.subheader("Adjustment Analysis")
        render_adjustment_analysis(trades)

        st.markdown("---")
        st.subheader("All Trades")
        render_trades_table(trades, "CAL")

    with tab2:
        st.subheader("Top 50 Configurations")
        rows = []
        for i, r in enumerate(filtered[:50]):
            pnl = r.get("total_net_pnl", 0)
            rows.append({
                "#": i + 1, "Config": r.get("strategy_name", ""),
                "P&L": fmt_rs(pnl), "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
                "WR": f"{r.get('win_rate', 0):.0%}", "DD": f"{r.get('max_drawdown_pct', 0):.1%}",
                "Trades": r.get("total_trades", 0), "PF": f"{r.get('profit_factor', 0):.2f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=500)

    with tab3:
        st.subheader("Parameter Impact on Sharpe")
        param_map = {
            "move_pct_to_adjust": "Adj Threshold", "move_pct_to_close": "Close Threshold",
            "profit_target_pct": "Profit Target", "back_month_close_dte": "Back Close DTE",
            "max_vix": "Max VIX",
        }
        param_data = []
        for r in filtered:
            p = r.get("params", {})
            row = {"sharpe": r.get("sharpe_ratio", 0)}
            for k in param_map:
                row[k] = p.get(k, 0)
            param_data.append(row)

        if param_data:
            pdf = pd.DataFrame(param_data)
            cols = st.columns(2)
            for i, (k, label) in enumerate(param_map.items()):
                if pdf[k].nunique() <= 1:
                    continue
                with cols[i % 2]:
                    fig = px.box(pdf, x=k, y="sharpe", title=label,
                                 labels={"sharpe": "Sharpe", k: ""})
                    fig.update_layout(height=280, margin=dict(t=40, b=20))
                    st.plotly_chart(fig, use_container_width=True)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Combined IC+CAL
# ════════════════════════════════════════════════════════════════════════════

elif page == "Combined IC+CAL":
    st.header("Combined IC + CAL")

    if not combined_data:
        st.error("No combined data.")
        st.stop()

    results = combined_data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)
    best = filtered[0] if filtered else None
    if not best:
        st.stop()

    profitable = sum(1 for r in filtered if r.get("total_net_pnl", 0) > 0)
    st.caption(f"{len(filtered)} blends | {profitable}/{len(filtered)} profitable | {slippage} slippage")

    st.subheader(f"Best: IC {best.get('ic_allocation_pct', 50)}% / CAL {best.get('cal_allocation_pct', 50)}%")
    render_metrics_row(best)

    # Extra combined metrics
    c1, c2, c3 = st.columns(3)
    c1.metric("IC Trades", best.get("ic_trades", 0))
    c2.metric("CAL Trades", best.get("cal_trades", 0))
    c3.metric("Allocation", f"IC{best.get('ic_allocation_pct', 50)}/CAL{best.get('cal_allocation_pct', 50)}")

    trades = best.get("trades", [])
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Equity Curve**")
        st.plotly_chart(make_equity_curve(trades), use_container_width=True)
    with col2:
        st.markdown("**Income Sources**")
        if trades:
            ic_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "IC")
            cal_pnl = sum(t["net_pnl"] for t in trades if t.get("strategy") == "CAL")
            fig = go.Figure(go.Pie(
                labels=["IC Trading", "CAL Trading", "Parked Capital"],
                values=[max(0, ic_pnl), max(0, cal_pnl), PARKED_CAPITAL_ANNUAL_INCOME],
                hole=0.45, marker_colors=["#3b82f6", "#8b5cf6", "#22c55e"],
                textinfo="label+value", texttemplate="%{label}<br>Rs %{value:,.0f}",
            ))
            fig.update_layout(height=320, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # Trade bars by strategy
    if trades:
        pnls = [t.get("net_pnl", 0) for t in trades]
        colors = ["#3b82f6" if t.get("strategy") == "IC" else "#8b5cf6" for t in trades]
        fig = go.Figure(go.Bar(
            x=list(range(1, len(trades) + 1)), y=pnls, marker_color=colors,
            hovertemplate="Trade %{x}: Rs %{y:,.0f} (%{customdata})<extra></extra>",
            customdata=[t.get("strategy", "") for t in trades],
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="gray")
        fig.update_layout(height=240, margin=dict(t=10, b=30, l=50, r=10),
                          xaxis_title="Trade #", yaxis_title="P&L", yaxis=dict(tickformat=","))
        st.markdown("**Trade P&L (blue=IC, purple=CAL)**")
        st.plotly_chart(fig, use_container_width=True)

    # Allocation analysis
    st.markdown("---")
    st.subheader("Allocation Impact")
    adf = pd.DataFrame([{
        "split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
        "sharpe": r.get("sharpe_ratio", 0),
        "max_dd": r.get("max_drawdown_pct", 0) * 100,
        "net_pnl": r.get("total_net_pnl", 0),
    } for r in filtered])

    if not adf.empty:
        c1, c2 = st.columns(2)
        with c1:
            fig = px.box(adf, x="split", y="sharpe", title="Sharpe by Allocation",
                         labels={"sharpe": "Sharpe", "split": ""})
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            fig = px.scatter(adf, x="max_dd", y="sharpe", color="split",
                             title="Risk vs Return", labels={"max_dd": "Max DD (%)", "sharpe": "Sharpe"})
            fig.update_layout(height=300, margin=dict(t=40, b=20))
            st.plotly_chart(fig, use_container_width=True)

    # Top 10
    st.markdown("---")
    st.subheader("Top 10")
    rows = []
    for i, r in enumerate(filtered[:10]):
        pnl = r.get("total_net_pnl", 0)
        rows.append({
            "#": i + 1,
            "IC": r.get("ic_config", ""), "CAL": r.get("cal_config", ""),
            "Split": f"IC{r.get('ic_allocation_pct', 50)}/CAL{r.get('cal_allocation_pct', 50)}",
            "P&L": fmt_rs(pnl), "Sharpe": f"{r.get('sharpe_ratio', 0):.2f}",
            "WR": f"{r.get('win_rate', 0):.0%}", "DD": f"{r.get('max_drawdown_pct', 0):.1%}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Adjustments
    st.markdown("---")
    st.subheader("Adjustment Analysis")
    render_adjustment_analysis(trades)


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Risk & Statistics
# ════════════════════════════════════════════════════════════════════════════

elif page == "Risk & Statistics":
    st.header("Risk & Statistical Validation")
    st.caption("Bootstrap CI, Monte Carlo simulation, walk-forward testing, regime analysis")

    if active_ic:
        st.subheader("Iron Condor")
        render_stats_section(active_ic, "IC")
    if active_cal:
        st.subheader("Calendar Spread")
        render_stats_section(active_cal, "CAL")


# ════════════════════════════════════════════════════════════════════════════
# PAGE: Trade Explorer
# ════════════════════════════════════════════════════════════════════════════

elif page == "Trade Explorer":
    st.header("Trade Explorer")
    st.caption("Drill into every trade from any configuration")

    strat = st.selectbox("Strategy", ["Iron Condor", "Calendar Spread", "Combined"])
    data = {"Iron Condor": active_ic, "Calendar Spread": active_cal, "Combined": active_combined}[strat]

    if not data:
        st.error("No data.")
        st.stop()

    results = data.get("results", [])
    filtered = [r for r in results if r.get("slippage_model") == slippage]
    filtered.sort(key=lambda r: r.get("sharpe_ratio", 0), reverse=True)

    names = [r.get("strategy_name", "") for r in filtered[:30]]
    selected_name = st.selectbox("Configuration", names)
    selected = next((r for r in filtered if r.get("strategy_name") == selected_name), None)

    if not selected:
        st.stop()

    trades = selected.get("trades", [])
    if not trades:
        st.info("No trades.")
        st.stop()

    st.markdown(f"**{len(trades)} trades** | P&L: {fmt_rs(selected.get('total_net_pnl', 0))} | "
                f"Sharpe: {selected.get('sharpe_ratio', 0):.2f} | WR: {selected.get('win_rate', 0):.0%}")

    c1, c2 = st.columns(2)
    with c1:
        exits = pd.Series([t.get("exit_type", "?") for t in trades]).value_counts()
        fig = px.pie(values=exits.values, names=exits.index, title="Exit Reasons", hole=0.4)
        fig.update_layout(height=280, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.histogram(x=[t.get("holding_days", 0) for t in trades], nbins=15,
                           title="Holding Period", labels={"x": "Days", "y": "Count"})
        fig.update_layout(height=280, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    for i, t in enumerate(trades):
        meta = t.get("metadata", {})
        pnl = t.get("net_pnl", 0)
        adj = t.get("adjustment_count", 0)
        color = "green" if pnl > 0 else "red"

        label = (f"Trade {i+1}: :{color}[{fmt_rs(pnl)}] | "
                 f"{t.get('entry_date', '')[:10]} to {t.get('exit_date', '')[:10]} | "
                 f"{t.get('exit_type', '')} | {t.get('holding_days', 0)}d"
                 + (f" | {adj} adj" if adj else ""))

        with st.expander(label):
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("Gross P&L", fmt_rs(t.get("gross_pnl", 0)))
            c2.metric("Costs", fmt_rs(t.get("total_costs", 0)))
            c3.metric("Net P&L", fmt_rs(pnl))
            c4.metric("Entry Premium", f"{t.get('net_premium_per_unit', 0):.1f}")
            c5.metric("Close Cost", f"{t.get('close_cost_per_unit', 0):.1f}")
            c6.metric("Days", t.get("holding_days", 0))

            if adj > 0:
                st.markdown(f"**Adjustments:** {adj} | "
                            f"Cost: {fmt_rs(t.get('adjustment_costs', 0))} | "
                            f"P&L: {fmt_rs(t.get('adjustment_pnl', 0))}")

            if meta:
                st.markdown("**Entry Conditions:**")
                st.json({k: v for k, v in meta.items() if k != "adjustment_count"})


# ── Footer ───────────────────────────────────────────────────────────────────
st.markdown("---")
st.caption(f"Quant Dashboard v2.0 | Baseline sweep (synthetic, seed=42) | "
           f"Capital: {fmt_rs(TOTAL_CAPITAL)} | Parked: {fmt_rs(PARKED_CAPITAL_ANNUAL_INCOME)}/yr")
