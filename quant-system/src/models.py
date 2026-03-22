"""Shared dataclasses for signals, trade structures, and results."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class EntrySignal:
    should_enter: bool
    reason: str
    blocking_conditions: list = field(default_factory=list)
    gate_results: list = field(default_factory=list)


@dataclass
class ExitSignal:
    should_exit: bool
    exit_type: str  # STOP_LOSS / TIME_STOP / PROFIT_TARGET / NONE
    urgency: str    # IMMEDIATE / TODAY / MONITOR
    message: str


@dataclass
class TradeStructure:
    strategy: str  # "IC"
    underlying: str
    expiry_date: datetime

    short_call_strike: int
    short_put_strike: int
    long_call_strike: int
    long_put_strike: int

    short_call_premium: float
    short_put_premium: float
    long_call_premium: float
    long_put_premium: float

    net_premium: float
    max_profit_per_lot: float
    max_loss_per_lot: float
    profit_target_close_price: float
    stop_loss_close_price: float

    lots: int = 1


@dataclass
class CalendarTradeStructure:
    strategy: str  # "CAL"
    underlying: str
    strike: int

    back_month_expiry: datetime
    front_month_expiry: datetime

    back_month_cost: float
    front_month_premium: float
    net_debit: float
    max_loss_per_lot: float

    lots: int = 1


@dataclass
class RollSignal:
    should_roll: bool
    action: str  # ROLL_FRONT / CLOSE_BACK_MONTH / HARVEST_AND_CLOSE / NONE
    message: str


@dataclass
class AdjustmentSignal:
    should_adjust: bool
    action: str      # CLOSE / CENTRE / NONE
    urgency: str     # IMMEDIATE / TODAY / MONITOR
    message: str


@dataclass
class GateResult:
    gate_name: str
    passed: bool
    current_value: str
    threshold: str
    message: str


# --- Generic Backtesting Models ---

@dataclass
class Leg:
    """A single option leg in a multi-leg position."""
    strike: int
    option_type: str    # "CE" or "PE"
    side: str           # "BUY" or "SELL"
    premium: float      # execution price per unit
    expiry_date: datetime
    bid: float = 0.0
    ask: float = 0.0
    iv: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0


@dataclass
class Position:
    """An open multi-leg options position being tracked by the backtester."""
    position_id: str
    strategy_name: str
    entry_date: datetime
    legs: list[Leg]
    lots: int = 1
    lot_size: int = 25
    net_premium_per_unit: float = 0.0   # + for credit, - for debit
    margin_required: float = 0.0
    metadata: dict = field(default_factory=dict)  # strategy-specific data
    adjustment_count: int = 0
    adjustment_costs: float = 0.0
    adjustment_history: list = field(default_factory=list)


@dataclass
class MarketState:
    """Snapshot of market conditions on a given day for the backtester."""
    date: datetime
    underlying_price: float
    india_vix: float
    iv_rank: float = 0.0
    option_chain: dict = field(default_factory=dict)
    expiry_dates: list = field(default_factory=list)


@dataclass
class EntryDecision:
    """Strategy's decision on whether to enter a new position."""
    should_enter: bool
    legs: list[Leg] = field(default_factory=list)
    net_premium_per_unit: float = 0.0
    margin_required: float = 0.0
    reason: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class ExitDecision:
    """Strategy's decision on whether to exit an existing position."""
    should_exit: bool
    exit_type: str = "NONE"     # STOP_LOSS / TIME_STOP / PROFIT_TARGET / ADJUSTMENT / EXPIRY / NONE
    urgency: str = "MONITOR"    # IMMEDIATE / TODAY / MONITOR
    reason: str = ""
    current_close_cost: float = 0.0
    exit_legs: list[Leg] = field(default_factory=list)


@dataclass
class AdjustmentDecision:
    """Strategy's decision on mid-trade adjustments (rolls, recentres, etc.)."""
    should_adjust: bool
    action: str = "NONE"
    close_legs: list[Leg] = field(default_factory=list)
    new_legs: list[Leg] = field(default_factory=list)
    reason: str = ""
    new_premium_per_unit: float = 0.0
    new_margin_required: float = 0.0
    close_cost: float = 0.0


@dataclass
class TradeResult:
    """Result of a single completed trade in the backtest."""
    position_id: str
    strategy_name: str
    entry_date: datetime
    exit_date: datetime
    entry_legs: list[Leg]
    exit_legs: list[Leg]
    lots: int
    lot_size: int
    net_premium_per_unit: float     # collected/paid at entry
    close_cost_per_unit: float      # cost to close at exit
    gross_pnl: float                # before costs
    total_costs: float              # all transaction + slippage costs
    net_pnl: float                  # gross_pnl - total_costs
    exit_type: str
    holding_days: int
    margin_required: float = 0.0
    max_drawdown_during_trade: float = 0.0
    metadata: dict = field(default_factory=dict)
    adjustment_count: int = 0
    adjustment_costs: float = 0.0
    adjustment_pnl: float = 0.0


@dataclass
class BacktestResult:
    """Aggregate result of a full backtest run."""
    strategy_name: str
    params: dict
    slippage_model: str
    start_date: datetime
    end_date: datetime
    trades: list[TradeResult]
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_gross_pnl: float = 0.0
    total_costs: float = 0.0
    total_net_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_trade_pnl: float = 0.0
    avg_winner: float = 0.0
    avg_loser: float = 0.0
    avg_holding_days: float = 0.0
    annual_return_pct: float = 0.0
    calmar_ratio: float = 0.0
    total_margin_cost: float = 0.0
    capital_used: float = 0.0
