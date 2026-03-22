"""Add paper_trades table

Revision ID: 002
Revises: 001
Create Date: 2026-03-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper_trades",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.DateTime(), nullable=False),
        sa.Column("symbol", sa.String(20), server_default="NIFTY"),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("strategy", sa.String(20), nullable=False),
        sa.Column("legs_json", sa.Text(), nullable=True),
        sa.Column("credit_collected", sa.Float(), server_default="0.0"),
        sa.Column("debit_paid", sa.Float(), server_default="0.0"),
        sa.Column("exit_date", sa.DateTime(), nullable=True),
        sa.Column("exit_credit", sa.Float(), nullable=True),
        sa.Column("realised_pnl", sa.Float(), nullable=True),
        sa.Column("slippage_actual", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="open"),
        sa.Column("trigger", sa.String(50), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("paper_trades")
