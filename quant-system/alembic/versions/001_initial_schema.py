"""Initial schema — all 6 tables

Revision ID: 001
Revises:
Create Date: 2026-03-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_code", sa.String(), unique=True, nullable=False),
        sa.Column("strategy", sa.String(), nullable=False),
        sa.Column("underlying", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("entry_date", sa.DateTime(), nullable=False),
        sa.Column("expiry_date", sa.DateTime(), nullable=False),
        sa.Column("short_strike_1", sa.Integer()),
        sa.Column("short_strike_2", sa.Integer()),
        sa.Column("long_strike_1", sa.Integer()),
        sa.Column("long_strike_2", sa.Integer()),
        sa.Column("iv_rank_at_entry", sa.Float()),
        sa.Column("india_vix_at_entry", sa.Float()),
        sa.Column("entry_premium_per_unit", sa.Float()),
        sa.Column("net_premium_per_unit", sa.Float()),
        sa.Column("lots", sa.Integer(), server_default="1"),
        sa.Column("market_regime", sa.String()),
        sa.Column("exit_date", sa.DateTime(), nullable=True),
        sa.Column("exit_reason", sa.String(), nullable=True),
        sa.Column("exit_price_per_unit", sa.Float(), nullable=True),
        sa.Column("gross_pnl", sa.Float(), nullable=True),
        sa.Column("net_pnl", sa.Float(), nullable=True),
        sa.Column("days_in_trade", sa.Integer(), nullable=True),
        sa.Column("brokerage_paid", sa.Float(), nullable=True),
        sa.Column("stt_paid", sa.Float(), nullable=True),
        sa.Column("slippage_estimate", sa.Float(), nullable=True),
        sa.Column("total_costs", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
    )

    op.create_table(
        "calendar_cycles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("front_month_expiry", sa.DateTime(), nullable=False),
        sa.Column("premium_collected", sa.Float(), nullable=False),
        sa.Column("exit_date", sa.DateTime(), nullable=True),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("cycle_pnl", sa.Float(), nullable=True),
    )

    op.create_table(
        "edge_metrics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_date", sa.DateTime(), nullable=False),
        sa.Column("rolling_win_rate_20", sa.Float()),
        sa.Column("rolling_profit_factor_20", sa.Float()),
        sa.Column("total_trades_all_time", sa.Integer()),
        sa.Column("ytd_net_pnl", sa.Float()),
        sa.Column("regime_sideways_win_rate", sa.Float(), nullable=True),
        sa.Column("regime_trending_win_rate", sa.Float(), nullable=True),
        sa.Column("regime_highvol_win_rate", sa.Float(), nullable=True),
    )

    op.create_table(
        "order_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trade_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("zerodha_order_id", sa.String(), nullable=True),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("transaction_type", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("fill_price", sa.Float(), nullable=True),
        sa.Column("slippage_actual", sa.Float(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("error_message", sa.String(), nullable=True),
    )

    op.create_table(
        "zerodha_sessions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), unique=True, nullable=False),
        sa.Column("access_token", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "alert_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("alert_type", sa.String(), nullable=False),
        sa.Column("urgency", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("position_id", sa.Integer(), sa.ForeignKey("trades.id"), nullable=True),
        sa.Column("acknowledged", sa.Boolean(), server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("alert_log")
    op.drop_table("zerodha_sessions")
    op.drop_table("order_log")
    op.drop_table("edge_metrics")
    op.drop_table("calendar_cycles")
    op.drop_table("trades")
