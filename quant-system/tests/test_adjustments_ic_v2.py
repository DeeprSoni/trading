"""Tests for IC adjustment engine v2."""
import pytest
from datetime import datetime, timedelta

from src.adjustments_ic import (
    evaluate_ic_adjustment, ICPosition, ICAdjustmentConfig, ICAdjustment
)


def make_position(
    credit=30.0,
    call_orig=15.0, put_orig=15.0,
    call_curr=15.0, put_curr=15.0,
    long_call=5.0, long_put=5.0,
    short_call=23000.0, short_put=21000.0,
    untested_rolls=0, tested_rolls=0,
    call_side_closed=False, put_side_closed=False,
    wings_removed=False,
):
    p = ICPosition(
        symbol="NIFTY",
        entry_date=datetime.now() - timedelta(days=10),
        expiry_date=datetime.now() + timedelta(days=25),
        original_credit=credit,
        call_spread_original_credit=call_orig,
        put_spread_original_credit=put_orig,
        call_spread_current_value=call_curr,
        put_spread_current_value=put_curr,
        long_call_value=long_call,
        long_put_value=long_put,
        short_call_strike=short_call,
        short_put_strike=short_put,
        untested_rolls_done=untested_rolls,
        tested_rolls_done=tested_rolls,
        call_side_closed=call_side_closed,
        put_side_closed=put_side_closed,
        wings_removed=wings_removed,
    )
    return p


def test_emergency_stop():
    p = make_position(credit=30.0, call_curr=35.0, put_curr=30.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.20,
                                     short_put_delta=0.10, dte=25)
    assert result == ICAdjustment.EMERGENCY_STOP


def test_profit_target():
    p = make_position(credit=30.0, call_curr=5.0, put_curr=10.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.10,
                                     short_put_delta=0.08, dte=25)
    assert result == ICAdjustment.PROFIT_TARGET


def test_time_stop():
    p = make_position(credit=30.0, call_curr=12.0, put_curr=10.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.15,
                                     short_put_delta=0.10, dte=20)
    assert result == ICAdjustment.TIME_STOP


def test_wing_removal():
    p = make_position(credit=30.0, call_curr=12.0, put_curr=10.0,
                       long_call=2.0, long_put=1.5)
    # DTE <= 7 and both wings < Rs 3 — but time stop fires first at 21 DTE
    # So we need DTE between wing_removal max (7) and time stop (21)
    # Actually wing_removal_dte_max=7 < time_stop_dte=21, so time stop always fires first
    # We need custom config to test wing removal in isolation
    cfg = ICAdjustmentConfig(time_stop_dte=5, wing_removal_dte_max=7)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.15,
                                     short_put_delta=0.10, dte=6, cfg=cfg)
    assert result == ICAdjustment.WING_REMOVAL


def test_partial_close_winner():
    # Total value = 2 + 13 = 15, credit = 30, profit = 50% → profit target fires first
    # Need profit < 50% overall but one side at 80%+
    # call_curr=2 (87% profit on call side), put_curr=15 (0% profit on put)
    # total value = 17, credit = 30, profit = 43% (< 50% target) → partial close fires
    p = make_position(credit=30.0, call_orig=15.0, call_curr=2.0,
                       put_orig=15.0, put_curr=15.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.08,
                                     short_put_delta=0.18, dte=25)
    assert result == ICAdjustment.PARTIAL_CLOSE_WINNER


def test_roll_untested_inward():
    # Call side untested (market below mid), call at 85% profit
    p = make_position(credit=30.0, call_orig=15.0, call_curr=2.0,
                       put_orig=15.0, put_curr=14.0)
    # But partial close would fire first since call at 86% profit
    # Need to set call_side_closed=True to skip partial close
    p.call_side_closed = True
    result = evaluate_ic_adjustment(p, spot=21500, short_call_delta=0.05,
                                     short_put_delta=0.20, dte=25)
    assert result == ICAdjustment.ROLL_UNTESTED_INWARD


def test_defensive_roll():
    p = make_position(credit=30.0, call_curr=20.0, put_curr=12.0)
    result = evaluate_ic_adjustment(p, spot=22900, short_call_delta=0.35,
                                     short_put_delta=0.10, dte=25)
    assert result == ICAdjustment.DEFENSIVE_ROLL


def test_iron_fly_conversion():
    # DTE=15 < time_stop_dte=21, so time stop fires first
    # Need DTE > 21 and spot within 50 pts of short strike
    p = make_position(credit=30.0, call_curr=15.0, put_curr=14.0,
                       short_call=22050.0, short_put=21000.0)
    result = evaluate_ic_adjustment(p, spot=22030.0, short_call_delta=0.28,
                                     short_put_delta=0.12, dte=25)
    assert result == ICAdjustment.IRON_FLY_CONVERSION


def test_no_adjustment_normal_conditions():
    p = make_position(credit=30.0, call_curr=12.0, put_curr=11.0)
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.18,
                                     short_put_delta=0.15, dte=28)
    assert result == ICAdjustment.NONE


def test_priority_stop_loss_over_profit_target():
    """Stop loss should fire even if profit target also met (edge case: value spike)."""
    p = make_position(credit=30.0, call_curr=35.0, put_curr=30.0)
    # value=65 >= 2*30=60 → stop loss, even though unrealized_profit is negative
    result = evaluate_ic_adjustment(p, spot=22000, short_call_delta=0.20,
                                     short_put_delta=0.10, dte=25)
    assert result == ICAdjustment.EMERGENCY_STOP
