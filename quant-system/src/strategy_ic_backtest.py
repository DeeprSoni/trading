"""
Iron Condor Backtest Adapter — bridges IronCondorStrategy to the generic
BacktestStrategy protocol for the backtesting engine.

Parameterised: accepts overrides for delta, wing width, DTE range, profit
target, stop loss, and all entry gates so the parameter sweep can test
thousands of variations.
"""

import logging
from datetime import datetime

import pandas as pd

from config import settings
from src.iv_calculator import IVCalculator
from src.models import (
    AdjustmentDecision, EntryDecision, ExitDecision, Leg, MarketState, Position,
)
from src.adjustments_ic import (
    evaluate_ic_adjustment, ICPosition, ICAdjustmentConfig, ICAdjustment,
)
from src.strategy_ic import detect_regime, get_skewed_deltas

logger = logging.getLogger(__name__)


class ICBacktestAdapter:
    """
    Iron Condor adapter for the generic backtester.

    All parameters are overridable so the sweep engine can test
    arbitrary combinations without touching strategy code.
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
            "stop_loss_multiplier": p.get("stop_loss_multiplier", settings.IC_STOP_LOSS_MULTIPLIER),
            "time_stop_dte": p.get("time_stop_dte", settings.IC_TIME_STOP_DTE),
            "max_open_positions": p.get("max_open_positions", settings.IC_MAX_OPEN_POSITIONS),
            "max_pct_capital": p.get("max_pct_capital", settings.IC_MAX_PCT_CAPITAL_PER_TRADE),
            "lot_size": p.get("lot_size", settings.NIFTY_LOT_SIZE),  # 75 (updated from 25)
            "min_premium": p.get("min_premium", 50),  # Min viable: Rs 50/unit covers costs at 4 legs * ~Rs 350/leg
            "regime_skew": p.get("regime_skew", False),
        }
        self._last_exit_date = None  # cooldown tracking
        self._last_exit_reason = None  # for variable cooldown
        self._spot_history = []

    @property
    def name(self) -> str:
        d = self._params["short_delta"]
        w = self._params["wing_width"]
        pt = int(self._params["profit_target_pct"] * 100)
        sl = self._params["stop_loss_multiplier"]
        return f"IC_d{d}_w{w}_pt{pt}_sl{sl}"

    @property
    def params(self) -> dict:
        return dict(self._params)

    def should_enter(self, state: MarketState) -> bool:
        """Quick pre-check: IV rank, VIX, DTE window, and cooldown."""
        self._spot_history.append(state.underlying_price)
        p = self._params
        if state.iv_rank < p["min_iv_rank"]:
            return False
        if state.india_vix > p["max_vix"]:
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
        """Build IC legs from the option chain using parameterised delta/width."""
        p = self._params
        chain = state.option_chain

        dte = self._best_dte(state)
        if dte is None:
            return EntryDecision(False, reason="No expiry in DTE window")

        time_to_expiry = dte / 365.0

        # Find target expiry date
        expiry_date = self._find_expiry(state, dte)

        # Determine deltas: regime-skewed or symmetric
        call_delta = p["short_delta"]
        put_delta = p["short_delta"]
        regime = "NEUTRAL"
        if p["regime_skew"] and len(self._spot_history) >= 50:
            regime = detect_regime(pd.Series(self._spot_history))
            call_delta, put_delta = get_skewed_deltas(regime, p["short_delta"])

        try:
            short_call_strike = self.iv_calc.find_strike_by_delta(
                chain, call_delta, "CE",
                underlying_price=state.underlying_price,
                time_to_expiry_years=time_to_expiry,
            )
            short_put_strike = self.iv_calc.find_strike_by_delta(
                chain, put_delta, "PE",
                underlying_price=state.underlying_price,
                time_to_expiry_years=time_to_expiry,
            )
        except Exception as e:
            return EntryDecision(False, reason=f"Delta strike lookup failed: {e}")

        long_call_strike = short_call_strike + p["wing_width"]
        long_put_strike = short_put_strike - p["wing_width"]

        # Get premiums from chain
        sc_mid = self._get_mid(chain, short_call_strike, "CE")
        sp_mid = self._get_mid(chain, short_put_strike, "PE")
        lc_mid = self._get_mid(chain, long_call_strike, "CE")
        lp_mid = self._get_mid(chain, long_put_strike, "PE")

        net_premium = sc_mid + sp_mid - lc_mid - lp_mid
        if net_premium <= 0:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} <= 0")

        if net_premium < p["min_premium"]:
            return EntryDecision(False, reason=f"Net premium {net_premium:.2f} < min {p['min_premium']}")

        max_loss_per_lot = (p["wing_width"] - net_premium) * p["lot_size"]
        max_allowed = settings.TOTAL_CAPITAL * p["max_pct_capital"]
        if max_loss_per_lot > max_allowed:
            return EntryDecision(False, reason=f"Max loss {max_loss_per_lot:.0f} > limit {max_allowed:.0f}")

        legs = [
            Leg(short_call_strike, "CE", "SELL", sc_mid, expiry_date),
            Leg(short_put_strike, "PE", "SELL", sp_mid, expiry_date),
            Leg(long_call_strike, "CE", "BUY", lc_mid, expiry_date),
            Leg(long_put_strike, "PE", "BUY", lp_mid, expiry_date),
        ]

        # Rough margin estimate: max_loss + 10% buffer
        margin = max_loss_per_lot * 1.10

        return EntryDecision(
            should_enter=True,
            legs=legs,
            net_premium_per_unit=net_premium,
            margin_required=margin,
            reason="IC entry — all gates passed",
            metadata={
                "short_call_strike": short_call_strike,
                "short_put_strike": short_put_strike,
                "long_call_strike": long_call_strike,
                "long_put_strike": long_put_strike,
                "dte_at_entry": dte,
                "iv_rank_at_entry": state.iv_rank,
                "vix_at_entry": state.india_vix,
                "max_loss_per_lot": max_loss_per_lot,
                "regime": regime,
            },
        )

    def should_exit(self, position: Position, state: MarketState) -> ExitDecision:
        """Check exit conditions: stop loss > time stop > profit target."""
        p = self._params
        entry_premium = position.net_premium_per_unit
        close_cost = self.reprice_position(position, state)

        # DTE of any leg (all same expiry for IC)
        expiry = position.legs[0].expiry_date
        dte = (expiry - state.date).days

        # 1. STOP LOSS — cap at stop level (real system monitors intraday every 60s)
        stop_threshold = entry_premium * p["stop_loss_multiplier"]
        if close_cost >= stop_threshold:
            self._last_exit_date = state.date
            self._last_exit_reason = "STOP_LOSS"
            exit_legs = self._make_exit_legs(position, state)
            # Use capped close cost: real system would exit at exactly the
            # stop threshold via intraday monitoring, not at end-of-day price
            return ExitDecision(
                True, "STOP_LOSS", "IMMEDIATE",
                f"Close cost {close_cost:.2f} >= {p['stop_loss_multiplier']}x premium {entry_premium:.2f}",
                stop_threshold, exit_legs,
            )

        # 2. TIME STOP — check for roll-for-duration before exiting
        if dte <= p["time_stop_dte"]:
            # Roll for duration: if profitable AND not rolled yet, defer to should_adjust
            if (close_cost < entry_premium
                    and position.metadata.get("duration_rolls", 0) == 0):
                # Don't exit — let should_adjust handle the ROLL_FOR_DURATION
                pass
            else:
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
        """IC adjustment logic — v2 engine handles all adjustments.

        DTE < 10 → hard close (gamma risk, handled here before v2)
        All other adjustments: delegated to adjustments_ic.evaluate_ic_adjustment()
        """
        chain = state.option_chain
        expiry = position.legs[0].expiry_date
        dte = (expiry - state.date).days

        # Limit to one adjustment per day
        last_adj = position.metadata.get("last_adjustment_date")
        if last_adj and last_adj == state.date.isoformat():
            return AdjustmentDecision(False, "NONE", reason="Already adjusted today")

        # Roll for duration: at time stop, profitable, not yet rolled
        entry_premium = position.net_premium_per_unit
        close_cost = self.reprice_position(position, state)
        if (dte <= self._params["time_stop_dte"]
                and close_cost < entry_premium
                and position.metadata.get("duration_rolls", 0) == 0):
            # Close current and roll to next monthly expiry
            close_legs = self._make_exit_legs(position, state)
            return AdjustmentDecision(
                should_adjust=True, action="ROLL_FOR_DURATION",
                close_legs=close_legs, new_legs=[],
                reason=f"DTE {dte} <= {self._params['time_stop_dte']} but profitable — rolling for duration",
                close_cost=close_cost,
            )

        # DTE < 10: hard close — gamma risk too high for any adjustment
        if dte < 10:
            close_legs = self._make_exit_legs(position, state)
            close_cost = self.reprice_position(position, state)
            return AdjustmentDecision(
                should_adjust=True, action="CLOSE",
                close_legs=close_legs, new_legs=[],
                reason=f"DTE {dte} < 10 — gamma risk, hard close",
                close_cost=close_cost,
            )

        # Identify legs by role
        short_call = short_put = long_call = long_put = None
        for leg in position.legs:
            if leg.option_type == "CE" and leg.side == "SELL":
                short_call = leg
            elif leg.option_type == "PE" and leg.side == "SELL":
                short_put = leg
            elif leg.option_type == "CE" and leg.side == "BUY":
                long_call = leg
            elif leg.option_type == "PE" and leg.side == "BUY":
                long_put = leg

        if not all([short_call, short_put, long_call, long_put]):
            return AdjustmentDecision(False, "NONE", reason="IC: incomplete legs")

        # All adjustments via v2 engine
        v2_result = self._check_v2_adjustments(
            position, state, short_call, short_put, long_call, long_put, dte,
        )
        if v2_result.should_adjust:
            return v2_result

        return AdjustmentDecision(False, "NONE", reason="IC: within parameters")

    def _build_ic_position(
        self, position: Position, state: MarketState,
        short_call, short_put, long_call, long_put,
    ) -> ICPosition:
        """Construct ICPosition from Position legs + current chain prices."""
        chain = state.option_chain

        sc_curr = self._get_mid(chain, short_call.strike, "CE")
        sp_curr = self._get_mid(chain, short_put.strike, "PE")
        lc_curr = self._get_mid(chain, long_call.strike, "CE")
        lp_curr = self._get_mid(chain, long_put.strike, "PE")

        call_spread_orig = short_call.premium - long_call.premium
        put_spread_orig = short_put.premium - long_put.premium
        call_spread_curr = sc_curr - lc_curr
        put_spread_curr = sp_curr - lp_curr

        return ICPosition(
            symbol="NIFTY",
            entry_date=position.entry_date,
            expiry_date=position.legs[0].expiry_date,
            original_credit=position.net_premium_per_unit,
            call_spread_original_credit=max(call_spread_orig, 0),
            put_spread_original_credit=max(put_spread_orig, 0),
            call_spread_current_value=max(call_spread_curr, 0),
            put_spread_current_value=max(put_spread_curr, 0),
            long_call_value=lc_curr,
            long_put_value=lp_curr,
            short_call_strike=short_call.strike,
            short_put_strike=short_put.strike,
            untested_rolls_done=position.metadata.get("untested_rolls_done", 0),
            tested_rolls_done=position.metadata.get("tested_rolls_done", 0),
            call_side_closed=position.metadata.get("call_side_closed", False),
            put_side_closed=position.metadata.get("put_side_closed", False),
            wings_removed=position.metadata.get("wings_removed", False),
        )

    def _check_v2_adjustments(
        self, position, state, short_call, short_put, long_call, long_put, dte,
    ) -> AdjustmentDecision:
        """Check v2 adjustment types: wing removal, partial close, defensive roll, iron fly."""
        ic_pos = self._build_ic_position(
            position, state, short_call, short_put, long_call, long_put,
        )

        chain = state.option_chain
        # Get deltas for short strikes
        sc_delta = self._get_leg_delta(chain, short_call, state, dte)
        sp_delta = self._get_leg_delta(chain, short_put, state, dte)

        # Skip stop/profit/time checks (handled by should_exit + DTE<10 above)
        # But enable all v2 adjustment types including defensive roll and partial close
        cfg = ICAdjustmentConfig(
            stop_loss_multiplier=999.0,   # handled by should_exit
            profit_target_pct=999.0,      # handled by should_exit
            time_stop_dte=0,              # handled by should_exit
        )

        action = evaluate_ic_adjustment(
            ic_pos, state.underlying_price, sc_delta, sp_delta, dte, cfg,
        )

        if action == ICAdjustment.NONE:
            return AdjustmentDecision(False, "NONE")

        return self._map_v2_adjustment(
            action, position, state, ic_pos,
            short_call, short_put, long_call, long_put, dte,
        )

    def _get_leg_delta(self, chain, leg, state, dte) -> float:
        """Get absolute delta for a leg from chain or via BS calculation."""
        for rec in chain.get("records", []):
            if rec["strike"] == leg.strike and rec["option_type"] == leg.option_type:
                if "delta" in rec and rec["delta"] != 0:
                    return abs(rec["delta"])
        # Fallback: compute via BS
        iv = 0.20
        for rec in chain.get("records", []):
            if rec["strike"] == leg.strike and rec["option_type"] == leg.option_type:
                iv = rec.get("iv", 0.20)
                if isinstance(iv, str) or iv <= 0:
                    iv = 0.20
                if iv > 1.0:
                    iv = iv / 100
                break
        T = max(dte / 365.0, 0.001)
        delta = self.iv_calc._bs_delta(state.underlying_price, leg.strike, T, 0.065, iv, leg.option_type)
        return abs(delta)

    def _map_v2_adjustment(
        self, action, position, state, ic_pos,
        short_call, short_put, long_call, long_put, dte,
    ) -> AdjustmentDecision:
        """Map ICAdjustment enum to AdjustmentDecision with close_legs/new_legs."""
        chain = state.option_chain
        expiry = position.legs[0].expiry_date

        if action == ICAdjustment.WING_REMOVAL:
            # Close both long wings, keep short legs
            lc_mid = self._get_mid(chain, long_call.strike, "CE")
            lp_mid = self._get_mid(chain, long_put.strike, "PE")
            close_legs = [
                Leg(long_call.strike, "CE", "SELL", lc_mid, expiry),
                Leg(long_put.strike, "PE", "SELL", lp_mid, expiry),
            ]
            return AdjustmentDecision(
                should_adjust=True, action="WING_REMOVAL",
                close_legs=close_legs, new_legs=[],
                reason=f"DTE {dte} — wings nearly dead, removing to free margin",
                close_cost=0.0,
            )

        if action == ICAdjustment.PARTIAL_CLOSE_WINNER:
            # Close whichever side is at 80%+ profit
            if ic_pos.call_spread_profit_pct >= 0.80:
                sc_mid = self._get_mid(chain, short_call.strike, "CE")
                lc_mid = self._get_mid(chain, long_call.strike, "CE")
                close_legs = [
                    Leg(short_call.strike, "CE", "BUY", sc_mid, expiry),
                    Leg(long_call.strike, "CE", "SELL", lc_mid, expiry),
                ]
                return AdjustmentDecision(
                    should_adjust=True, action="PARTIAL_CLOSE_WINNER",
                    close_legs=close_legs, new_legs=[],
                    reason=f"Call side at {ic_pos.call_spread_profit_pct:.0%} profit — closing winner",
                    close_cost=sc_mid - lc_mid,
                )
            else:
                sp_mid = self._get_mid(chain, short_put.strike, "PE")
                lp_mid = self._get_mid(chain, long_put.strike, "PE")
                close_legs = [
                    Leg(short_put.strike, "PE", "BUY", sp_mid, expiry),
                    Leg(long_put.strike, "PE", "SELL", lp_mid, expiry),
                ]
                return AdjustmentDecision(
                    should_adjust=True, action="PARTIAL_CLOSE_WINNER",
                    close_legs=close_legs, new_legs=[],
                    reason=f"Put side at {ic_pos.put_spread_profit_pct:.0%} profit — closing winner",
                    close_cost=sp_mid - lp_mid,
                )

        if action == ICAdjustment.ROLL_UNTESTED_INWARD:
            # Roll the untested side inward for fresh credit
            call_distance = short_call.strike - state.underlying_price
            put_distance = state.underlying_price - short_put.strike
            if call_distance > put_distance:
                # Call side is untested — roll it inward
                return self._roll_call_side(
                    position, state, short_call, long_call, short_put, long_put,
                )
            else:
                return self._roll_put_side(
                    position, state, short_call, long_call, short_put, long_put,
                )

        if action == ICAdjustment.DEFENSIVE_ROLL:
            # Roll the tested side further out
            sc_delta = self._get_leg_delta(chain, short_call, state, dte)
            sp_delta = self._get_leg_delta(chain, short_put, state, dte)
            if sc_delta > sp_delta:
                return self._roll_call_side(
                    position, state, short_call, long_call, short_put, long_put,
                )
            else:
                return self._roll_put_side(
                    position, state, short_call, long_call, short_put, long_put,
                )

        if action == ICAdjustment.IRON_FLY_CONVERSION:
            # Close current IC, open iron fly at ATM
            close_legs = self._make_exit_legs(position, state)
            close_cost = self.reprice_position(position, state)
            return AdjustmentDecision(
                should_adjust=True, action="IRON_FLY_CONVERSION",
                close_legs=close_legs, new_legs=[],
                reason="Spot at short strike — converting to iron fly (closing IC)",
                close_cost=close_cost,
            )

        return AdjustmentDecision(False, "NONE")

    def _roll_call_side(self, position, state, short_call, long_call, short_put, long_put):
        """Roll call spread 500 pts higher. Optionally harvest put side."""
        p = self._params
        chain = state.option_chain
        expiry = short_call.expiry_date

        sc_mid = self._get_mid(chain, short_call.strike, "CE")
        lc_mid = self._get_mid(chain, long_call.strike, "CE")

        close_legs = [
            Leg(short_call.strike, "CE", "BUY", sc_mid, expiry),
            Leg(long_call.strike, "CE", "SELL", lc_mid, expiry),
        ]

        new_sc_strike = short_call.strike + 500
        new_lc_strike = new_sc_strike + p["wing_width"]
        new_sc_mid = self._get_mid(chain, new_sc_strike, "CE")
        new_lc_mid = self._get_mid(chain, new_lc_strike, "CE")

        new_legs = [
            Leg(new_sc_strike, "CE", "SELL", new_sc_mid, expiry),
            Leg(new_lc_strike, "CE", "BUY", new_lc_mid, expiry),
        ]

        # Asymmetric harvest: if put side at 85%+ profit, close it
        put_entry_prem = short_put.premium - long_put.premium
        sp_mid = self._get_mid(chain, short_put.strike, "PE")
        lp_mid = self._get_mid(chain, long_put.strike, "PE")
        put_close_cost = sp_mid - lp_mid

        harvested = False
        if put_entry_prem > 0 and put_close_cost >= 0:
            put_profit_pct = 1 - (put_close_cost / put_entry_prem)
            if put_profit_pct >= 0.85:
                close_legs.extend([
                    Leg(short_put.strike, "PE", "BUY", sp_mid, expiry),
                    Leg(long_put.strike, "PE", "SELL", lp_mid, expiry),
                ])
                harvested = True

        new_prem = new_sc_mid - new_lc_mid
        if not harvested:
            new_prem += short_put.premium - long_put.premium

        return AdjustmentDecision(
            should_adjust=True, action="ROLL_CALL_SIDE",
            close_legs=close_legs, new_legs=new_legs,
            reason=f"Call tested: short {short_call.strike} within 300 of {state.underlying_price:.0f}, rolling up 500"
                   + (", harvesting put side" if harvested else ""),
            new_premium_per_unit=new_prem,
            close_cost=sc_mid - lc_mid,
        )

    def _roll_put_side(self, position, state, short_call, long_call, short_put, long_put):
        """Roll put spread 500 pts lower. Optionally harvest call side."""
        p = self._params
        chain = state.option_chain
        expiry = short_put.expiry_date

        sp_mid = self._get_mid(chain, short_put.strike, "PE")
        lp_mid = self._get_mid(chain, long_put.strike, "PE")

        close_legs = [
            Leg(short_put.strike, "PE", "BUY", sp_mid, expiry),
            Leg(long_put.strike, "PE", "SELL", lp_mid, expiry),
        ]

        new_sp_strike = short_put.strike - 500
        new_lp_strike = new_sp_strike - p["wing_width"]
        new_sp_mid = self._get_mid(chain, new_sp_strike, "PE")
        new_lp_mid = self._get_mid(chain, new_lp_strike, "PE")

        new_legs = [
            Leg(new_sp_strike, "PE", "SELL", new_sp_mid, expiry),
            Leg(new_lp_strike, "PE", "BUY", new_lp_mid, expiry),
        ]

        # Asymmetric harvest: if call side at 85%+ profit, close it
        call_entry_prem = short_call.premium - long_call.premium
        sc_mid = self._get_mid(chain, short_call.strike, "CE")
        lc_mid = self._get_mid(chain, long_call.strike, "CE")
        call_close_cost = sc_mid - lc_mid

        harvested = False
        if call_entry_prem > 0 and call_close_cost >= 0:
            call_profit_pct = 1 - (call_close_cost / call_entry_prem)
            if call_profit_pct >= 0.85:
                close_legs.extend([
                    Leg(short_call.strike, "CE", "BUY", sc_mid, expiry),
                    Leg(long_call.strike, "CE", "SELL", lc_mid, expiry),
                ])
                harvested = True

        new_prem = new_sp_mid - new_lp_mid
        if not harvested:
            new_prem += short_call.premium - long_call.premium

        return AdjustmentDecision(
            should_adjust=True, action="ROLL_PUT_SIDE",
            close_legs=close_legs, new_legs=new_legs,
            reason=f"Put tested: short {short_put.strike} within 300 of {state.underlying_price:.0f}, rolling down 500"
                   + (", harvesting call side" if harvested else ""),
            new_premium_per_unit=new_prem,
            close_cost=sp_mid - lp_mid,
        )

    def reprice_position(self, position: Position, state: MarketState) -> float:
        """
        Calculate cost-to-close: sum of current mid prices for closing each leg.
        For a credit spread, this is what you'd pay to buy back shorts minus
        what you'd receive selling longs.
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
