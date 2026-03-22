"""
Iron Condor Strategy — entry gates, trade structure generation, and exit signals.

Sells OTM call and put spreads (16-delta shorts, 500-point wings) to collect
premium in sideways/normal markets. Profits from time decay when Nifty stays
within the short strikes.
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config import settings
from src.exceptions import InvalidTradeStructureError, ExpiryNotFoundError
from src.iv_calculator import IVCalculator
from src.models import EntrySignal, ExitSignal, GateResult, TradeStructure

logger = logging.getLogger(__name__)


class IronCondorStrategy:
    """Generates and validates Iron Condor trades on Nifty."""

    def __init__(self, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()

    # --- Entry ---

    def check_entry_conditions(self, market_data: dict, db=None) -> EntrySignal:
        """
        Apply 6 gates in order. Short-circuit on first failure.

        market_data must contain:
          iv_rank: float
          india_vix: float
          expiry_dates: list of datetime or date-string
          today: datetime (optional, defaults to now)

        db: SQLAlchemy session (optional, for position count and drawdown checks)
        """
        today = market_data.get("today", datetime.now())
        gate_results = []
        blocking = []

        # Gate 1: IV Rank >= 30
        iv_rank = market_data.get("iv_rank")
        g1_pass = iv_rank is not None and iv_rank >= settings.IC_MIN_IV_RANK
        g1 = GateResult(
            "IV Rank",
            g1_pass,
            f"{iv_rank:.0f}" if iv_rank is not None else "N/A",
            f">= {settings.IC_MIN_IV_RANK}",
            f"IV Rank {iv_rank if iv_rank is not None else 'N/A'} below minimum {settings.IC_MIN_IV_RANK} — premium not rich enough"
            if not g1_pass else "IV Rank sufficient",
        )
        gate_results.append(g1)
        if not g1_pass:
            blocking.append(g1.message)
            return EntrySignal(False, g1.message, blocking, gate_results)

        # Gate 2: India VIX <= 25
        vix = market_data.get("india_vix", 0)
        g2_pass = vix <= settings.VIX_MAX_FOR_IC
        g2 = GateResult(
            "India VIX",
            g2_pass,
            f"{vix:.1f}",
            f"<= {settings.VIX_MAX_FOR_IC}",
            f"India VIX {vix:.1f} above maximum {settings.VIX_MAX_FOR_IC} — too volatile for IC"
            if not g2_pass else "VIX within range",
        )
        gate_results.append(g2)
        if not g2_pass:
            blocking.append(g2.message)
            return EntrySignal(False, g2.message, blocking, gate_results)

        # Gate 3: DTE between 30 and 45
        dte = self._find_target_dte(market_data.get("expiry_dates", []), today)
        g3_pass = dte is not None and settings.IC_MIN_DTE_ENTRY <= dte <= settings.IC_MAX_DTE_ENTRY
        g3 = GateResult(
            "DTE Window",
            g3_pass,
            f"{dte} days" if dte is not None else "No expiry found",
            f"{settings.IC_MIN_DTE_ENTRY}-{settings.IC_MAX_DTE_ENTRY} days",
            f"No expiry in {settings.IC_MIN_DTE_ENTRY}-{settings.IC_MAX_DTE_ENTRY} DTE window — wrong time of month"
            if not g3_pass else f"Expiry in {dte} days",
        )
        gate_results.append(g3)
        if not g3_pass:
            blocking.append(g3.message)
            return EntrySignal(False, g3.message, blocking, gate_results)

        # Gate 4: Open IC positions < max
        open_count = self._count_open_positions(db, "IC")
        g4_pass = open_count < settings.IC_MAX_OPEN_POSITIONS
        g4 = GateResult(
            "Open Positions",
            g4_pass,
            str(open_count),
            f"< {settings.IC_MAX_OPEN_POSITIONS}",
            f"Maximum {settings.IC_MAX_OPEN_POSITIONS} open IC positions already active"
            if not g4_pass else f"{open_count} open IC positions",
        )
        gate_results.append(g4)
        if not g4_pass:
            blocking.append(g4.message)
            return EntrySignal(False, g4.message, blocking, gate_results)

        # Gate 5: No major event within 25 days
        event_check = self._check_events(today, days_ahead=25)
        g5_pass = event_check is None
        g5 = GateResult(
            "Event Calendar",
            g5_pass,
            "No events" if g5_pass else f"{event_check['name']} on {event_check['date']}",
            "No event within 25 days",
            f"Major event on {event_check['date']}: {event_check['name']} — avoid holding IC through event"
            if not g5_pass else "No upcoming events",
        )
        gate_results.append(g5)
        if not g5_pass:
            blocking.append(g5.message)
            return EntrySignal(False, g5.message, blocking, gate_results)

        # Gate 6: Account drawdown < 5%
        drawdown = self._get_account_drawdown(db)
        g6_pass = drawdown < settings.ACCOUNT_DRAWDOWN_STOP
        g6 = GateResult(
            "Account Drawdown",
            g6_pass,
            f"{drawdown:.1%}",
            f"< {settings.ACCOUNT_DRAWDOWN_STOP:.0%}",
            f"Account drawdown exceeds {settings.ACCOUNT_DRAWDOWN_STOP:.0%} — all trading suspended"
            if not g6_pass else f"Drawdown at {drawdown:.1%}",
        )
        gate_results.append(g6)
        if not g6_pass:
            blocking.append(g6.message)
            return EntrySignal(False, g6.message, blocking, gate_results)

        return EntrySignal(
            True,
            "All gates passed — IC entry signal active",
            [],
            gate_results,
        )

    # --- Trade Structure ---

    def generate_trade_structure(
        self,
        option_chain: dict,
        underlying_price: float,
        expiry_date: datetime | None = None,
        time_to_expiry_years: float | None = None,
    ) -> TradeStructure:
        """
        Build IC trade structure with 16-delta short strikes and 500-point wings.
        Validates net premium > 0 and max loss within capital limits.
        """
        if time_to_expiry_years is None:
            time_to_expiry_years = 35 / 365  # Default ~35 DTE

        if expiry_date is None:
            expiry_date = datetime.now() + timedelta(days=int(time_to_expiry_years * 365))

        # Find 16-delta strikes
        short_call_strike = self.iv_calc.find_strike_by_delta(
            option_chain, settings.IC_SHORT_DELTA, "CE",
            underlying_price=underlying_price,
            time_to_expiry_years=time_to_expiry_years,
        )
        short_put_strike = self.iv_calc.find_strike_by_delta(
            option_chain, settings.IC_SHORT_DELTA, "PE",
            underlying_price=underlying_price,
            time_to_expiry_years=time_to_expiry_years,
        )

        long_call_strike = short_call_strike + settings.IC_WING_WIDTH_POINTS
        long_put_strike = short_put_strike - settings.IC_WING_WIDTH_POINTS

        # Get mid prices for all 4 legs
        short_call_mid = self._get_mid_price(option_chain, short_call_strike, "CE")
        short_put_mid = self._get_mid_price(option_chain, short_put_strike, "PE")
        long_call_mid = self._get_mid_price(option_chain, long_call_strike, "CE")
        long_put_mid = self._get_mid_price(option_chain, long_put_strike, "PE")

        net_premium = short_call_mid + short_put_mid - long_call_mid - long_put_mid

        if net_premium <= 0:
            raise InvalidTradeStructureError(
                f"Net premium is {net_premium:.2f} (must be > 0). "
                f"Short strikes too far OTM or wings too close."
            )

        max_profit_per_lot = net_premium * settings.NIFTY_LOT_SIZE
        max_loss_per_lot = (settings.IC_WING_WIDTH_POINTS - net_premium) * settings.NIFTY_LOT_SIZE

        max_allowed_loss = settings.TOTAL_CAPITAL * settings.IC_MAX_PCT_CAPITAL_PER_TRADE
        if max_loss_per_lot > max_allowed_loss:
            raise InvalidTradeStructureError(
                f"Max loss per lot Rs {max_loss_per_lot:.0f} exceeds "
                f"{settings.IC_MAX_PCT_CAPITAL_PER_TRADE:.0%} of capital (Rs {max_allowed_loss:.0f})"
            )

        profit_target_close_price = net_premium * (1 - settings.IC_PROFIT_TARGET_PCT)
        stop_loss_close_price = net_premium * settings.IC_STOP_LOSS_MULTIPLIER

        return TradeStructure(
            strategy="IC",
            underlying=settings.PRIMARY_INSTRUMENT,
            expiry_date=expiry_date,
            short_call_strike=short_call_strike,
            short_put_strike=short_put_strike,
            long_call_strike=long_call_strike,
            long_put_strike=long_put_strike,
            short_call_premium=short_call_mid,
            short_put_premium=short_put_mid,
            long_call_premium=long_call_mid,
            long_put_premium=long_put_mid,
            net_premium=net_premium,
            max_profit_per_lot=max_profit_per_lot,
            max_loss_per_lot=max_loss_per_lot,
            profit_target_close_price=profit_target_close_price,
            stop_loss_close_price=stop_loss_close_price,
        )

    # --- Exit ---

    def check_exit_conditions(
        self,
        position: dict,
        current_data: dict,
    ) -> ExitSignal:
        """
        Check exit conditions in priority order:
        1. Stop loss (2x premium) — IMMEDIATE
        2. Time stop (21 DTE) — TODAY
        3. Profit target (50%) — TODAY

        position dict must contain:
          entry_premium: float
          expiry_date: datetime

        current_data must contain:
          current_close_cost: float (cost to close all legs now)
        """
        entry_premium = position["entry_premium"]
        expiry_date = position["expiry_date"]
        if isinstance(expiry_date, str):
            expiry_date = datetime.fromisoformat(expiry_date)

        current_close_cost = current_data["current_close_cost"]
        now = current_data.get("now", datetime.now())

        # 1. STOP LOSS — highest priority
        if current_close_cost >= entry_premium * settings.IC_STOP_LOSS_MULTIPLIER:
            return ExitSignal(
                True, "STOP_LOSS", "IMMEDIATE",
                f"Loss exceeds {settings.IC_STOP_LOSS_MULTIPLIER}x premium. "
                f"Close ALL legs with market orders NOW.",
            )

        # 2. TIME STOP
        dte = (expiry_date - now).days
        if dte <= settings.IC_TIME_STOP_DTE:
            return ExitSignal(
                True, "TIME_STOP", "TODAY",
                f"{settings.IC_TIME_STOP_DTE} DTE reached ({dte} days left). "
                f"Close by 3 PM today.",
            )

        # 3. PROFIT TARGET
        profit_pct = 1 - (current_close_cost / entry_premium)
        if profit_pct >= settings.IC_PROFIT_TARGET_PCT:
            return ExitSignal(
                True, "PROFIT_TARGET", "TODAY",
                f"Profit target reached at {profit_pct:.0%}. "
                f"Close and consider re-entry.",
            )

        # 4. No exit needed
        return ExitSignal(
            False, "NONE", "MONITOR",
            "Position within parameters.",
        )

    # --- Helpers ---

    @staticmethod
    def _get_mid_price(
        option_chain: dict, strike: int, option_type: str
    ) -> float:
        """Get mid price (average of bid and ask) for a specific strike/type."""
        for record in option_chain.get("records", []):
            if record["strike"] == strike and record["option_type"] == option_type:
                bid = record.get("bid", record.get("ltp", 0))
                ask = record.get("ask", record.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return record.get("ltp", 0)

        # Strike not found in chain — estimate from nearby strikes
        logger.warning("Strike %d %s not found in chain. Using LTP fallback.", strike, option_type)
        records = [
            r for r in option_chain.get("records", [])
            if r["option_type"] == option_type
        ]
        if not records:
            return 0.0

        # Find closest strike
        closest = min(records, key=lambda r: abs(r["strike"] - strike))
        return closest.get("ltp", 0)

    @staticmethod
    def _find_target_dte(expiry_dates: list, today: datetime) -> int | None:
        """Find the nearest expiry with DTE between IC_MIN_DTE_ENTRY and IC_MAX_DTE_ENTRY."""
        for expiry_str in sorted(expiry_dates):
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if hasattr(expiry, "hour") is False:
                    expiry = datetime.combine(expiry, datetime.min.time())

            dte = (expiry - today).days
            if settings.IC_MIN_DTE_ENTRY <= dte <= settings.IC_MAX_DTE_ENTRY:
                return dte
        return None

    @staticmethod
    def _count_open_positions(db, strategy: str) -> int:
        """Count open positions for a given strategy."""
        if db is None:
            return 0
        from db.crud import get_open_trades
        return len(get_open_trades(db, strategy=strategy))

    @staticmethod
    def _check_events(today: datetime, days_ahead: int = 25) -> dict | None:
        """Check if any event is within days_ahead. Returns first event found or None."""
        try:
            events_path = Path("config/events_calendar.json")
            with open(events_path) as f:
                calendar = json.load(f)
        except FileNotFoundError:
            return None

        cutoff = today + timedelta(days=days_ahead)

        for event in calendar.get("events", []):
            event_date = datetime.strptime(event["date"], "%Y-%m-%d")
            if today <= event_date <= cutoff:
                return event
        return None

    @staticmethod
    def _get_account_drawdown(db) -> float:
        """Calculate current account drawdown as a fraction."""
        if db is None:
            return 0.0
        from db.crud import get_all_trades
        trades = get_all_trades(db)
        total_pnl = sum(t.net_pnl or 0 for t in trades)
        if total_pnl >= 0:
            return 0.0
        return abs(total_pnl) / settings.TOTAL_CAPITAL


# ── Regime Detection (v3) ────────────────────────────────────────────────────

def detect_regime(spot_history: pd.Series) -> str:
    """
    Detect market regime from spot price history.

    BULLISH: 20-day SMA rising AND price above 50-day SMA
    BEARISH: 20-day SMA falling AND price below 50-day SMA
    NEUTRAL: everything else

    Requires at least 50 data points.
    """
    if len(spot_history) < 50:
        return "NEUTRAL"

    sma20 = spot_history.rolling(20).mean()
    sma50 = spot_history.rolling(50).mean()
    spot = spot_history.iloc[-1]
    sma20_rising = sma20.iloc[-1] > sma20.iloc[-2]
    sma20_falling = sma20.iloc[-1] < sma20.iloc[-2]

    if spot > sma50.iloc[-1] and sma20_rising:
        return "BULLISH"
    if spot < sma50.iloc[-1] and sma20_falling:
        return "BEARISH"
    return "NEUTRAL"


def get_skewed_deltas(regime: str, base_delta: float = 0.16) -> tuple[float, float]:
    """
    Get regime-aware call/put deltas for Iron Condor.

    In BULLISH: tighter call (0.12), wider put (0.22) — collect more on the side market won't go.
    In BEARISH: wider call (0.22), tighter put (0.12) — same logic, reversed.
    In NEUTRAL: symmetric (base_delta, base_delta).

    Returns (call_delta, put_delta).
    """
    if regime == "BULLISH":
        return (0.12, 0.22)
    if regime == "BEARISH":
        return (0.22, 0.12)
    return (base_delta, base_delta)
