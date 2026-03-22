"""
Calendar Spread Backtest Adapter — bridges CalendarSpreadStrategy to the
generic BacktestStrategy protocol.

Parameterised: accepts overrides for DTE ranges, adjustment thresholds,
roll triggers, VIX limits, etc.
"""

import logging
from datetime import datetime

from config import settings
from src.iv_calculator import IVCalculator
from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, Leg, MarketState, Position,
)
from src.adjustments_cal import (
    evaluate_cal_adjustment, CALPosition, CALAdjustmentConfig, CALAdjustment,
)

logger = logging.getLogger(__name__)


class CalBacktestAdapter:
    """
    Calendar Spread adapter for the generic backtester.

    Entry: buy back-month ATM call, sell front-month ATM call.
    Adjustments: recentre at 2% move, close at 4% move.
    """

    def __init__(self, params: dict | None = None, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()
        p = params or {}
        self._params = {
            "max_vix": p.get("max_vix", settings.VIX_HIGH_THRESHOLD),
            "front_min_dte": p.get("front_min_dte", settings.CAL_FRONT_MONTH_MIN_DTE),
            "front_max_dte": p.get("front_max_dte", settings.CAL_FRONT_MONTH_MAX_DTE),
            "back_min_dte": p.get("back_min_dte", settings.CAL_BACK_MONTH_MIN_DTE),
            "back_max_dte": p.get("back_max_dte", settings.CAL_BACK_MONTH_MAX_DTE),
            "profit_target_pct": p.get("profit_target_pct", settings.CAL_PROFIT_TARGET_PCT),
            "back_month_close_dte": p.get("back_month_close_dte", settings.CAL_BACK_MONTH_CLOSE_DTE),
            "move_pct_to_adjust": p.get("move_pct_to_adjust", settings.CAL_MAX_MOVE_PCT_TO_ADJUST),
            "move_pct_to_close": p.get("move_pct_to_close", settings.CAL_MAX_MOVE_PCT_TO_CLOSE),
            "front_roll_dte": p.get("front_roll_dte", 3),
            "front_profit_roll_pct": p.get("front_profit_roll_pct", 0.50),
            "iv_harvest_pct": p.get("iv_harvest_pct", 30),
            "max_open_positions": p.get("max_open_positions", settings.CAL_MAX_OPEN_POSITIONS),
            "lot_size": p.get("lot_size", settings.NIFTY_LOT_SIZE),
        }

    @property
    def name(self) -> str:
        p = self._params
        pt = int(p["profit_target_pct"] * 100)
        adj = int(p["move_pct_to_adjust"] * 100)
        cls = int(p["move_pct_to_close"] * 100)
        return f"CAL_pt{pt}_adj{adj}_cls{cls}"

    @property
    def params(self) -> dict:
        return dict(self._params)

    def should_enter(self, state: MarketState) -> bool:
        """Quick pre-check: VIX and both expiry windows available."""
        p = self._params
        if state.india_vix > p["max_vix"]:
            return False
        front = self._find_dte_in_range(state, p["front_min_dte"], p["front_max_dte"])
        back = self._find_dte_in_range(state, p["back_min_dte"], p["back_max_dte"])
        return front is not None and back is not None

    def generate_entry(self, state: MarketState) -> EntryDecision:
        """Build calendar: buy back-month ATM, sell front-month ATM."""
        p = self._params
        chain = state.option_chain

        # ATM strike
        strike = round(state.underlying_price / 100) * 100

        front_dte = self._find_dte_in_range(state, p["front_min_dte"], p["front_max_dte"])
        back_dte = self._find_dte_in_range(state, p["back_min_dte"], p["back_max_dte"])
        if front_dte is None or back_dte is None:
            return EntryDecision(False, reason="Missing front or back month expiry")

        front_expiry = self._find_expiry(state, front_dte)
        back_expiry = self._find_expiry(state, back_dte)

        # Get actual prices from chain for each expiry
        front_premium = self._get_mid_by_expiry(chain, strike, "CE", front_expiry)
        back_cost = self._get_mid_by_expiry(chain, strike, "CE", back_expiry)

        if front_premium <= 0 or back_cost <= 0:
            return EntryDecision(False, reason="Could not price front or back month")

        net_debit = back_cost - front_premium
        if net_debit <= 0:
            return EntryDecision(False, reason=f"Net debit {net_debit:.2f} <= 0")

        legs = [
            Leg(strike, "CE", "BUY", back_cost, back_expiry),
            Leg(strike, "CE", "SELL", front_premium, front_expiry),
        ]

        max_loss = net_debit * p["lot_size"]
        margin = max_loss * 1.5  # calendar margin is typically higher

        return EntryDecision(
            should_enter=True,
            legs=legs,
            net_premium_per_unit=-net_debit,  # negative = debit
            margin_required=margin,
            reason="Calendar entry — all gates passed",
            metadata={
                "strike": strike,
                "front_dte": front_dte,
                "back_dte": back_dte,
                "vix_at_entry": state.india_vix,
                "underlying_at_entry": state.underlying_price,
                "back_iv_at_entry": self._get_iv_by_expiry(chain, strike, "CE", back_expiry),
            },
        )

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """
        Exit checks:
        1. Underlying moved > close threshold — CLOSE
        2. Back month at close DTE — CLOSE
        3. Profit target reached — CLOSE
        4. Front month about to expire — TIME_STOP (should roll, but for backtest we close)
        """
        p = self._params
        close_cost = self.reprice_position(position, state)
        entry_debit = abs(position.net_premium_per_unit)

        strike = position.metadata.get("strike", position.legs[0].strike)
        move_pct = abs(state.underlying_price - strike) / strike if strike > 0 else 0

        # 1. Large move — close
        if move_pct >= p["move_pct_to_close"]:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "ADJUSTMENT", "IMMEDIATE",
                f"Underlying moved {move_pct:.1%} from strike — close",
                close_cost, exit_legs,
            )

        # 2. Back month DTE check
        back_leg = max(position.legs, key=lambda l: l.expiry_date)
        back_dte = (back_leg.expiry_date - state.date).days
        if back_dte <= p["back_month_close_dte"]:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "TIME_STOP", "TODAY",
                f"Back month at {back_dte} DTE — close entire position",
                close_cost, exit_legs,
            )

        # 3. Profit target
        if entry_debit > 0:
            # Calendar profit = current_value - entry_debit
            current_value = self._position_value(position, state)
            profit_pct = (current_value - entry_debit) / entry_debit
            if profit_pct >= p["profit_target_pct"]:
                exit_legs = self._make_exit_legs(position, state)
                return ExitDecision(
                    True, "PROFIT_TARGET", "TODAY",
                    f"Calendar profit {profit_pct:.0%} >= target",
                    close_cost, exit_legs,
                )

        # 4. Front month expiry safeguard (adjustment engine handles rolling,
        #    this is a last-resort close if front month actually expires)
        front_leg = min(position.legs, key=lambda l: l.expiry_date)
        front_dte = (front_leg.expiry_date - state.date).days
        if front_dte <= 0:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "EXPIRY", "IMMEDIATE",
                f"Front month expired — forced close",
                close_cost, exit_legs,
            )

        return ExitDecision(False, "NONE", "MONITOR", "Within parameters", close_cost)

    def should_adjust(self, position: Position, state: MarketState) -> AdjustmentDecision:
        """Calendar adjustment logic — v2 engine handles all adjustments.

        Kept here: IV harvest (needs back_iv_at_entry from metadata), recentre, large-move close.
        Removed: old DTE<=3 front roll and 50% decay roll (v2 engine handles at DTE<=6, 60% decay).
        Added via v2: early profit close, diagonal convert, add second calendar.
        """
        p = self._params
        chain = state.option_chain

        front_leg = min(position.legs, key=lambda l: l.expiry_date)
        back_leg = max(position.legs, key=lambda l: l.expiry_date)
        strike = position.metadata.get("strike", front_leg.strike)

        # Limit to one adjustment per day
        last_adj = position.metadata.get("last_adjustment_date")
        if last_adj and last_adj == state.date.isoformat():
            return AdjustmentDecision(False, "NONE", reason="Already adjusted today")

        # IV Harvest — back month IV expanded 30%+ (needs metadata, kept here)
        entry_iv = position.metadata.get("back_iv_at_entry", 0)
        if entry_iv > 0:
            current_iv = self._get_iv_by_expiry(
                chain, back_leg.strike, back_leg.option_type, back_leg.expiry_date,
            )
            if current_iv > 0:
                iv_expansion = ((current_iv - entry_iv) / entry_iv) * 100
                if iv_expansion >= p["iv_harvest_pct"]:
                    close_legs = self._make_exit_legs(position, state)
                    close_cost = self.reprice_position(position, state)
                    return AdjustmentDecision(
                        should_adjust=True, action="IV_HARVEST",
                        close_legs=close_legs, new_legs=[],
                        reason=f"Back IV expanded {iv_expansion:.0f}% ({entry_iv:.1f} -> {current_iv:.1f})",
                        close_cost=close_cost,
                    )

        # Recentre on 2% move (kept — needs strike from metadata)
        move_pct = abs(state.underlying_price - strike) / strike if strike > 0 else 0
        if move_pct >= p["move_pct_to_adjust"] and move_pct < p["move_pct_to_close"]:
            return self._recentre(position, state, front_leg, back_leg, move_pct)

        # All other adjustments via v2 engine (front roll, early profit, diagonal, add cal)
        v2_result = self._check_v2_adjustments(
            position, state, front_leg, back_leg, strike,
        )
        if v2_result.should_adjust:
            return v2_result

        return AdjustmentDecision(False, "NONE", reason="Calendar: within range")

    def _build_cal_position(
        self, position: Position, state: MarketState,
        front_leg, back_leg, strike,
    ) -> CALPosition:
        """Construct CALPosition from Position legs + metadata."""
        chain = state.option_chain
        entry_spot = position.metadata.get("entry_spot", state.underlying_price)

        front_curr = self._get_mid_by_expiry(
            chain, front_leg.strike, front_leg.option_type, front_leg.expiry_date,
        )

        return CALPosition(
            symbol="NIFTY",
            entry_date=position.entry_date,
            entry_spot=entry_spot,
            front_expiry=front_leg.expiry_date,
            back_expiry=back_leg.expiry_date,
            front_month_entry_value=front_leg.premium,
            front_month_current_value=front_curr,
            back_month_iv_at_entry=position.metadata.get("back_iv_at_entry", 0),
            back_month_iv_current=self._get_iv_by_expiry(
                chain, back_leg.strike, back_leg.option_type, back_leg.expiry_date,
            ),
            calendar_entry_credit=abs(position.net_premium_per_unit),
            calendar_current_value=self._position_value(position, state),
            secondary_calendars_added=position.metadata.get("secondary_calendars_added", 0),
            is_diagonal=position.metadata.get("is_diagonal", False),
        )

    def _check_v2_adjustments(
        self, position, state, front_leg, back_leg, strike,
    ) -> AdjustmentDecision:
        """Check v2 CAL adjustments: early profit, diagonal, add second cal."""
        cal_pos = self._build_cal_position(position, state, front_leg, back_leg, strike)

        front_dte = (front_leg.expiry_date - state.date).days
        back_dte = (back_leg.expiry_date - state.date).days

        # Skip checks handled above; enable front roll and other v2 checks
        cfg = CALAdjustmentConfig(
            large_move_pct=999.0,       # handled by should_exit (4% move close)
            back_close_dte=0,           # handled by should_exit
            iv_harvest_trigger=999.0,   # handled above (needs metadata)
            full_recentre_pct=999.0,    # handled above (needs strike from metadata)
            # Enabled: front_roll_dte=6, front_decay_threshold=0.60,
            #          early_profit, diagonal, add_second_cal
        )

        action = evaluate_cal_adjustment(cal_pos, state.underlying_price, front_dte, back_dte, cfg)

        if action == CALAdjustment.NONE:
            return AdjustmentDecision(False, "NONE")

        return self._map_v2_cal_adjustment(
            action, position, state, cal_pos, front_leg, back_leg,
        )

    def _map_v2_cal_adjustment(
        self, action, position, state, cal_pos, front_leg, back_leg,
    ) -> AdjustmentDecision:
        """Map CALAdjustment enum to AdjustmentDecision."""
        chain = state.option_chain
        expiry = front_leg.expiry_date

        if action == CALAdjustment.FRONT_ROLL:
            # v2 front roll at DTE<=6 and 60% decay
            return self._roll_front_month(
                position, state, front_leg, back_leg,
                f"v2: Front month roll (DTE or decay threshold met)",
            )

        if action == CALAdjustment.EARLY_PROFIT_CLOSE:
            close_legs = self._make_exit_legs(position, state)
            close_cost = self.reprice_position(position, state)
            return AdjustmentDecision(
                should_adjust=True, action="EARLY_PROFIT_CLOSE",
                close_legs=close_legs, new_legs=[],
                reason=f"Early profit {cal_pos.unrealized_profit_pct:.0%} — closing",
                close_cost=close_cost,
            )

        if action == CALAdjustment.DIAGONAL_CONVERT:
            # Close current front, sell OTM front (diagonal)
            front_close_mid = self._get_mid_by_expiry(
                chain, front_leg.strike, front_leg.option_type, expiry,
            )
            close_legs = [
                Leg(front_leg.strike, front_leg.option_type, "BUY", front_close_mid, expiry),
            ]
            # Sell front at new strike (OTM in direction of move)
            direction = 1 if state.underlying_price > cal_pos.entry_spot else -1
            new_strike = round((state.underlying_price + direction * 100) / 100) * 100
            new_front_mid = self._get_mid_by_expiry(
                chain, new_strike, front_leg.option_type, expiry,
            )
            new_legs = [
                Leg(new_strike, front_leg.option_type, "SELL", new_front_mid, expiry),
            ]
            position.metadata["is_diagonal"] = True
            return AdjustmentDecision(
                should_adjust=True, action="DIAGONAL_CONVERT",
                close_legs=close_legs, new_legs=new_legs,
                reason=f"1.5%+ move — converting to diagonal at {new_strike}",
                close_cost=front_close_mid,
            )

        if action == CALAdjustment.ADD_SECOND_CAL:
            # Add second calendar 200 pts OTM
            offset = 200
            direction = 1 if state.underlying_price > cal_pos.entry_spot else -1
            new_strike = round((state.underlying_price + direction * offset) / 100) * 100

            new_front_mid = self._get_mid_by_expiry(
                chain, new_strike, front_leg.option_type, front_leg.expiry_date,
            )
            new_back_mid = self._get_mid_by_expiry(
                chain, new_strike, back_leg.option_type, back_leg.expiry_date,
            )
            new_legs = [
                Leg(new_strike, front_leg.option_type, "SELL", new_front_mid, front_leg.expiry_date),
                Leg(new_strike, back_leg.option_type, "BUY", new_back_mid, back_leg.expiry_date),
            ]
            position.metadata["secondary_calendars_added"] = (
                position.metadata.get("secondary_calendars_added", 0) + 1
            )
            return AdjustmentDecision(
                should_adjust=True, action="ADD_SECOND_CAL",
                close_legs=[], new_legs=new_legs,
                reason=f"Adding second calendar at {new_strike} (25%+ profit, market stable)",
                new_premium_per_unit=-(new_back_mid - new_front_mid),
            )

        return AdjustmentDecision(False, "NONE")

    def _roll_front_month(self, position, state, front_leg, back_leg, reason):
        """Close current front month, sell new front month at same strike with next expiry."""
        chain = state.option_chain

        # Close: buy back current front month
        front_close_mid = self._get_mid_by_expiry(
            chain, front_leg.strike, front_leg.option_type, front_leg.expiry_date,
        )
        close_legs = [
            Leg(front_leg.strike, front_leg.option_type, "BUY", front_close_mid, front_leg.expiry_date),
        ]

        # Find next monthly expiry after current front
        new_front_expiry = self._find_next_expiry_after(state, front_leg.expiry_date)
        if new_front_expiry is None or new_front_expiry >= back_leg.expiry_date:
            # Can't roll — close entire position
            all_close = self._make_exit_legs(position, state)
            close_cost = self.reprice_position(position, state)
            return AdjustmentDecision(
                should_adjust=True, action="CLOSE",
                close_legs=all_close, new_legs=[],
                reason="Cannot roll front month — no valid next expiry, closing",
                close_cost=close_cost,
            )

        # New: sell next monthly at same strike
        new_front_mid = self._get_mid_by_expiry(
            chain, front_leg.strike, front_leg.option_type, new_front_expiry,
        )
        new_legs = [
            Leg(front_leg.strike, front_leg.option_type, "SELL", new_front_mid, new_front_expiry),
        ]

        # Updated premium: back value minus new front credit
        back_current = self._get_mid_by_expiry(
            chain, back_leg.strike, back_leg.option_type, back_leg.expiry_date,
        )
        new_prem = -(back_current - new_front_mid)  # negative = debit

        return AdjustmentDecision(
            should_adjust=True, action="ROLL_FRONT",
            close_legs=close_legs, new_legs=new_legs,
            reason=reason,
            new_premium_per_unit=new_prem,
            close_cost=front_close_mid,
        )

    def _recentre(self, position, state, front_leg, back_leg, move_pct):
        """Close front at old strike, open new front at current ATM."""
        chain = state.option_chain

        front_close_mid = self._get_mid_by_expiry(
            chain, front_leg.strike, front_leg.option_type, front_leg.expiry_date,
        )
        close_legs = [
            Leg(front_leg.strike, front_leg.option_type, "BUY", front_close_mid, front_leg.expiry_date),
        ]

        new_strike = round(state.underlying_price / 100) * 100
        new_front_mid = self._get_mid_by_expiry(
            chain, new_strike, front_leg.option_type, front_leg.expiry_date,
        )
        new_legs = [
            Leg(new_strike, front_leg.option_type, "SELL", new_front_mid, front_leg.expiry_date),
        ]

        position.metadata["strike"] = new_strike

        back_current = self._get_mid_by_expiry(
            chain, back_leg.strike, back_leg.option_type, back_leg.expiry_date,
        )
        new_prem = -(back_current - new_front_mid)

        return AdjustmentDecision(
            should_adjust=True, action="RECENTRE",
            close_legs=close_legs, new_legs=new_legs,
            reason=f"Underlying moved {move_pct:.1%} from strike {front_leg.strike} — recentring to {new_strike}",
            new_premium_per_unit=new_prem,
            close_cost=front_close_mid,
        )

    def _find_next_expiry_after(self, state: MarketState, current_expiry: datetime) -> datetime | None:
        """Find the nearest expiry date strictly after current_expiry."""
        candidates = []
        for expiry_str in state.expiry_dates:
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if not hasattr(expiry, "hour"):
                    expiry = datetime.combine(expiry, datetime.min.time())
            if expiry > current_expiry:
                candidates.append(expiry)
        return min(candidates) if candidates else None

    @staticmethod
    def _get_iv_by_expiry(chain: dict, strike: int, option_type: str,
                          expiry_date: datetime) -> float:
        """Get IV from chain matching strike + type + expiry."""
        expiry_str = expiry_date.strftime("%Y-%m-%d") if expiry_date else ""
        for rec in chain.get("records", []):
            if rec["strike"] != strike or rec["option_type"] != option_type:
                continue
            rec_expiry = str(rec.get("expiry", ""))[:10]
            if rec_expiry and expiry_str and rec_expiry == expiry_str:
                return rec.get("iv", 0.0)
        return 0.0

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """Cost to close a calendar: sell back-month - buy front-month (remaining value)."""
        chain = state.option_chain
        close_cost = 0.0
        for leg in position.legs:
            current_mid = self._get_mid_by_expiry(chain, leg.strike, leg.option_type, leg.expiry_date)
            if leg.side == "SELL":
                close_cost += current_mid   # buy back short
            else:
                close_cost -= current_mid   # sell long
        return abs(close_cost)  # cost to unwind

    def _position_value(self, position: Position, state: MarketState) -> float:
        """Current net value of the calendar spread."""
        chain = state.option_chain
        value = 0.0
        for leg in position.legs:
            current_mid = self._get_mid_by_expiry(chain, leg.strike, leg.option_type, leg.expiry_date)
            if leg.side == "BUY":
                value += current_mid
            else:
                value -= current_mid
        return value

    # --- Helpers ---

    def _find_dte_in_range(self, state: MarketState, min_dte: int, max_dte: int) -> int | None:
        for expiry_str in sorted(state.expiry_dates):
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if not hasattr(expiry, "hour"):
                    expiry = datetime.combine(expiry, datetime.min.time())
            dte = (expiry - state.date).days
            if min_dte <= dte <= max_dte:
                return dte
        return None

    def _find_expiry(self, state: MarketState, target_dte: int) -> datetime:
        best = None
        best_diff = float("inf")
        for expiry_str in state.expiry_dates:
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if not hasattr(expiry, "hour"):
                    expiry = datetime.combine(expiry, datetime.min.time())
            diff = abs((expiry - state.date).days - target_dte)
            if diff < best_diff:
                best_diff = diff
                best = expiry
        return best

    @staticmethod
    def _get_mid(chain: dict, strike: int, option_type: str) -> float:
        for rec in chain.get("records", []):
            if rec["strike"] == strike and rec["option_type"] == option_type:
                bid = rec.get("bid", rec.get("ltp", 0))
                ask = rec.get("ask", rec.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return rec.get("ltp", 0)
        records = [r for r in chain.get("records", []) if r["option_type"] == option_type]
        if not records:
            return 0.0
        closest = min(records, key=lambda r: abs(r["strike"] - strike))
        return closest.get("ltp", 0)

    @staticmethod
    def _get_mid_by_expiry(chain: dict, strike: int, option_type: str,
                           expiry_date: datetime) -> float:
        """Get mid price matching strike + type + expiry (critical for calendar spreads)."""
        expiry_str = expiry_date.strftime("%Y-%m-%d") if expiry_date else ""

        # First pass: exact match on strike + type + expiry
        for rec in chain.get("records", []):
            if rec["strike"] != strike or rec["option_type"] != option_type:
                continue
            rec_expiry = str(rec.get("expiry", ""))[:10]
            if rec_expiry and expiry_str and rec_expiry == expiry_str:
                bid = rec.get("bid", rec.get("ltp", 0))
                ask = rec.get("ask", rec.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return rec.get("ltp", 0)

        # Second pass: match strike + type + closest expiry date
        if expiry_date:
            matching = [r for r in chain.get("records", [])
                        if r["strike"] == strike and r["option_type"] == option_type]
            if matching:
                # Pick record whose expiry is closest to the leg's expiry
                def expiry_distance(r):
                    r_exp = str(r.get("expiry", ""))[:10]
                    if r_exp:
                        try:
                            r_date = datetime.fromisoformat(r_exp)
                            return abs((r_date - expiry_date).days)
                        except (ValueError, TypeError):
                            pass
                    return abs(r.get("dte", 30) - 30)  # fallback
                best = min(matching, key=expiry_distance)
                bid = best.get("bid", best.get("ltp", 0))
                ask = best.get("ask", best.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return best.get("ltp", 0)

        # Fallback: nearest strike for this option type
        records = [r for r in chain.get("records", []) if r["option_type"] == option_type]
        if not records:
            return 0.0
        closest = min(records, key=lambda r: abs(r["strike"] - strike))
        return closest.get("ltp", 0)

    def _make_exit_legs(self, position: Position, state: MarketState) -> list[Leg]:
        exit_legs = []
        chain = state.option_chain
        for leg in position.legs:
            current_mid = self._get_mid_by_expiry(chain, leg.strike, leg.option_type, leg.expiry_date)
            exit_side = "BUY" if leg.side == "SELL" else "SELL"
            exit_legs.append(Leg(
                strike=leg.strike,
                option_type=leg.option_type,
                side=exit_side,
                premium=current_mid,
                expiry_date=leg.expiry_date,
            ))
        return exit_legs
