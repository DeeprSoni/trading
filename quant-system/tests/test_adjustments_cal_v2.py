"""Tests for CAL adjustment engine v2."""
import pytest
from datetime import datetime, timedelta

from src.adjustments_cal import (
    evaluate_cal_adjustment, CALPosition, CALAdjustmentConfig, CALAdjustment
)


def make_position(
    entry_spot=22000.0,
    front_entry=100.0, front_curr=100.0,
    back_iv_entry=0.20, back_iv_curr=0.20,
    cal_entry=50.0, cal_curr=50.0,
    secondary=0, is_diagonal=False,
):
    return CALPosition(
        symbol="NIFTY",
        entry_date=datetime.now() - timedelta(days=10),
        entry_spot=entry_spot,
        front_expiry=datetime.now() + timedelta(days=20),
        back_expiry=datetime.now() + timedelta(days=60),
        front_month_entry_value=front_entry,
        front_month_current_value=front_curr,
        back_month_iv_at_entry=back_iv_entry,
        back_month_iv_current=back_iv_curr,
        calendar_entry_credit=cal_entry,
        calendar_current_value=cal_curr,
        secondary_calendars_added=secondary,
        is_diagonal=is_diagonal,
    )


def test_close_large_move():
    # 5% move from entry
    p = make_position(entry_spot=22000.0)
    result = evaluate_cal_adjustment(p, spot=23100.0, front_dte=15, back_dte=55)
    assert result == CALAdjustment.CLOSE_LARGE_MOVE


def test_close_back_near():
    p = make_position(entry_spot=22000.0)
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=5, back_dte=24)
    assert result == CALAdjustment.CLOSE_BACK_NEAR


def test_early_profit_close():
    # 50% profit and front DTE <= 15
    p = make_position(cal_entry=50.0, cal_curr=75.0)
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=12, back_dte=50)
    assert result == CALAdjustment.EARLY_PROFIT_CLOSE


def test_iv_harvest_roll():
    # IV expanded 30% (from 0.20 to 0.26)
    p = make_position(back_iv_entry=0.20, back_iv_curr=0.26)
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.IV_HARVEST_ROLL


def test_front_roll():
    # Front DTE <= 6 and 70% decayed
    p = make_position(front_entry=100.0, front_curr=30.0)
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=5, back_dte=45)
    assert result == CALAdjustment.FRONT_ROLL


def test_full_recentre():
    # 2.5% move
    p = make_position(entry_spot=22000.0)
    result = evaluate_cal_adjustment(p, spot=22550.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.FULL_RECENTRE


def test_diagonal_convert():
    # 1.7% move, not yet diagonal
    p = make_position(entry_spot=22000.0, is_diagonal=False)
    result = evaluate_cal_adjustment(p, spot=22374.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.DIAGONAL_CONVERT


def test_diagonal_not_triggered_if_already_diagonal():
    p = make_position(entry_spot=22000.0, is_diagonal=True)
    result = evaluate_cal_adjustment(p, spot=22374.0, front_dte=18, back_dte=55)
    # Should NOT trigger diagonal again, falls through to NONE
    assert result == CALAdjustment.NONE


def test_add_second_calendar():
    # 30% profit and market stable (within 1%)
    p = make_position(cal_entry=50.0, cal_curr=65.0, secondary=0)
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.ADD_SECOND_CAL


def test_no_adjustment_normal_conditions():
    p = make_position()
    result = evaluate_cal_adjustment(p, spot=22000.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.NONE


def test_priority_large_move_over_recentre():
    # 5% move triggers close, not recentre
    p = make_position(entry_spot=22000.0)
    result = evaluate_cal_adjustment(p, spot=23200.0, front_dte=18, back_dte=55)
    assert result == CALAdjustment.CLOSE_LARGE_MOVE
