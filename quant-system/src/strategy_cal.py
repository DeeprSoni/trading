"""
Calendar Spread Strategy — entry gates, trade structure, roll and adjustment signals.

Buys a far-month ATM call and sells a near-month ATM call to profit from the
IV differential and faster theta decay of the front month. Uses monthly expiries
only (Nifty weekly expiries were discontinued in late 2024).
"""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from config import settings
from src.exceptions import ExpiryNotFoundError
from src.iv_calculator import IVCalculator
from src.models import (
    AdjustmentSignal, CalendarTradeStructure, EntrySignal, GateResult, RollSignal,
)

logger = logging.getLogger(__name__)


class CalendarSpreadStrategy:
    """Generates and validates Calendar Spread trades on Nifty."""

    def __init__(self, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()

    # --- Entry ---

    def check_entry_conditions(self, market_data: dict, db=None) -> EntrySignal:
        """
        Apply 4 gates in order. Short-circuit on first failure.

        market_data must contain:
          india_vix: float
          expiry_dates: list of datetime or date-strings
          today: datetime (optional)
        """
        today = market_data.get("today", datetime.now())
        gate_results = []
        blocking = []

        # Gate 1: VIX <= 28
        vix = market_data.get("india_vix", 0)
        g1_pass = vix <= settings.VIX_HIGH_THRESHOLD
        g1 = GateResult(
            "India VIX",
            g1_pass,
            f"{vix:.1f}",
            f"<= {settings.VIX_HIGH_THRESHOLD}",
            f"VIX {vix:.1f} above {settings.VIX_HIGH_THRESHOLD} — back-month option too expensive"
            if not g1_pass else "VIX within range for calendar",
        )
        gate_results.append(g1)
        if not g1_pass:
            blocking.append(g1.message)
            return EntrySignal(False, g1.message, blocking, gate_results)

        # Gate 2: No event within 7 days
        event = self._check_events(today, days_ahead=7)
        g2_pass = event is None
        g2 = GateResult(
            "Event Calendar",
            g2_pass,
            "No events" if g2_pass else f"{event['name']} on {event['date']}",
            "No event within 7 days",
            f"Event in {(datetime.strptime(event['date'], '%Y-%m-%d') - today).days} days: {event['name']} — wait until after"
            if not g2_pass else "No upcoming events",
        )
        gate_results.append(g2)
        if not g2_pass:
            blocking.append(g2.message)
            return EntrySignal(False, g2.message, blocking, gate_results)

        # Gate 3: Open calendar positions < max
        open_count = self._count_open_positions(db, "CAL")
        g3_pass = open_count < settings.CAL_MAX_OPEN_POSITIONS
        g3 = GateResult(
            "Open Positions",
            g3_pass,
            str(open_count),
            f"< {settings.CAL_MAX_OPEN_POSITIONS}",
            f"Maximum {settings.CAL_MAX_OPEN_POSITIONS} open calendar positions reached"
            if not g3_pass else f"{open_count} open calendar positions",
        )
        gate_results.append(g3)
        if not g3_pass:
            blocking.append(g3.message)
            return EntrySignal(False, g3.message, blocking, gate_results)

        # Gate 4: Back-month (60-75 DTE) AND front-month (20-35 DTE) expiries exist
        expiry_dates = market_data.get("expiry_dates", [])
        back_dte = self._find_expiry_in_range(
            expiry_dates, today,
            settings.CAL_BACK_MONTH_MIN_DTE, settings.CAL_BACK_MONTH_MAX_DTE,
        )
        front_dte = self._find_expiry_in_range(
            expiry_dates, today,
            settings.CAL_FRONT_MONTH_MIN_DTE, settings.CAL_FRONT_MONTH_MAX_DTE,
        )
        g4_pass = back_dte is not None and front_dte is not None
        if not g4_pass:
            missing = []
            if back_dte is None:
                missing.append(f"back-month ({settings.CAL_BACK_MONTH_MIN_DTE}-{settings.CAL_BACK_MONTH_MAX_DTE} DTE)")
            if front_dte is None:
                missing.append(f"front-month ({settings.CAL_FRONT_MONTH_MIN_DTE}-{settings.CAL_FRONT_MONTH_MAX_DTE} DTE)")
            msg = f"No expiry in {' or '.join(missing)} window"
        else:
            msg = f"Back-month {back_dte} DTE, front-month {front_dte} DTE"

        g4 = GateResult(
            "Expiry Availability",
            g4_pass,
            msg,
            f"Back {settings.CAL_BACK_MONTH_MIN_DTE}-{settings.CAL_BACK_MONTH_MAX_DTE} + Front {settings.CAL_FRONT_MONTH_MIN_DTE}-{settings.CAL_FRONT_MONTH_MAX_DTE}",
            msg if not g4_pass else msg,
        )
        gate_results.append(g4)
        if not g4_pass:
            blocking.append(g4.message)
            return EntrySignal(False, g4.message, blocking, gate_results)

        return EntrySignal(
            True,
            "All gates passed — Calendar entry signal active",
            [],
            gate_results,
        )

    # --- Trade Structure ---

    def generate_trade_structure(
        self,
        option_chain: dict,
        underlying_price: float,
    ) -> CalendarTradeStructure:
        """
        Build Calendar Spread: buy back-month ATM call, sell front-month ATM call.
        Uses monthly expiries only.
        """
        # ATM strike (rounded to nearest 100)
        strike = round(underlying_price / 100) * 100

        expiry_dates = option_chain.get("expiry_dates", [])
        today = datetime.now()

        # Find back month: 60-75 DTE
        back_month_expiry = self._find_expiry_date(
            expiry_dates, today,
            settings.CAL_BACK_MONTH_MIN_DTE, settings.CAL_BACK_MONTH_MAX_DTE,
        )
        if back_month_expiry is None:
            raise ExpiryNotFoundError(
                f"No back-month expiry in {settings.CAL_BACK_MONTH_MIN_DTE}-"
                f"{settings.CAL_BACK_MONTH_MAX_DTE} DTE window"
            )

        # Find front month: 20-35 DTE (monthly, not weekly)
        front_month_expiry = self._find_expiry_date(
            expiry_dates, today,
            settings.CAL_FRONT_MONTH_MIN_DTE, settings.CAL_FRONT_MONTH_MAX_DTE,
        )
        if front_month_expiry is None:
            raise ExpiryNotFoundError(
                f"No front-month expiry in {settings.CAL_FRONT_MONTH_MIN_DTE}-"
                f"{settings.CAL_FRONT_MONTH_MAX_DTE} DTE window"
            )

        back_month_cost = self._get_mid_price(
            option_chain, strike, "CE", str(back_month_expiry.date())
        )
        front_month_premium = self._get_mid_price(
            option_chain, strike, "CE", str(front_month_expiry.date())
        )

        net_debit = back_month_cost - front_month_premium
        max_loss = net_debit * settings.NIFTY_LOT_SIZE

        return CalendarTradeStructure(
            strategy="CAL",
            underlying=settings.PRIMARY_INSTRUMENT,
            strike=strike,
            back_month_expiry=back_month_expiry,
            front_month_expiry=front_month_expiry,
            back_month_cost=back_month_cost,
            front_month_premium=front_month_premium,
            net_debit=net_debit,
            max_loss_per_lot=max_loss,
        )

    # --- Roll Conditions ---

    def check_roll_conditions(self, position: dict, current_data: dict) -> RollSignal:
        """
        Check if front month needs rolling or position needs closing.

        position dict: front_month_expiry, back_month_expiry, front_month_entry_premium
        current_data dict: front_month_current_price, back_month_iv_change_pct, now (optional)
        """
        now = current_data.get("now", datetime.now())

        front_expiry = position["front_month_expiry"]
        if isinstance(front_expiry, str):
            front_expiry = datetime.fromisoformat(front_expiry)
        front_month_dte = (front_expiry - now).days

        back_expiry = position["back_month_expiry"]
        if isinstance(back_expiry, str):
            back_expiry = datetime.fromisoformat(back_expiry)
        back_month_dte = (back_expiry - now).days

        # 1. Front month expiring in 3 days — roll to next monthly
        if front_month_dte <= 3:
            return RollSignal(
                True, "ROLL_FRONT",
                "Front month expiring in 3 days. Sell next monthly expiry immediately.",
            )

        # 2. Front month at 50% profit — early roll
        entry_premium = position.get("front_month_entry_premium", 0)
        current_price = current_data.get("front_month_current_price", entry_premium)
        if entry_premium > 0:
            profit_pct = 1 - (current_price / entry_premium)
            if profit_pct >= 0.50:
                return RollSignal(
                    True, "ROLL_FRONT",
                    "Front month at 50% profit. Early roll to next monthly to reset theta clock.",
                )

        # 3. Back month at 25 DTE — close entire position
        if back_month_dte <= settings.CAL_BACK_MONTH_CLOSE_DTE:
            return RollSignal(
                True, "CLOSE_BACK_MONTH",
                "Back month at 25 DTE. Close entire position now.",
            )

        # 4. Back month IV expansion >= 30%
        iv_change = current_data.get("back_month_iv_change_pct", 0)
        if iv_change >= 30:
            return RollSignal(
                True, "HARVEST_AND_CLOSE",
                "Back month gained 30%+ from IV expansion. Harvest this bonus.",
            )

        return RollSignal(False, "NONE", "Position healthy.")

    # --- Adjustment Conditions ---

    def check_adjustment_conditions(
        self, position: dict, current_data: dict
    ) -> AdjustmentSignal:
        """
        Check if underlying has moved too far from calendar strike.

        position dict: strike (int)
        current_data dict: underlying_value (float)
        """
        strike = position["strike"]
        current_price = current_data["underlying_value"]
        move_pct = abs(current_price - strike) / strike

        # 4% move — close entire position
        if move_pct >= settings.CAL_MAX_MOVE_PCT_TO_CLOSE:
            return AdjustmentSignal(
                True, "CLOSE", "IMMEDIATE",
                f"Market moved {move_pct:.1%} from strike. Close entire position.",
            )

        # 2% move — recentre calendar
        if move_pct >= settings.CAL_MAX_MOVE_PCT_TO_ADJUST:
            return AdjustmentSignal(
                True, "CENTRE", "TODAY",
                f"Market moved {move_pct:.1%}. Centre calendar at new ATM.",
            )

        return AdjustmentSignal(
            False, "NONE", "MONITOR",
            "Within acceptable range.",
        )

    # --- Helpers ---

    @staticmethod
    def _find_expiry_in_range(
        expiry_dates: list, today: datetime, min_dte: int, max_dte: int
    ) -> int | None:
        """Find DTE for first expiry in the given range. Returns DTE or None."""
        for expiry_str in sorted(expiry_dates):
            expiry = datetime.fromisoformat(str(expiry_str)) if isinstance(expiry_str, str) else expiry_str
            if not hasattr(expiry, "hour"):
                expiry = datetime.combine(expiry, datetime.min.time())
            dte = (expiry - today).days
            if min_dte <= dte <= max_dte:
                return dte
        return None

    @staticmethod
    def _find_expiry_date(
        expiry_dates: list, today: datetime, min_dte: int, max_dte: int
    ) -> datetime | None:
        """Find first expiry date in the given DTE range."""
        for expiry_str in sorted(expiry_dates):
            expiry = datetime.fromisoformat(str(expiry_str)) if isinstance(expiry_str, str) else expiry_str
            if not hasattr(expiry, "hour"):
                expiry = datetime.combine(expiry, datetime.min.time())
            dte = (expiry - today).days
            if min_dte <= dte <= max_dte:
                return expiry
        return None

    @staticmethod
    def _get_mid_price(
        option_chain: dict, strike: int, option_type: str, expiry: str | None = None
    ) -> float:
        """Get mid price for a specific strike/type, optionally filtered by expiry."""
        for record in option_chain.get("records", []):
            if record["strike"] == strike and record["option_type"] == option_type:
                if expiry is not None and str(record.get("expiry", "")) != expiry:
                    continue
                bid = record.get("bid", record.get("ltp", 0))
                ask = record.get("ask", record.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return record.get("ltp", 0)

        # Fallback — closest strike
        records = [
            r for r in option_chain.get("records", [])
            if r["option_type"] == option_type
        ]
        if expiry is not None:
            records = [r for r in records if str(r.get("expiry", "")) == expiry]
        if not records:
            return 0.0
        closest = min(records, key=lambda r: abs(r["strike"] - strike))
        return closest.get("ltp", 0)

    @staticmethod
    def _check_events(today: datetime, days_ahead: int = 7) -> dict | None:
        try:
            with open(Path("config/events_calendar.json")) as f:
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
    def _count_open_positions(db, strategy: str) -> int:
        if db is None:
            return 0
        from db.crud import get_open_trades
        return len(get_open_trades(db, strategy=strategy))
