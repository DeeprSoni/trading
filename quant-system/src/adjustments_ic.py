"""
Iron Condor Adjustment Engine v2.0

Adjustment priority (checked in this exact order each day):

  1. Emergency stop loss        — 2× original credit, IMMEDIATE exit
  2. Profit target close        — 50% total IC profit, close whole IC
  3. Time stop                  — 21 DTE, close all
  4. Wing removal               — DTE ≤ 7 AND both wings < Rs 3 (free up margin)
  5. Partial close (one side)   — Either spread at 80% profit, close just that half
  6. Roll untested side inward  — Untested at 80% profit, collect fresh credit
  7. Defensive roll             — Tested short delta ≥ 0.30, roll out in time
  8. Convert to iron butterfly  — Spot within 50 pts of short strike, DTE ≥ 12
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class ICAdjustment(Enum):
    NONE                  = "none"
    EMERGENCY_STOP        = "emergency_stop"
    PROFIT_TARGET         = "profit_target"
    TIME_STOP             = "time_stop"
    WING_REMOVAL          = "wing_removal"
    PARTIAL_CLOSE_WINNER  = "partial_close_winner"
    ROLL_UNTESTED_INWARD  = "roll_untested_inward"
    DEFENSIVE_ROLL        = "defensive_roll"
    IRON_FLY_CONVERSION   = "iron_fly_conversion"


@dataclass
class ICAdjustmentConfig:
    # Stop loss
    stop_loss_multiplier: float  = 2.0    # 2× original credit = full stop

    # Profit target (whole IC)
    profit_target_pct: float     = 0.50   # 50% of original credit

    # Time stop
    time_stop_dte: int           = 21

    # Wing removal (near expiry)
    wing_removal_dte_max: int    = 7
    wing_removal_value_max: float= 3.0    # Rs 3 per wing

    # Partial close (one side winner)
    partial_close_pct: float     = 0.80   # 80% profit on one spread

    # Credit harvest (untested side roll inward)
    untested_profit_pct: float   = 0.80   # Roll untested when at 80% profit
    min_roll_credit: float       = 10.0   # Must collect at least Rs 10 net credit
    max_rolls_per_side: int      = 1      # Never roll same leg twice

    # Defensive roll (tested side)
    defensive_delta_trigger: float = 0.30 # Short strike delta threshold

    # Iron fly conversion
    iron_fly_min_dte: int        = 12
    iron_fly_spot_distance: float= 50.0   # Points from short strike


@dataclass
class ICPosition:
    """Represents one live IC position with state tracking."""
    symbol: str
    entry_date: object
    expiry_date: object
    original_credit: float            # Total credit collected at entry (Rs)

    # Current values (updated daily by backtester)
    call_spread_original_credit: float = 0.0
    put_spread_original_credit:  float = 0.0
    call_spread_current_value:   float = 0.0
    put_spread_current_value:    float = 0.0
    long_call_value:  float = 0.0
    long_put_value:   float = 0.0

    # Short strike prices
    short_call_strike: float = 0.0
    short_put_strike:  float = 0.0

    # Roll tracking
    untested_rolls_done: int = 0
    tested_rolls_done:   int = 0
    call_side_closed: bool   = False
    put_side_closed: bool    = False
    wings_removed: bool      = False

    @property
    def current_total_value(self) -> float:
        return self.call_spread_current_value + self.put_spread_current_value

    @property
    def unrealized_profit(self) -> float:
        return self.original_credit - self.current_total_value

    @property
    def call_spread_profit_pct(self) -> float:
        if self.call_spread_original_credit <= 0:
            return 0.0
        return 1 - self.call_spread_current_value / self.call_spread_original_credit

    @property
    def put_spread_profit_pct(self) -> float:
        if self.put_spread_original_credit <= 0:
            return 0.0
        return 1 - self.put_spread_current_value / self.put_spread_original_credit

    def untested_side_profit_pct(self, spot: float) -> float:
        """Profit % of whichever side the market has moved away from."""
        call_distance = self.short_call_strike - spot
        put_distance  = spot - self.short_put_strike
        if call_distance > put_distance:
            return self.call_spread_profit_pct   # Market below mid; call side untested
        return self.put_spread_profit_pct


def evaluate_ic_adjustment(
    position: ICPosition,
    spot: float,
    short_call_delta: float,
    short_put_delta: float,
    dte: int,
    cfg: ICAdjustmentConfig | None = None,
) -> ICAdjustment:
    """
    Evaluate what adjustment (if any) to execute on this IC today.
    Returns the ICAdjustment enum value.

    Call this once per trading day per position.

    Parameters:
      position         : current ICPosition object with updated values
      spot             : current underlying spot price
      short_call_delta : delta of the short call (positive, 0–1)
      short_put_delta  : delta of the short put  (positive, 0–1)
      dte              : calendar days to expiry
      cfg              : adjustment config (defaults to ICAdjustmentConfig())
    """
    if cfg is None:
        cfg = ICAdjustmentConfig()

    credit = position.original_credit
    value  = position.current_total_value

    # ── 1. Emergency stop ────────────────────────────────────────────────────
    if value >= credit * cfg.stop_loss_multiplier:
        logger.debug("IC adjust: EMERGENCY_STOP")
        return ICAdjustment.EMERGENCY_STOP

    # ── 2. Profit target ─────────────────────────────────────────────────────
    profit_pct = position.unrealized_profit / credit if credit > 0 else 0
    if profit_pct >= cfg.profit_target_pct:
        logger.debug("IC adjust: PROFIT_TARGET")
        return ICAdjustment.PROFIT_TARGET

    # ── 3. Time stop ─────────────────────────────────────────────────────────
    if dte <= cfg.time_stop_dte:
        logger.debug("IC adjust: TIME_STOP")
        return ICAdjustment.TIME_STOP

    # ── 4. Wing removal (near expiry, wings nearly dead) ─────────────────────
    if (dte <= cfg.wing_removal_dte_max and
            position.long_call_value <= cfg.wing_removal_value_max and
            position.long_put_value  <= cfg.wing_removal_value_max and
            not position.wings_removed):
        logger.debug("IC adjust: WING_REMOVAL")
        return ICAdjustment.WING_REMOVAL

    # ── 5. Partial close (one side at big profit) ─────────────────────────────
    if (not position.call_side_closed and
            position.call_spread_profit_pct >= cfg.partial_close_pct):
        logger.debug("IC adjust: PARTIAL_CLOSE_WINNER (call side)")
        return ICAdjustment.PARTIAL_CLOSE_WINNER
    if (not position.put_side_closed and
            position.put_spread_profit_pct >= cfg.partial_close_pct):
        logger.debug("IC adjust: PARTIAL_CLOSE_WINNER (put side)")
        return ICAdjustment.PARTIAL_CLOSE_WINNER

    # ── 6. Roll untested side inward (credit harvest) ─────────────────────────
    untested_pct = position.untested_side_profit_pct(spot)
    if (untested_pct >= cfg.untested_profit_pct and
            position.untested_rolls_done < cfg.max_rolls_per_side):
        # Caller must verify roll credit ≥ min_roll_credit before executing
        logger.debug("IC adjust: ROLL_UNTESTED_INWARD")
        return ICAdjustment.ROLL_UNTESTED_INWARD

    # ── 7. Defensive roll (tested side delta too high) ───────────────────────
    tested_delta = max(short_call_delta, short_put_delta)
    if (tested_delta >= cfg.defensive_delta_trigger and
            position.tested_rolls_done < cfg.max_rolls_per_side):
        logger.debug(f"IC adjust: DEFENSIVE_ROLL (delta={tested_delta:.2f})")
        return ICAdjustment.DEFENSIVE_ROLL

    # ── 8. Iron fly conversion (spot AT short strike) ─────────────────────────
    if dte >= cfg.iron_fly_min_dte:
        nearest_short_distance = min(
            abs(spot - position.short_call_strike),
            abs(spot - position.short_put_strike),
        )
        if nearest_short_distance <= cfg.iron_fly_spot_distance:
            logger.debug("IC adjust: IRON_FLY_CONVERSION")
            return ICAdjustment.IRON_FLY_CONVERSION

    return ICAdjustment.NONE
