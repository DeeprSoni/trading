"""
Strategy Protocol — generic interface for plugging any options strategy
into the backtesting engine.

Any strategy that implements this protocol can be backtested without
modifying the backtester itself.
"""

from typing import Protocol, runtime_checkable

from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, MarketState, Position,
)


@runtime_checkable
class BacktestStrategy(Protocol):
    """
    Protocol that any strategy adapter must implement.

    The backtester calls these methods in order on each simulation day:
      1. should_enter()  — check if conditions allow a new trade
      2. generate_entry() — build the specific legs
      3. should_exit()   — check open positions for exit signals
      4. should_adjust() — check open positions for mid-trade adjustments

    Each method receives a MarketState snapshot and returns a decision dataclass.
    """

    @property
    def name(self) -> str:
        """Short name for this strategy variant (e.g. 'IC_base', 'CAL_aggressive')."""
        ...

    @property
    def params(self) -> dict:
        """Current parameter set as a dict (for logging/display)."""
        ...

    def should_enter(self, state: MarketState) -> bool:
        """Quick pre-check: are market conditions right for entry?"""
        ...

    def generate_entry(self, state: MarketState) -> EntryDecision:
        """
        Build the full trade structure (legs, premiums, margin).
        Only called when should_enter() returns True.
        """
        ...

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """Check if an open position should be closed."""
        ...

    def should_adjust(self, position: Position, state: MarketState) -> AdjustmentDecision:
        """Check if an open position needs mid-trade adjustment (optional)."""
        ...

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """
        Return the current cost-to-close for an open position.
        Used by the backtester for daily P&L tracking and drawdown calculation.
        """
        ...
