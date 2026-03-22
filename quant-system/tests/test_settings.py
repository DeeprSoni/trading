"""Tests for config/settings.py — capital structure, IC gates, wing/size tables."""

from config.settings import (
    TOTAL_CAPITAL,
    CAPITAL_STRUCTURE,
    PARKED_YIELD,
    PARKED_CAPITAL_ANNUAL_INCOME,
    PHASE_1_ACTIVE_CAPITAL,
    PHASE_3_ACTIVE_CAPITAL,
    IC_IVR_MIN,
    IC_VIX_STANDARD_MAX,
    IC_VIX_ELEVATED_MAX,
    IC_VIX_KILLSWITCH,
    IC_WING_TABLE,
    IC_SIZE_TABLE,
    get_ic_wing_width,
    get_ic_size_multiplier,
    # Backward-compat aliases
    ACTIVE_TRADING_CAPITAL,
    IC_MIN_IV_RANK,
    VIX_MAX_FOR_IC,
)


def test_capital_structure_sums_to_total():
    total = sum(CAPITAL_STRUCTURE.values())
    assert total == TOTAL_CAPITAL


def test_parked_yield_computation():
    expected = (
        400_000 * 0.065
        + 100_000 * 0.075
        + 50_000 * 0.035
    )
    assert abs(PARKED_CAPITAL_ANNUAL_INCOME - expected) < 1.0


def test_phase_capitals():
    assert PHASE_1_ACTIVE_CAPITAL == 90_000
    assert PHASE_3_ACTIVE_CAPITAL == 200_000


def test_get_ic_wing_width():
    assert get_ic_wing_width(10) == 400
    assert get_ic_wing_width(18) == 500
    assert get_ic_wing_width(22) == 600
    assert get_ic_wing_width(27) == 700
    assert get_ic_wing_width(33) == 800
    assert get_ic_wing_width(40) == 900


def test_get_ic_size_multiplier():
    assert get_ic_size_multiplier(15) == 1.00
    assert get_ic_size_multiplier(27) == 0.75
    assert get_ic_size_multiplier(33) == 0.50
    assert get_ic_size_multiplier(40) == 0.25


def test_backward_compat_aliases():
    assert ACTIVE_TRADING_CAPITAL == PHASE_1_ACTIVE_CAPITAL
    assert IC_MIN_IV_RANK == IC_IVR_MIN
    assert VIX_MAX_FOR_IC == IC_VIX_STANDARD_MAX


def test_ic_gate_values():
    assert IC_IVR_MIN == 20
    assert IC_VIX_STANDARD_MAX == 25
    assert IC_VIX_ELEVATED_MAX == 35
    assert IC_VIX_KILLSWITCH == 40
