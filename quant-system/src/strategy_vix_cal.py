"""
VIX Spike Calendar Spread Adapter — enters ATM calendar when VIX spikes
from below 20 to above 25 within 3 trading days.

Rationale: During VIX spikes, the front-month is artificially expensive
relative to the back-month, so the calendar spread is cheap. When VIX
mean-reverts, the spread widens and the position profits.

This is a hedge/opportunistic strategy — no adjustments, just hold or close.
"""

import logging
from datetime import datetime

from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, Leg, MarketState, Position,
)

logger = logging.getLogger(__name__)


class VIXSpikeCalendarAdapter:
    """
    VIX Spike Calendar adapter for the generic backtester.

    Entry: VIX spikes from <20 to >25 within 3 days -> buy back-month ATM call,
           sell front-month ATM call.
    Exit:  VIX mean-reverts below 18, profit target, DTE, large move, or expiry.
    Adjustments: None — this is a hedge trade.
    """

    def __init__(self, params: dict | None = None):
        p = params or {}
        self._params = {
            "vix_spike_threshold": p.get("vix_spike_threshold", 25),
            "vix_pre_spike_max": p.get("vix_pre_spike_max", 20),
            "vix_lookback_days": p.get("vix_lookback_days", 3),
            "vix_mean_revert_exit": p.get("vix_mean_revert_exit", 18),
            "profit_target_pct": p.get("profit_target_pct", 0.35),
            "front_min_dte": p.get("front_min_dte", 20),
            "front_max_dte": p.get("front_max_dte", 45),
            "back_min_dte": p.get("back_min_dte", 60),
            "back_max_dte": p.get("back_max_dte", 90),
            "back_close_dte": p.get("back_close_dte", 25),
            "move_pct_to_close": p.get("move_pct_to_close", 0.04),
            "max_open_positions": p.get("max_open_positions", 1),
            "lot_size": p.get("lot_size", 75),
        }
        # Internal VIX history tracking (MarketState doesn't carry vix_history)
        self._vix_history: list[tuple[datetime, float]] = []

    @property
    def name(self) -> str:
        p = self._params
        spike = int(p["vix_spike_threshold"])
        pre = int(p["vix_pre_spike_max"])
        pt = int(p["profit_target_pct"] * 100)
        return f"VIX_CAL_s{spike}_p{pre}_pt{pt}"

    @property
    def params(self) -> dict:
        return dict(self._params)

    def should_enter(self, state: MarketState) -> bool:
        """
        Entry gate: VIX must have spiked from below pre_spike_max to above
        spike_threshold within the last lookback_days trading days.
        Also requires valid front and back month expiries.
        """
        p = self._params

        # Track VIX history
        self._record_vix(state.date, state.india_vix)

        # Check VIX spike condition
        if not self._is_vix_spike(state.india_vix):
            return False

        # Check both expiry windows available
        front = self._find_dte_in_range(state, p["front_min_dte"], p["front_max_dte"])
        back = self._find_dte_in_range(state, p["back_min_dte"], p["back_max_dte"])
        return front is not None and back is not None

    def generate_entry(self, state: MarketState) -> EntryDecision:
        """Build calendar: buy back-month ATM call, sell front-month ATM call."""
        p = self._params
        chain = state.option_chain

        # ATM strike rounded to nearest 100
        strike = round(state.underlying_price / 100) * 100

        front_dte = self._find_dte_in_range(state, p["front_min_dte"], p["front_max_dte"])
        back_dte = self._find_dte_in_range(state, p["back_min_dte"], p["back_max_dte"])
        if front_dte is None or back_dte is None:
            return EntryDecision(False, reason="Missing front or back month expiry")

        front_expiry = self._find_expiry(state, front_dte)
        back_expiry = self._find_expiry(state, back_dte)

        # Get prices from chain for each expiry
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
        margin = max_loss * 1.5

        return EntryDecision(
            should_enter=True,
            legs=legs,
            net_premium_per_unit=-net_debit,  # negative = debit
            margin_required=margin,
            reason="VIX spike calendar entry — all gates passed",
            metadata={
                "strike": strike,
                "front_dte": front_dte,
                "back_dte": back_dte,
                "entry_trigger": "VIX_SPIKE",
                "entry_vix": state.india_vix,
                "underlying_at_entry": state.underlying_price,
            },
        )

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """
        Exit checks (in priority order):
        1. VIX drops below mean_revert_exit -> take profit (VIX normalised)
        2. Underlying moved > move_pct_to_close -> close
        3. Back month DTE <= back_close_dte -> close
        4. Profit target reached -> close
        5. Front month expired -> forced close
        """
        p = self._params

        # Track VIX
        self._record_vix(state.date, state.india_vix)

        close_cost = self.reprice_position(position, state)
        entry_debit = abs(position.net_premium_per_unit)

        strike = position.metadata.get("strike", position.legs[0].strike)

        # 1. VIX mean reversion exit
        if state.india_vix <= p["vix_mean_revert_exit"]:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "PROFIT_TARGET", "TODAY",
                f"VIX mean-reverted to {state.india_vix:.1f} <= {p['vix_mean_revert_exit']} — close",
                close_cost, exit_legs,
            )

        # 2. Large move
        move_pct = abs(state.underlying_price - strike) / strike if strike > 0 else 0
        if move_pct >= p["move_pct_to_close"]:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "ADJUSTMENT", "IMMEDIATE",
                f"Underlying moved {move_pct:.1%} from strike — close",
                close_cost, exit_legs,
            )

        # 3. Back month DTE check
        back_leg = max(position.legs, key=lambda l: l.expiry_date)
        back_dte = (back_leg.expiry_date - state.date).days
        if back_dte <= p["back_close_dte"]:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "TIME_STOP", "TODAY",
                f"Back month at {back_dte} DTE — close entire position",
                close_cost, exit_legs,
            )

        # 4. Profit target
        if entry_debit > 0:
            current_value = self._position_value(position, state)
            profit_pct = (current_value - entry_debit) / entry_debit
            if profit_pct >= p["profit_target_pct"]:
                exit_legs = self._make_exit_legs(position, state)
                return ExitDecision(
                    True, "PROFIT_TARGET", "TODAY",
                    f"Calendar profit {profit_pct:.0%} >= {p['profit_target_pct']:.0%} target",
                    close_cost, exit_legs,
                )

        # 5. Front month expiry safeguard
        front_leg = min(position.legs, key=lambda l: l.expiry_date)
        front_dte = (front_leg.expiry_date - state.date).days
        if front_dte <= 0:
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "EXPIRY", "IMMEDIATE",
                "Front month expired — forced close",
                close_cost, exit_legs,
            )

        return ExitDecision(False, "NONE", "MONITOR", "Within parameters", close_cost)

    def should_adjust(self, position: Position, state: MarketState) -> AdjustmentDecision:
        """No adjustments — this is a hedge trade, close or hold."""
        # Track VIX even on adjustment check days
        self._record_vix(state.date, state.india_vix)
        return AdjustmentDecision(False, "NONE", reason="VIX spike calendar: no adjustments")

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """Cost to close: sell back-month - buy front-month (remaining value)."""
        chain = state.option_chain
        close_cost = 0.0
        for leg in position.legs:
            current_mid = self._get_mid_by_expiry(
                chain, leg.strike, leg.option_type, leg.expiry_date,
            )
            if leg.side == "SELL":
                close_cost += current_mid   # buy back short
            else:
                close_cost -= current_mid   # sell long
        return abs(close_cost)

    # --- Internal VIX tracking ---

    def _record_vix(self, date: datetime, vix: float) -> None:
        """Append VIX reading, avoiding duplicates for the same date."""
        if self._vix_history and self._vix_history[-1][0] == date:
            return  # already recorded today
        self._vix_history.append((date, vix))

    def _is_vix_spike(self, current_vix: float) -> bool:
        """
        Check if VIX has spiked: current VIX > spike_threshold AND
        VIX was < pre_spike_max within the last lookback_days entries.
        """
        p = self._params
        if current_vix <= p["vix_spike_threshold"]:
            return False

        lookback = p["vix_lookback_days"]
        # Look at the last N entries (excluding the current one which was just appended)
        recent = self._vix_history[-(lookback + 1):-1] if len(self._vix_history) > 1 else []

        for _, vix_val in recent:
            if vix_val < p["vix_pre_spike_max"]:
                return True

        return False

    # --- Helpers (same pattern as CalBacktestAdapter) ---

    def _position_value(self, position: Position, state: MarketState) -> float:
        """Current net value of the calendar spread."""
        chain = state.option_chain
        value = 0.0
        for leg in position.legs:
            current_mid = self._get_mid_by_expiry(
                chain, leg.strike, leg.option_type, leg.expiry_date,
            )
            if leg.side == "BUY":
                value += current_mid
            else:
                value -= current_mid
        return value

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
    def _get_mid_by_expiry(chain: dict, strike: int, option_type: str,
                           expiry_date: datetime) -> float:
        """Get mid price matching strike + type + expiry."""
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
                def expiry_distance(r):
                    r_exp = str(r.get("expiry", ""))[:10]
                    if r_exp:
                        try:
                            r_date = datetime.fromisoformat(r_exp)
                            return abs((r_date - expiry_date).days)
                        except (ValueError, TypeError):
                            pass
                    return abs(r.get("dte", 30) - 30)
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
            current_mid = self._get_mid_by_expiry(
                chain, leg.strike, leg.option_type, leg.expiry_date,
            )
            exit_side = "BUY" if leg.side == "SELL" else "SELL"
            exit_legs.append(Leg(
                strike=leg.strike,
                option_type=leg.option_type,
                side=exit_side,
                premium=current_mid,
                expiry_date=leg.expiry_date,
            ))
        return exit_legs
