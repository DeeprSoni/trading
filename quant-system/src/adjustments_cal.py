"""
Calendar Spread Adjustment Engine v2.0

Adjustment priority (checked daily):

  1. Close on large move      — spot moved 4%+ from entry
  2. Back month too near      — back month DTE ≤ 25
  3. Early profit close       — 40% profit AND front month DTE ≤ 15
  4. IV harvest roll          — back month IV expanded 25%+
  5. Front month roll         — front month DTE ≤ 6 AND 60% decayed
  6. Full recentre            — spot moved 2%+
  7. Diagonal conversion      — spot moved 1.5% (cheaper than full recentre)
  8. Add second calendar      — 25% profit AND market stable
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class CALAdjustment(Enum):
    NONE                = "none"
    CLOSE_LARGE_MOVE    = "close_large_move"
    CLOSE_BACK_NEAR     = "close_back_near"
    EARLY_PROFIT_CLOSE  = "early_profit_close"
    IV_HARVEST_ROLL     = "iv_harvest_roll"
    FRONT_ROLL          = "front_roll"
    FULL_RECENTRE       = "full_recentre"
    DIAGONAL_CONVERT    = "diagonal_convert"
    ADD_SECOND_CAL      = "add_second_calendar"


@dataclass
class CALAdjustmentConfig:
    # Close triggers
    large_move_pct: float        = 0.04   # 4% move → close all
    back_close_dte: int          = 25     # Close when back month at 25 DTE

    # Profit targets
    profit_target_pct: float     = 0.40   # 40% profit target
    early_close_front_dte: int   = 15     # Close at 40% if front DTE ≤ 15 (past theta peak)

    # IV harvest
    iv_harvest_trigger: float    = 0.25   # Back month IV up 25%+ → harvest roll

    # Front roll (CHANGED: was 3 DTE, now 6 DTE for better fill prices)
    front_roll_dte: int          = 6      # was 3
    front_decay_threshold: float = 0.60   # Only roll after 60% of entry time value gone

    # Market move reactions
    full_recentre_pct: float     = 0.02   # 2%+ move → recentre both legs
    diagonal_pct: float          = 0.015  # 1.5% move → convert to diagonal (cheaper)

    # Expansion
    add_cal_profit_pct: float    = 0.25   # Add 2nd calendar when first at 25% profit
    add_cal_stable_pct: float    = 0.010  # Market must be within 1% of entry
    max_secondary_calendars: int = 2      # Allow up to 2 additional calendars
    second_cal_offset_pts: int   = 200    # 200 pts OTM each side


@dataclass
class CALPosition:
    """Live calendar spread position."""
    symbol: str
    entry_date: object
    entry_spot: float
    front_expiry: object
    back_expiry: object

    # Values updated daily
    front_month_entry_value: float = 0.0
    front_month_current_value: float = 0.0
    back_month_iv_at_entry: float = 0.0
    back_month_iv_current: float = 0.0
    calendar_entry_credit: float = 0.0
    calendar_current_value: float = 0.0

    # State
    secondary_calendars_added: int = 0
    is_diagonal: bool = False

    @property
    def unrealized_profit_pct(self) -> float:
        if self.calendar_entry_credit == 0:
            return 0.0
        gain = self.calendar_current_value - self.calendar_entry_credit
        return gain / abs(self.calendar_entry_credit)

    @property
    def front_decay_pct(self) -> float:
        if self.front_month_entry_value == 0:
            return 0.0
        return 1 - self.front_month_current_value / self.front_month_entry_value

    @property
    def back_iv_change_pct(self) -> float:
        if self.back_month_iv_at_entry == 0:
            return 0.0
        return (self.back_month_iv_current - self.back_month_iv_at_entry) / self.back_month_iv_at_entry


def evaluate_cal_adjustment(
    position: CALPosition,
    spot: float,
    front_dte: int,
    back_dte: int,
    cfg: CALAdjustmentConfig | None = None,
) -> CALAdjustment:
    """
    Evaluate what calendar adjustment to execute today.
    Returns CALAdjustment enum value.
    """
    if cfg is None:
        cfg = CALAdjustmentConfig()

    move_pct   = abs(spot - position.entry_spot) / position.entry_spot
    profit_pct = position.unrealized_profit_pct

    # ── 1. Large move — close everything ─────────────────────────────────────
    if move_pct >= cfg.large_move_pct:
        return CALAdjustment.CLOSE_LARGE_MOVE

    # ── 2. Back month near expiry ─────────────────────────────────────────────
    if back_dte <= cfg.back_close_dte:
        return CALAdjustment.CLOSE_BACK_NEAR

    # ── 3. Early profit close (past theta peak) ───────────────────────────────
    if profit_pct >= cfg.profit_target_pct and front_dte <= cfg.early_close_front_dte:
        return CALAdjustment.EARLY_PROFIT_CLOSE

    # ── 4. IV harvest roll ────────────────────────────────────────────────────
    if position.back_iv_change_pct >= cfg.iv_harvest_trigger:
        return CALAdjustment.IV_HARVEST_ROLL

    # ── 5. Front month roll ───────────────────────────────────────────────────
    if (front_dte <= cfg.front_roll_dte and
            position.front_decay_pct >= cfg.front_decay_threshold):
        return CALAdjustment.FRONT_ROLL

    # ── 6. Full recentre (2%+ move) ───────────────────────────────────────────
    if move_pct >= cfg.full_recentre_pct:
        return CALAdjustment.FULL_RECENTRE

    # ── 7. Diagonal conversion (1.5% move — cheaper than full recentre) ───────
    if move_pct >= cfg.diagonal_pct and not position.is_diagonal:
        return CALAdjustment.DIAGONAL_CONVERT

    # ── 8. Add second calendar (winning + market stable) ─────────────────────
    if (profit_pct >= cfg.add_cal_profit_pct and
            move_pct <= cfg.add_cal_stable_pct and
            position.secondary_calendars_added < cfg.max_secondary_calendars):
        return CALAdjustment.ADD_SECOND_CAL

    return CALAdjustment.NONE
