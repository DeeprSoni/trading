"""
Strangle-to-IC Conversion Backtest Adapter — sells a naked strangle in
high-VIX environments, then converts to an Iron Condor once 30% profit
is banked (or on emergency 2% move).

Entry: 16-delta short strangle (2 legs, no wings).
Conversion: buy 500-pt wings when profit >= 30% or spot moves 2%+.
Exit: same as IC but with tighter 1.0x stop pre-conversion, 2.0x post.
"""

import logging
from datetime import datetime

from config import settings
from src.iv_calculator import IVCalculator
from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, Leg, MarketState, Position,
)

logger = logging.getLogger(__name__)


class StrangleToICAdapter:
    """
    Strangle-to-IC adapter for the generic backtester.

    Requires elevated VIX (28-35) and IVR >= 35 for entry.
    Opens a naked short strangle, converts to IC on 30% profit or
    emergency 2% spot move.
    """

    def __init__(self, params: dict | None = None, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()
        p = params or {}
        self._params = {
            "short_delta": p.get("short_delta", 0.16),
            "wing_width": p.get("wing_width", 500),
            "min_vix": p.get("min_vix", 28),
            "max_vix": p.get("max_vix", 35),
            "min_iv_rank": p.get("min_iv_rank", 35),
            "min_dte": p.get("min_dte", 30),
            "max_dte": p.get("max_dte", 45),
            "profit_target_pct": p.get("profit_target_pct", 0.50),
            "stop_loss_multiplier": p.get("stop_loss_multiplier", 1.0),   # before conversion
            "converted_stop_loss": p.get("converted_stop_loss", 2.0),     # after conversion
            "conversion_profit_pct": p.get("conversion_profit_pct", 0.30),
            "emergency_wing_move_pct": p.get("emergency_wing_move_pct", 0.02),
            "time_stop_dte": p.get("time_stop_dte", 21),
            "max_open_positions": p.get("max_open_positions", 1),
            "max_pct_capital": p.get("max_pct_capital", settings.IC_MAX_PCT_CAPITAL_PER_TRADE),
            "lot_size": p.get("lot_size", settings.NIFTY_LOT_SIZE),
            "min_premium": p.get("min_premium", 80),  # strangles collect more premium
        }
        self._last_exit_date = None
        self._last_exit_reason = None

    @property
    def name(self) -> str:
        d = self._params["short_delta"]
        w = self._params["wing_width"]
        pt = int(self._params["profit_target_pct"] * 100)
        sl = self._params["stop_loss_multiplier"]
        return f"STRANGLE_d{d}_w{w}_pt{pt}_sl{sl}"

    @property
    def params(self) -> dict:
        return dict(self._params)

    def should_enter(self, state: MarketState) -> bool:
        """Pre-check: VIX band (28-35), IVR >= 35, DTE window, cooldown."""
        p = self._params
        if state.india_vix < p["min_vix"]:
            return False
        if state.india_vix > p["max_vix"]:
            return False
        if state.iv_rank < p["min_iv_rank"]:
            return False
        # Variable cooldown based on exit reason
        if self._last_exit_date:
            cooldown_map = {
                "PROFIT_TARGET": 2,
                "STOP_LOSS": 7,
                "TIME_STOP": 1,
            }
            cooldown_days = cooldown_map.get(self._last_exit_reason, 2)
            if (state.date - self._last_exit_date).days < cooldown_days:
                return False
        dte = self._best_dte(state)
        if dte is None:
            return False
        return True

    def generate_entry(self, state: MarketState) -> EntryDecision:
        """Build short strangle: 2 legs (short call + short put), no wings."""
        p = self._params
        chain = state.option_chain

        dte = self._best_dte(state)
        if dte is None:
            return EntryDecision(False, reason="No expiry in DTE window")

        time_to_expiry = dte / 365.0
        expiry_date = self._find_expiry(state, dte)

        try:
            short_call_strike = self.iv_calc.find_strike_by_delta(
                chain, p["short_delta"], "CE",
                underlying_price=state.underlying_price,
                time_to_expiry_years=time_to_expiry,
            )
            short_put_strike = self.iv_calc.find_strike_by_delta(
                chain, p["short_delta"], "PE",
                underlying_price=state.underlying_price,
                time_to_expiry_years=time_to_expiry,
            )
        except Exception as e:
            return EntryDecision(False, reason=f"Delta strike lookup failed: {e}")

        # Get premiums from chain
        sc_mid = self._get_mid(chain, short_call_strike, "CE")
        sp_mid = self._get_mid(chain, short_put_strike, "PE")

        net_premium = sc_mid + sp_mid
        if net_premium <= 0:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} <= 0")

        if net_premium < p["min_premium"]:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} < min {p['min_premium']}")

        legs = [
            Leg(short_call_strike, "CE", "SELL", sc_mid, expiry_date),
            Leg(short_put_strike, "PE", "SELL", sp_mid, expiry_date),
        ]

        # Naked strangle margin is higher — rough estimate
        margin = net_premium * p["lot_size"] * 3.0

        return EntryDecision(
            should_enter=True,
            legs=legs,
            net_premium_per_unit=net_premium,
            margin_required=margin,
            reason="Strangle entry — all gates passed",
            metadata={
                "short_call_strike": short_call_strike,
                "short_put_strike": short_put_strike,
                "entry_underlying": state.underlying_price,
                "dte_at_entry": dte,
                "iv_rank_at_entry": state.iv_rank,
                "vix_at_entry": state.india_vix,
                "converted": False,
            },
        )

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """Check exit conditions: stop loss > time stop > profit target > expiry.

        Stop loss multiplier depends on whether the position has been
        converted to an IC (metadata 'converted' flag).
        """
        p = self._params
        entry_premium = position.net_premium_per_unit
        close_cost = self.reprice_position(position, state)

        # DTE of any leg (all same expiry)
        expiry = position.legs[0].expiry_date
        dte = (expiry - state.date).days

        # Pick the correct stop loss multiplier
        converted = position.metadata.get("converted", False)
        sl_mult = p["converted_stop_loss"] if converted else p["stop_loss_multiplier"]

        # 1. STOP LOSS (strict > to avoid triggering at entry when sl_mult=1.0)
        stop_threshold = entry_premium * sl_mult
        if close_cost > stop_threshold:
            self._last_exit_date = state.date
            self._last_exit_reason = "STOP_LOSS"
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "STOP_LOSS", "IMMEDIATE",
                f"Close cost {close_cost:.2f} >= {sl_mult}x premium {entry_premium:.2f}",
                stop_threshold, exit_legs,
            )

        # 2. TIME STOP
        if dte <= p["time_stop_dte"]:
            self._last_exit_date = state.date
            self._last_exit_reason = "TIME_STOP"
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "TIME_STOP", "TODAY",
                f"{dte} DTE <= {p['time_stop_dte']} time stop",
                close_cost, exit_legs,
            )

        # 3. PROFIT TARGET
        profit_pct = 1 - (close_cost / entry_premium) if entry_premium > 0 else 0
        if profit_pct >= p["profit_target_pct"]:
            self._last_exit_date = state.date
            self._last_exit_reason = "PROFIT_TARGET"
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "PROFIT_TARGET", "TODAY",
                f"Profit {profit_pct:.0%} >= target {p['profit_target_pct']:.0%}",
                close_cost, exit_legs,
            )

        # 4. EXPIRY (last day)
        if dte <= 0:
            self._last_exit_date = state.date
            self._last_exit_reason = "EXPIRY"
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "EXPIRY", "IMMEDIATE",
                "Position expired", close_cost, exit_legs,
            )

        return ExitDecision(False, "NONE", "MONITOR", "Within parameters", close_cost)

    def should_adjust(self, position: Position, state: MarketState) -> AdjustmentDecision:
        """Check conversion triggers:

        1. Profit conversion: unrealized profit >= 30% AND not yet converted
           -> buy 500-pt wings on both sides.
        2. Emergency wing buy: spot moved 2%+ from entry
           -> buy wings immediately regardless of profit.
        """
        p = self._params
        converted = position.metadata.get("converted", False)

        # Already converted — no further adjustments needed
        if converted:
            return AdjustmentDecision(False, "NONE", reason="Already converted to IC")

        # Limit to one adjustment per day
        last_adj = position.metadata.get("last_adjustment_date")
        if last_adj and last_adj == state.date.isoformat():
            return AdjustmentDecision(False, "NONE", reason="Already adjusted today")

        entry_premium = position.net_premium_per_unit
        close_cost = self.reprice_position(position, state)
        entry_underlying = position.metadata.get("entry_underlying", state.underlying_price)

        # Check emergency wing buy first (higher priority)
        spot_move_pct = abs(state.underlying_price - entry_underlying) / entry_underlying
        if spot_move_pct >= p["emergency_wing_move_pct"]:
            return self._build_wing_adjustment(
                position, state,
                reason=f"Emergency wing buy: spot moved {spot_move_pct:.1%} from entry "
                       f"({entry_underlying:.0f} -> {state.underlying_price:.0f})",
            )

        # Check profit-based conversion
        profit_pct = 1 - (close_cost / entry_premium) if entry_premium > 0 else 0
        if profit_pct >= p["conversion_profit_pct"]:
            return self._build_wing_adjustment(
                position, state,
                reason=f"Profit conversion: {profit_pct:.0%} >= {p['conversion_profit_pct']:.0%} target",
            )

        return AdjustmentDecision(False, "NONE", reason="Strangle: within parameters")

    def _build_wing_adjustment(self, position: Position, state: MarketState,
                                reason: str) -> AdjustmentDecision:
        """Build the wing-buying adjustment legs."""
        p = self._params
        chain = state.option_chain

        # Find the short strikes from position legs
        short_call = None
        short_put = None
        for leg in position.legs:
            if leg.option_type == "CE" and leg.side == "SELL":
                short_call = leg
            elif leg.option_type == "PE" and leg.side == "SELL":
                short_put = leg

        if not short_call or not short_put:
            return AdjustmentDecision(False, "NONE", reason="Incomplete position legs")

        long_call_strike = short_call.strike + p["wing_width"]
        long_put_strike = short_put.strike - p["wing_width"]
        expiry = short_call.expiry_date

        lc_mid = self._get_mid(chain, long_call_strike, "CE")
        lp_mid = self._get_mid(chain, long_put_strike, "PE")

        new_legs = [
            Leg(long_call_strike, "CE", "BUY", lc_mid, expiry),
            Leg(long_put_strike, "PE", "BUY", lp_mid, expiry),
        ]

        wing_cost = lc_mid + lp_mid

        return AdjustmentDecision(
            should_adjust=True,
            action="CONVERT_TO_IC",
            close_legs=[],
            new_legs=new_legs,
            reason=reason,
            close_cost=wing_cost,
        )

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """Calculate cost-to-close: sum of current mid prices for all legs.

        Works for both 2-leg (strangle) and 4-leg (converted IC) positions.
        """
        chain = state.option_chain
        close_cost = 0.0
        for leg in position.legs:
            current_mid = self._get_mid(chain, leg.strike, leg.option_type)
            if leg.side == "SELL":
                close_cost += current_mid   # pay to buy back
            else:
                close_cost -= current_mid   # receive from selling
        return max(close_cost, 0.0)

    # --- Helpers ---

    def _best_dte(self, state: MarketState) -> int | None:
        """Find nearest expiry in the DTE window."""
        p = self._params
        for expiry_str in sorted(state.expiry_dates):
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if not hasattr(expiry, "hour"):
                    expiry = datetime.combine(expiry, datetime.min.time())
            dte = (expiry - state.date).days
            if p["min_dte"] <= dte <= p["max_dte"]:
                return dte
        return None

    def _find_expiry(self, state: MarketState, target_dte: int) -> datetime:
        """Return the actual expiry datetime closest to target_dte."""
        best = None
        best_diff = float("inf")
        for expiry_str in state.expiry_dates:
            if isinstance(expiry_str, str):
                expiry = datetime.fromisoformat(expiry_str)
            else:
                expiry = expiry_str
                if not hasattr(expiry, "hour"):
                    expiry = datetime.combine(expiry, datetime.min.time())
            dte = (expiry - state.date).days
            diff = abs(dte - target_dte)
            if diff < best_diff:
                best_diff = diff
                best = expiry
        return best

    @staticmethod
    def _get_mid(chain: dict, strike: int, option_type: str) -> float:
        """Get mid price from option chain, fallback to LTP then nearest strike."""
        for rec in chain.get("records", []):
            if rec["strike"] == strike and rec["option_type"] == option_type:
                bid = rec.get("bid", rec.get("ltp", 0))
                ask = rec.get("ask", rec.get("ltp", 0))
                if bid > 0 and ask > 0:
                    return (bid + ask) / 2
                return rec.get("ltp", 0)

        # Nearest strike fallback
        records = [r for r in chain.get("records", []) if r["option_type"] == option_type]
        if not records:
            return 0.0
        closest = min(records, key=lambda r: abs(r["strike"] - strike))
        return closest.get("ltp", 0)

    def _make_exit_legs(self, position: Position, state: MarketState) -> list[Leg]:
        """Build exit legs (reverse of entry) with current market prices."""
        exit_legs = []
        chain = state.option_chain
        for leg in position.legs:
            current_mid = self._get_mid(chain, leg.strike, leg.option_type)
            exit_side = "BUY" if leg.side == "SELL" else "SELL"
            exit_legs.append(Leg(
                strike=leg.strike,
                option_type=leg.option_type,
                side=exit_side,
                premium=current_mid,
                expiry_date=leg.expiry_date,
            ))
        return exit_legs
