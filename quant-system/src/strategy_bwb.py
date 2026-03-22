"""
Broken Wing Butterfly (BWB) Backtest Adapter — bridges to the generic
BacktestStrategy protocol for the backtesting engine.

Put side: sell 2x short puts at 16-delta, buy 1x long put at ATM - 1000 pts (1x2 ratio)
Call side: standard 1x1 call spread (same as IC)
Extra credit from the second short put.
Tighter stop loss: 1.5x original credit (vs IC's 2x).
"""

import logging
from datetime import datetime

from config import settings
from src.iv_calculator import IVCalculator
from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, Leg, MarketState, Position,
)

logger = logging.getLogger(__name__)


class BrokenWingButterflyAdapter:
    """
    Broken Wing Butterfly adapter for the generic backtester.

    Same entry gates as IC (IV rank, VIX, DTE, cooldown).
    Put side: 2x short puts at delta, 1x long put far OTM (ATM - 1000).
    Call side: standard 1x1 call spread.
    Tighter stop loss (1.5x vs IC's 2x).
    """

    def __init__(self, params: dict | None = None, iv_calculator: IVCalculator | None = None):
        self.iv_calc = iv_calculator or IVCalculator()
        p = params or {}
        self._params = {
            "short_delta": p.get("short_delta", settings.IC_SHORT_DELTA),
            "wing_width": p.get("wing_width", settings.IC_WING_WIDTH_POINTS),
            "min_dte": p.get("min_dte", settings.IC_MIN_DTE_ENTRY),
            "max_dte": p.get("max_dte", settings.IC_MAX_DTE_ENTRY),
            "min_iv_rank": p.get("min_iv_rank", settings.IC_MIN_IV_RANK),
            "max_vix": p.get("max_vix", settings.VIX_MAX_FOR_IC),
            "profit_target_pct": p.get("profit_target_pct", settings.IC_PROFIT_TARGET_PCT),
            "stop_loss_multiplier": p.get("stop_loss_multiplier", 1.5),  # Tighter than IC's 2.0
            "time_stop_dte": p.get("time_stop_dte", settings.IC_TIME_STOP_DTE),
            "max_open_positions": p.get("max_open_positions", settings.IC_MAX_OPEN_POSITIONS),
            "max_pct_capital": p.get("max_pct_capital", settings.IC_MAX_PCT_CAPITAL_PER_TRADE),
            "lot_size": p.get("lot_size", settings.NIFTY_LOT_SIZE),
            "min_premium": p.get("min_premium", 50),
            "bwb_put_ratio": p.get("bwb_put_ratio", 2),  # 2x short puts
            "bwb_long_put_offset": p.get("bwb_long_put_offset", 1000),  # ATM - 1000 pts
        }
        self._last_exit_date = None

    @property
    def name(self) -> str:
        d = self._params["short_delta"]
        w = self._params["wing_width"]
        pt = int(self._params["profit_target_pct"] * 100)
        sl = self._params["stop_loss_multiplier"]
        return f"BWB_d{d}_w{w}_pt{pt}_sl{sl}"

    @property
    def params(self) -> dict:
        return dict(self._params)

    def should_enter(self, state: MarketState) -> bool:
        """Same entry gates as IC: IV rank, VIX, DTE window, and cooldown."""
        p = self._params
        if state.iv_rank < p["min_iv_rank"]:
            return False
        if state.india_vix > p["max_vix"]:
            return False
        if self._last_exit_date and (state.date - self._last_exit_date).days < 5:
            return False
        dte = self._best_dte(state)
        if dte is None:
            return False
        return True

    def generate_entry(self, state: MarketState) -> EntryDecision:
        """
        Build BWB legs:
        - 2x short puts at delta (SELL)
        - 1x long put at ATM - bwb_long_put_offset (BUY)
        - 1x short call at delta (SELL)
        - 1x long call at short_call + wing_width (BUY)
        Total: 5 legs
        """
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

        long_call_strike = short_call_strike + p["wing_width"]
        # Long put: ATM - offset (far OTM, cheap protection)
        atm_strike = round(state.underlying_price / 100) * 100
        long_put_strike = atm_strike - p["bwb_long_put_offset"]

        # Get premiums
        sc_mid = self._get_mid(chain, short_call_strike, "CE")
        sp_mid = self._get_mid(chain, short_put_strike, "PE")
        lc_mid = self._get_mid(chain, long_call_strike, "CE")
        lp_mid = self._get_mid(chain, long_put_strike, "PE")

        put_ratio = p["bwb_put_ratio"]

        # Net premium: 2x short puts + 1x short call - 1x long put - 1x long call
        net_premium = (put_ratio * sp_mid) + sc_mid - lp_mid - lc_mid
        if net_premium <= 0:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} <= 0")
        if net_premium < p["min_premium"]:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} < min {p['min_premium']}")

        # Max loss: worst case on put side = (short_put - long_put) * ratio concern
        # But BWB has asymmetric risk; use call side wing as simpler bound
        max_loss_call = (p["wing_width"] - (sc_mid - lc_mid)) * p["lot_size"]
        max_loss_put = (short_put_strike - long_put_strike - (put_ratio * sp_mid - lp_mid)) * p["lot_size"]
        max_loss_per_lot = max(max_loss_call, max_loss_put, 0)

        max_allowed = settings.TOTAL_CAPITAL * p["max_pct_capital"]
        if max_loss_per_lot > max_allowed:
            return EntryDecision(False, reason=f"Max loss {max_loss_per_lot:.0f} > limit {max_allowed:.0f}")

        # Build legs: 2 short puts, 1 long put, 1 short call, 1 long call = 5 legs
        legs = [
            Leg(short_put_strike, "PE", "SELL", sp_mid, expiry_date),      # short put 1
            Leg(short_put_strike, "PE", "SELL", sp_mid, expiry_date),      # short put 2
            Leg(long_put_strike, "PE", "BUY", lp_mid, expiry_date),        # long put
            Leg(short_call_strike, "CE", "SELL", sc_mid, expiry_date),     # short call
            Leg(long_call_strike, "CE", "BUY", lc_mid, expiry_date),      # long call
        ]

        margin = max_loss_per_lot * 1.10

        return EntryDecision(
            should_enter=True,
            legs=legs,
            net_premium_per_unit=net_premium,
            margin_required=margin,
            reason="BWB entry — all gates passed",
            metadata={
                "short_call_strike": short_call_strike,
                "short_put_strike": short_put_strike,
                "long_call_strike": long_call_strike,
                "long_put_strike": long_put_strike,
                "dte_at_entry": dte,
                "iv_rank_at_entry": state.iv_rank,
                "vix_at_entry": state.india_vix,
                "max_loss_per_lot": max_loss_per_lot,
                "bwb_put_ratio": put_ratio,
            },
        )

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """Check exit conditions: stop loss > time stop > profit target."""
        p = self._params
        entry_premium = position.net_premium_per_unit
        close_cost = self.reprice_position(position, state)

        expiry = position.legs[0].expiry_date
        dte = (expiry - state.date).days

        # 1. STOP LOSS — 1.5x original credit (tighter than IC)
        stop_threshold = entry_premium * p["stop_loss_multiplier"]
        if close_cost >= stop_threshold:
            self._last_exit_date = state.date
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "STOP_LOSS", "IMMEDIATE",
                f"Close cost {close_cost:.2f} >= {p['stop_loss_multiplier']}x premium {entry_premium:.2f}",
                stop_threshold, exit_legs,
            )

        # 2. TIME STOP
        if dte <= p["time_stop_dte"]:
            self._last_exit_date = state.date
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
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "PROFIT_TARGET", "TODAY",
                f"Profit {profit_pct:.0%} >= target {p['profit_target_pct']:.0%}",
                close_cost, exit_legs,
            )

        # 4. EXPIRY
        if dte <= 0:
            self._last_exit_date = state.date
            exit_legs = self._make_exit_legs(position, state)
            return ExitDecision(
                True, "EXPIRY", "IMMEDIATE",
                "Position expired", close_cost, exit_legs,
            )

        return ExitDecision(False, "NONE", "MONITOR", "Within parameters", close_cost)

    def should_adjust(self, position: Position, state: MarketState) -> AdjustmentDecision:
        """BWB adjustment — simple: no adjustments beyond exit logic."""
        return AdjustmentDecision(False, "NONE", reason="BWB: no mid-trade adjustments")

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """Calculate cost-to-close for BWB position."""
        chain = state.option_chain
        close_cost = 0.0
        for leg in position.legs:
            current_mid = self._get_mid(chain, leg.strike, leg.option_type)
            if leg.side == "SELL":
                close_cost += current_mid
            else:
                close_cost -= current_mid
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
