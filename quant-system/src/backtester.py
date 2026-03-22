"""
Generic Backtesting Engine — strategy-agnostic day-by-day simulator.

Feeds daily MarketState snapshots to any BacktestStrategy adapter,
tracks positions, applies transaction costs via CostEngine, and
produces a BacktestResult with full trade-by-trade detail.

Key design goals:
  - Strategy-agnostic: works with any adapter implementing BacktestStrategy protocol
  - Cost-accurate: every trade goes through CostEngine (brokerage, STT, slippage, etc.)
  - No lookahead: each day only sees data up to that day
  - Daily P&L tracking: for drawdown and equity curve calculation
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from src.cost_engine import CostEngine, LegCostInput, SlippageModel
from src.models import (
    BacktestResult, EntryDecision, ExitDecision, Leg, MarketState,
    Position, TradeResult,
)
from src.strategy_protocol import BacktestStrategy

logger = logging.getLogger(__name__)


@dataclass
class DailySnapshot:
    """Daily P&L snapshot for equity curve construction."""
    date: datetime
    open_positions: int
    daily_pnl: float
    cumulative_pnl: float
    drawdown: float
    drawdown_pct: float


class Backtester:
    """
    Generic day-by-day options backtesting engine.

    Usage:
        engine = Backtester(strategy=my_adapter, cost_engine=CostEngine())
        result = engine.run(daily_states)
    """

    def __init__(
        self,
        strategy: BacktestStrategy,
        cost_engine: CostEngine | None = None,
        capital: float = 750000.0,
        max_open_positions: int = 2,
    ):
        self.strategy = strategy
        self.cost_engine = cost_engine or CostEngine()
        self.capital = capital
        self.max_open_positions = max_open_positions

        # State
        self.open_positions: list[Position] = []
        self.completed_trades: list[TradeResult] = []
        self.daily_snapshots: list[DailySnapshot] = []
        self._peak_equity = capital
        self._cumulative_pnl = 0.0
        self._trade_counter = 0

    def run(self, daily_states: list[MarketState]) -> BacktestResult:
        """
        Run the full backtest over a sequence of daily market states.

        Each state represents one trading day with its option chain,
        underlying price, VIX, etc.
        """
        if not daily_states:
            return self._empty_result()

        for state in daily_states:
            self._process_day(state)

        return self._compile_result(daily_states[0].date, daily_states[-1].date)

    def _process_day(self, state: MarketState):
        """Process a single trading day."""
        daily_pnl = 0.0

        # 1. Check exits on open positions (iterate copy to allow removal)
        positions_to_close = []
        for pos in list(self.open_positions):
            exit_decision = self.strategy.should_exit(pos, state)
            if exit_decision.should_exit:
                positions_to_close.append((pos, exit_decision))

        for pos, exit_d in positions_to_close:
            trade_result = self._close_position(pos, exit_d, state)
            daily_pnl += trade_result.net_pnl

        # 2. Check adjustments on remaining open positions
        for pos in list(self.open_positions):
            adj = self.strategy.should_adjust(pos, state)
            if adj.should_adjust:
                adj_pnl = self._execute_adjustment(pos, adj, state)
                daily_pnl += adj_pnl

        # 3. Check for new entries
        if len(self.open_positions) < self.max_open_positions:
            if self.strategy.should_enter(state):
                entry = self.strategy.generate_entry(state)
                if entry.should_enter:
                    self._open_position(entry, state)

        # 4. Track daily unrealised P&L for drawdown
        unrealised = 0.0
        for pos in self.open_positions:
            close_cost = self.strategy.reprice_position(pos, state)
            if pos.net_premium_per_unit > 0:  # credit strategy
                unrealised += (pos.net_premium_per_unit - close_cost) * pos.lot_size * pos.lots
            else:  # debit strategy
                current_value = abs(close_cost)
                entry_debit = abs(pos.net_premium_per_unit)
                unrealised += (current_value - entry_debit) * pos.lot_size * pos.lots

        self._cumulative_pnl += daily_pnl
        total_equity = self.capital + self._cumulative_pnl + unrealised
        self._peak_equity = max(self._peak_equity, total_equity)
        drawdown = self._peak_equity - total_equity
        drawdown_pct = drawdown / self._peak_equity if self._peak_equity > 0 else 0

        self.daily_snapshots.append(DailySnapshot(
            date=state.date,
            open_positions=len(self.open_positions),
            daily_pnl=daily_pnl,
            cumulative_pnl=self._cumulative_pnl,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
        ))

    def _open_position(self, entry: EntryDecision, state: MarketState):
        """Create a new open position from an entry decision."""
        self._trade_counter += 1
        pos_id = f"{self.strategy.name}_{self._trade_counter:04d}"

        lot_size = entry.metadata.get("lot_size", 25)

        # Position sizing: max 5% of capital at risk per trade
        max_risk_per_trade = self.capital * 0.05
        if entry.margin_required > 0:
            lots = max(1, int(max_risk_per_trade / entry.margin_required))
        else:
            lots = 1

        # Also cap by available margin (active trading capital = 40% of total)
        active_capital = self.capital * 0.40
        margin_in_use = sum(p.margin_required * p.lots for p in self.open_positions)
        available = active_capital - margin_in_use
        if entry.margin_required > 0:
            lots = min(lots, max(1, int(available / entry.margin_required)))

        pos = Position(
            position_id=pos_id,
            strategy_name=self.strategy.name,
            entry_date=state.date,
            legs=entry.legs,
            lots=lots,
            lot_size=lot_size,
            net_premium_per_unit=entry.net_premium_per_unit,
            margin_required=entry.margin_required,
            metadata=entry.metadata,
        )
        self.open_positions.append(pos)
        logger.debug("Opened %s on %s: %d lots, premium=%.2f", pos_id, state.date, lots, entry.net_premium_per_unit)

    def _execute_adjustment(self, pos: Position, adj, state: MarketState) -> float:
        """Execute an adjustment: close specified legs, optionally open new legs.

        Returns the net daily P&L impact (realized P&L minus adjustment costs).
        """
        from src.models import AdjustmentDecision, ExitDecision

        logger.info(
            "Executing adjustment for %s: %s — %s",
            pos.position_id, adj.action, adj.reason,
        )

        # If no new_legs, treat as a full close
        if not adj.new_legs:
            exit_d = ExitDecision(
                should_exit=True,
                exit_type=f"ADJUSTMENT_{adj.action}",
                urgency="IMMEDIATE",
                reason=adj.reason,
                current_close_cost=adj.close_cost,
                exit_legs=adj.close_legs,
            )
            trade_result = self._close_position(pos, exit_d, state)
            return trade_result.net_pnl

        # Calculate costs for closing + opening adjustment legs
        adj_cost_legs = []
        for leg in list(adj.close_legs) + list(adj.new_legs):
            adj_cost_legs.append(LegCostInput(
                premium=leg.premium,
                side=leg.side,
                lots=pos.lots,
                lot_size=pos.lot_size,
                bid=leg.bid,
                ask=leg.ask,
            ))

        adj_costs = self.cost_engine.calculate_trade_costs(
            entry_legs=[],
            exit_legs=adj_cost_legs,
            net_premium_per_unit=abs(pos.net_premium_per_unit),
            lot_size=pos.lot_size,
            lots=pos.lots,
            margin_required=0,
            holding_days=0,
        )

        # Realized P&L from closing legs
        realized_pnl = 0.0
        for close_leg in adj.close_legs:
            for entry_leg in pos.legs:
                if entry_leg.strike == close_leg.strike and entry_leg.option_type == close_leg.option_type:
                    if entry_leg.side == "SELL":
                        realized_pnl += (entry_leg.premium - close_leg.premium) * pos.lot_size * pos.lots
                    else:
                        realized_pnl += (close_leg.premium - entry_leg.premium) * pos.lot_size * pos.lots
                    break

        # Update position: remove closed legs, add new legs
        closed_keys = {(cl.strike, cl.option_type) for cl in adj.close_legs}
        remaining_legs = [l for l in pos.legs if (l.strike, l.option_type) not in closed_keys]
        pos.legs = remaining_legs + list(adj.new_legs)

        # Update premium
        if adj.new_premium_per_unit != 0:
            pos.net_premium_per_unit = adj.new_premium_per_unit
        else:
            new_prem = 0.0
            for leg in pos.legs:
                if leg.side == "SELL":
                    new_prem += leg.premium
                else:
                    new_prem -= leg.premium
            pos.net_premium_per_unit = new_prem

        if adj.new_margin_required > 0:
            pos.margin_required = adj.new_margin_required

        # Track adjustment
        adj_cost_total = adj_costs.total_costs
        pos.adjustment_count += 1
        pos.adjustment_costs += adj_cost_total
        pos.adjustment_history.append({
            "date": state.date.isoformat(),
            "action": adj.action,
            "cost": round(adj_cost_total, 2),
            "realized_pnl": round(realized_pnl, 2),
        })
        pos.metadata["adjustment_count"] = pos.adjustment_count

        logger.debug(
            "Adjusted %s: %s, cost=%.2f, realized=%.2f",
            pos.position_id, adj.action, adj_cost_total, realized_pnl,
        )

        return realized_pnl - adj_cost_total

    def _close_position(self, pos: Position, exit_d: ExitDecision, state: MarketState) -> TradeResult:
        """Close a position and calculate P&L including all costs."""
        self.open_positions.remove(pos)

        # Build cost engine legs
        entry_cost_legs = []
        exit_cost_legs = []

        for leg in pos.legs:
            entry_cost_legs.append(LegCostInput(
                premium=leg.premium,
                side=leg.side,
                lots=pos.lots,
                lot_size=pos.lot_size,
                bid=leg.bid,
                ask=leg.ask,
            ))

        for eleg in exit_d.exit_legs:
            exit_cost_legs.append(LegCostInput(
                premium=eleg.premium,
                side=eleg.side,
                lots=pos.lots,
                lot_size=pos.lot_size,
                bid=eleg.bid,
                ask=eleg.ask,
            ))

        # If no exit legs provided, build from close cost
        if not exit_cost_legs:
            close_cost = exit_d.current_close_cost
            for leg in pos.legs:
                exit_side = "BUY" if leg.side == "SELL" else "SELL"
                # Distribute close cost proportionally
                exit_cost_legs.append(LegCostInput(
                    premium=close_cost / len(pos.legs) if len(pos.legs) > 0 else 0,
                    side=exit_side,
                    lots=pos.lots,
                    lot_size=pos.lot_size,
                ))

        holding_days = (state.date - pos.entry_date).days

        costs = self.cost_engine.calculate_trade_costs(
            entry_legs=entry_cost_legs,
            exit_legs=exit_cost_legs,
            net_premium_per_unit=abs(pos.net_premium_per_unit),
            lot_size=pos.lot_size,
            lots=pos.lots,
            margin_required=pos.margin_required,
            holding_days=holding_days,
        )

        # Gross P&L
        if pos.net_premium_per_unit > 0:  # credit strategy (IC)
            gross_pnl = (pos.net_premium_per_unit - exit_d.current_close_cost) * pos.lot_size * pos.lots
        else:  # debit strategy (Calendar)
            entry_debit = abs(pos.net_premium_per_unit)
            gross_pnl = (exit_d.current_close_cost - entry_debit) * pos.lot_size * pos.lots

        all_costs = costs.total_costs + pos.adjustment_costs
        net_pnl = gross_pnl - all_costs

        adj_realized = sum(h.get("realized_pnl", 0) for h in pos.adjustment_history)

        result = TradeResult(
            position_id=pos.position_id,
            strategy_name=pos.strategy_name,
            entry_date=pos.entry_date,
            exit_date=state.date,
            entry_legs=pos.legs,
            exit_legs=exit_d.exit_legs,
            lots=pos.lots,
            lot_size=pos.lot_size,
            net_premium_per_unit=pos.net_premium_per_unit,
            close_cost_per_unit=exit_d.current_close_cost,
            gross_pnl=round(gross_pnl, 2),
            total_costs=round(all_costs, 2),
            net_pnl=round(net_pnl, 2),
            exit_type=exit_d.exit_type,
            holding_days=holding_days,
            margin_required=pos.margin_required,
            metadata=pos.metadata,
            adjustment_count=pos.adjustment_count,
            adjustment_costs=round(pos.adjustment_costs, 2),
            adjustment_pnl=round(adj_realized, 2),
        )
        self.completed_trades.append(result)

        logger.debug(
            "Closed %s on %s: %s, gross=%.2f, costs=%.2f, net=%.2f",
            pos.position_id, state.date, exit_d.exit_type,
            gross_pnl, costs.total_costs, net_pnl,
        )
        return result

    def _compile_result(self, start_date: datetime, end_date: datetime) -> BacktestResult:
        """Aggregate all trade results into a BacktestResult."""
        trades = self.completed_trades
        total_trades = len(trades)

        if total_trades == 0:
            return self._empty_result(start_date, end_date)

        winners = [t for t in trades if t.net_pnl > 0]
        losers = [t for t in trades if t.net_pnl <= 0]

        total_gross = sum(t.gross_pnl for t in trades)
        total_costs = sum(t.total_costs for t in trades)
        total_net = sum(t.net_pnl for t in trades)

        gross_wins = sum(t.net_pnl for t in winners)
        gross_losses = abs(sum(t.net_pnl for t in losers))

        # Max drawdown from daily snapshots
        max_dd = max((s.drawdown for s in self.daily_snapshots), default=0)
        max_dd_pct = max((s.drawdown_pct for s in self.daily_snapshots), default=0)

        # Sharpe ratio (annualised, using daily P&L)
        daily_pnls = [s.daily_pnl for s in self.daily_snapshots if s.daily_pnl != 0]
        sharpe = self._calc_sharpe(daily_pnls)
        sortino = self._calc_sortino(daily_pnls)

        # Annual return
        trading_days = len(self.daily_snapshots)
        years = trading_days / 252 if trading_days > 0 else 1
        annual_return = (total_net / self.capital) / years if years > 0 else 0

        # Calmar
        calmar = annual_return / max_dd_pct if max_dd_pct > 0 else 0

        return BacktestResult(
            strategy_name=self.strategy.name,
            params=self.strategy.params,
            slippage_model=self.cost_engine.slippage_model.value,
            start_date=start_date,
            end_date=end_date,
            trades=trades,
            total_trades=total_trades,
            winning_trades=len(winners),
            losing_trades=len(losers),
            win_rate=len(winners) / total_trades,
            total_gross_pnl=round(total_gross, 2),
            total_costs=round(total_costs, 2),
            total_net_pnl=round(total_net, 2),
            max_drawdown=round(max_dd, 2),
            max_drawdown_pct=round(max_dd_pct, 4),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            profit_factor=round(gross_wins / gross_losses, 2) if gross_losses > 0 else float("inf"),
            avg_trade_pnl=round(total_net / total_trades, 2),
            avg_winner=round(gross_wins / len(winners), 2) if winners else 0,
            avg_loser=round(-gross_losses / len(losers), 2) if losers else 0,
            avg_holding_days=round(sum(t.holding_days for t in trades) / total_trades, 1),
            annual_return_pct=round(annual_return * 100, 2),
            calmar_ratio=round(calmar, 2),
            total_margin_cost=round(sum(t.total_costs for t in trades), 2),
            capital_used=self.capital,
        )

    def _empty_result(self, start_date=None, end_date=None) -> BacktestResult:
        now = datetime.now()
        return BacktestResult(
            strategy_name=self.strategy.name,
            params=self.strategy.params,
            slippage_model=self.cost_engine.slippage_model.value,
            start_date=start_date or now,
            end_date=end_date or now,
            trades=[],
        )

    @staticmethod
    def _calc_sharpe(daily_pnls: list[float], risk_free_daily: float = 0.0) -> float:
        """Annualised Sharpe from daily P&L."""
        if len(daily_pnls) < 2:
            return 0.0
        import statistics
        mean = statistics.mean(daily_pnls) - risk_free_daily
        std = statistics.stdev(daily_pnls)
        if std == 0:
            return 0.0
        return (mean / std) * (252 ** 0.5)

    @staticmethod
    def _calc_sortino(daily_pnls: list[float], risk_free_daily: float = 0.0) -> float:
        """Annualised Sortino from daily P&L (downside deviation only)."""
        if len(daily_pnls) < 2:
            return 0.0
        import statistics
        mean = statistics.mean(daily_pnls) - risk_free_daily
        downside = [p for p in daily_pnls if p < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        down_std = statistics.stdev(downside) if len(downside) > 1 else abs(downside[0])
        if down_std == 0:
            return 0.0
        return (mean / down_std) * (252 ** 0.5)
