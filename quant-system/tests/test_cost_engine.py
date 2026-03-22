"""Tests for cost_engine — Indian F&O transaction cost calculator."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.cost_engine import CostEngine, LegCostInput, SlippageModel


# Use zero slippage for deterministic fee tests
def _engine(slippage=SlippageModel.REALISTIC, **kw):
    return CostEngine(slippage_model=slippage, **kw)


def _zero_slippage_engine(**kw):
    """Engine with zero slippage so we can verify fees exactly."""
    return CostEngine(
        slippage_model=SlippageModel.OPTIMISTIC,
        default_slippage_per_unit=0,
        **kw,
    )


# --- Single Leg Tests ---

class TestSingleLegCosts:
    def test_sell_leg_has_stt(self):
        """STT should apply on sell-side turnover."""
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=100, side="SELL", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        # STT = 100 * 25 * 0.000625 = 1.5625
        assert abs(costs.stt - 1.56) < 0.01

    def test_buy_leg_no_stt(self):
        """STT should NOT apply on buy side."""
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        assert costs.stt == 0.0

    def test_buy_leg_has_stamp_duty(self):
        """Stamp duty should apply on buy-side turnover."""
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        # stamp = 100 * 25 * 0.00003 = 0.075
        assert abs(costs.stamp_duty - 0.075) < 0.001

    def test_sell_leg_no_stamp_duty(self):
        """Stamp duty should NOT apply on sell side."""
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=100, side="SELL", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        assert costs.stamp_duty == 0.0

    def test_brokerage_is_flat_20(self):
        """Brokerage should be Rs 20 regardless of premium."""
        engine = _zero_slippage_engine()
        for premium in [10, 100, 500]:
            leg = LegCostInput(premium=premium, side="SELL", lots=1, lot_size=25, bid=premium, ask=premium)
            costs = engine.calculate_leg_costs(leg)
            assert costs.brokerage == 20.0

    def test_exchange_charges_both_sides(self):
        """Exchange charges apply on both buy and sell."""
        engine = _zero_slippage_engine()
        leg_buy = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=100, ask=100)
        leg_sell = LegCostInput(premium=100, side="SELL", lots=1, lot_size=25, bid=100, ask=100)
        # Both should have same exchange charges: 100*25*0.00053 = 1.325
        assert abs(engine.calculate_leg_costs(leg_buy).exchange_charges - 1.325) < 0.001
        assert abs(engine.calculate_leg_costs(leg_sell).exchange_charges - 1.325) < 0.001

    def test_gst_on_brokerage_exchange_sebi(self):
        """GST = 18% of (brokerage + exchange + SEBI fee)."""
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        # exchange = 1.325, sebi = 0.0025, brokerage = 20
        expected_gst = (20 + 1.325 + 0.0025) * 0.18
        assert abs(costs.gst - expected_gst) < 0.01

    def test_lots_multiply_turnover(self):
        """2 lots should double turnover-based fees (not brokerage)."""
        engine = _zero_slippage_engine()
        leg1 = LegCostInput(premium=100, side="SELL", lots=1, lot_size=25, bid=100, ask=100)
        leg2 = LegCostInput(premium=100, side="SELL", lots=2, lot_size=25, bid=100, ask=100)
        c1 = engine.calculate_leg_costs(leg1)
        c2 = engine.calculate_leg_costs(leg2)
        # STT should double
        assert abs(c2.stt - c1.stt * 2) < 0.01
        # Brokerage stays same (flat per order)
        assert c2.brokerage == c1.brokerage


# --- Slippage Model Tests ---

class TestSlippageModels:
    def test_optimistic_less_than_realistic(self):
        engine_opt = CostEngine(slippage_model=SlippageModel.OPTIMISTIC)
        engine_real = CostEngine(slippage_model=SlippageModel.REALISTIC)
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25)
        assert engine_opt.calculate_leg_costs(leg).slippage < engine_real.calculate_leg_costs(leg).slippage

    def test_realistic_less_than_conservative(self):
        engine_real = CostEngine(slippage_model=SlippageModel.REALISTIC)
        engine_cons = CostEngine(slippage_model=SlippageModel.CONSERVATIVE)
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25)
        assert engine_real.calculate_leg_costs(leg).slippage < engine_cons.calculate_leg_costs(leg).slippage

    def test_slippage_uses_actual_spread_when_available(self):
        engine = CostEngine(slippage_model=SlippageModel.REALISTIC)
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=99, ask=101)
        costs = engine.calculate_leg_costs(leg)
        # spread = 2, realistic = 75% => 1.5/unit * 25 = 37.5
        assert abs(costs.slippage - 37.5) < 0.01

    def test_slippage_estimates_spread_when_no_bidask(self):
        engine = CostEngine(slippage_model=SlippageModel.REALISTIC)
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25)
        costs = engine.calculate_leg_costs(leg)
        # premium 100 => OTM range (50-200), spread = max(2, 100*0.02) = 2.0
        # realistic = 75% => 1.5/unit * 25 = 37.5
        assert abs(costs.slippage - 37.5) < 0.01

    def test_conservative_adds_one_rupee(self):
        engine = CostEngine(slippage_model=SlippageModel.CONSERVATIVE)
        leg = LegCostInput(premium=100, side="BUY", lots=1, lot_size=25, bid=99, ask=101)
        costs = engine.calculate_leg_costs(leg)
        # spread = 2, conservative = 100% + 1 = 3/unit * 25 = 75
        assert abs(costs.slippage - 75.0) < 0.01


# --- Spread Estimation Tests ---

class TestSpreadEstimation:
    def test_atm_tight_spread(self):
        engine = CostEngine()
        spread = engine.estimate_spread_from_premium(300)
        # 300 * 0.008 = 2.4
        assert abs(spread - 2.4) < 0.01

    def test_otm_wider_spread(self):
        engine = CostEngine()
        spread = engine.estimate_spread_from_premium(80)
        # max(2, 80*0.02) = 2.0
        assert abs(spread - 2.0) < 0.01

    def test_far_otm_even_wider(self):
        engine = CostEngine()
        spread = engine.estimate_spread_from_premium(20)
        # max(3, 20*0.05) = 3.0
        assert abs(spread - 3.0) < 0.01

    def test_deep_otm_percentage(self):
        engine = CostEngine()
        spread = engine.estimate_spread_from_premium(5)
        # max(2, 5*0.15) = 2.0
        assert abs(spread - 2.0) < 0.01


# --- Iron Condor Cost Tests ---

class TestICCosts:
    def test_ic_has_8_legs_roundtrip(self):
        engine = _zero_slippage_engine()
        costs = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
            exit_short_call=53, exit_short_put=47,
            exit_long_call=16.5, exit_long_put=14.4,
        )
        assert costs.leg_count == 8

    def test_ic_brokerage_is_8x20(self):
        """8 orders * Rs 20 = Rs 160 brokerage."""
        engine = _zero_slippage_engine()
        costs = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
            exit_short_call=53, exit_short_put=47,
            exit_long_call=16.5, exit_long_put=14.4,
        )
        assert costs.total_brokerage == 160.0

    def test_ic_stt_only_on_sells(self):
        """STT on: entry sell call/put + exit sell long call/put."""
        engine = _zero_slippage_engine()
        costs = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
            exit_short_call=53, exit_short_put=47,
            exit_long_call=16.5, exit_long_put=14.4,
        )
        # Sell-side premiums: 106, 94 (entry) + 16.5, 14.4 (exit)
        # STT = (106 + 94 + 16.5 + 14.4) * 25 * 0.000625
        expected_stt = (106 + 94 + 16.5 + 14.4) * 25 * 0.000625
        assert abs(costs.total_stt - expected_stt) < 0.02

    def test_ic_total_costs_positive(self):
        engine = CostEngine(slippage_model=SlippageModel.REALISTIC)
        costs = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
        )
        assert costs.total_costs > 0
        assert costs.cost_per_unit > 0
        assert costs.cost_as_pct_of_premium > 0

    def test_ic_cost_per_unit_is_meaningful(self):
        """Cost per unit should be a few rupees, not hundreds."""
        engine = CostEngine(slippage_model=SlippageModel.REALISTIC)
        costs = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
        )
        # For 1-lot Nifty IC, cost_per_unit should be roughly Rs 10-30
        assert 2 < costs.cost_per_unit < 100

    def test_ic_with_margin_opportunity_cost(self):
        engine = _zero_slippage_engine()
        costs_no_margin = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
        )
        costs_with_margin = engine.calculate_ic_costs(
            short_call_premium=106, short_put_premium=94,
            long_call_premium=55, long_put_premium=48,
            margin_required=100000, holding_days=35,
        )
        assert costs_with_margin.margin_opportunity_cost > 0
        assert costs_with_margin.total_costs > costs_no_margin.total_costs


# --- Calendar Spread Cost Tests ---

class TestCalendarCosts:
    def test_calendar_has_4_legs_roundtrip(self):
        engine = _zero_slippage_engine()
        costs = engine.calculate_calendar_costs(
            back_month_cost=350, front_month_premium=200,
            exit_back_month=400, exit_front_month=60,
        )
        assert costs.leg_count == 4

    def test_calendar_brokerage_is_4x20(self):
        engine = _zero_slippage_engine()
        costs = engine.calculate_calendar_costs(
            back_month_cost=350, front_month_premium=200,
            exit_back_month=400, exit_front_month=60,
        )
        assert costs.total_brokerage == 80.0

    def test_calendar_costs_positive(self):
        engine = CostEngine(slippage_model=SlippageModel.REALISTIC)
        costs = engine.calculate_calendar_costs(
            back_month_cost=350, front_month_premium=200,
        )
        assert costs.total_costs > 0


# --- ITM Expiry STT Tests ---

class TestITMExpiryStt:
    def test_itm_expiry_stt_calculation(self):
        engine = CostEngine()
        # 100 points ITM, 1 lot of 25
        stt = engine.calculate_itm_expiry_stt(100, 25, 1)
        # 100 * 25 * 0.00125 = 3.125
        assert abs(stt - 3.125) < 0.001

    def test_deep_itm_expiry_is_expensive(self):
        """500 points ITM on 2 lots — this cost is a profit killer."""
        engine = CostEngine()
        stt = engine.calculate_itm_expiry_stt(500, 25, 2)
        # 500 * 25 * 2 * 0.00125 = 31.25
        assert abs(stt - 31.25) < 0.01


# --- Margin Opportunity Cost Tests ---

class TestMarginCost:
    def test_margin_cost_formula(self):
        engine = CostEngine()
        cost = engine.calculate_margin_opportunity_cost(100000, 35)
        # 100000 * 0.065 * (35/365) = 623.29
        expected = 100000 * 0.065 * (35 / 365)
        assert abs(cost - expected) < 0.01

    def test_zero_days_zero_cost(self):
        engine = CostEngine()
        assert engine.calculate_margin_opportunity_cost(100000, 0) == 0.0

    def test_zero_margin_zero_cost(self):
        engine = CostEngine()
        assert engine.calculate_margin_opportunity_cost(0, 35) == 0.0

    def test_custom_annual_rate(self):
        engine = CostEngine()
        cost = engine.calculate_margin_opportunity_cost(100000, 365, annual_rate=0.10)
        assert abs(cost - 10000) < 0.01


# --- Edge Cases ---

class TestEdgeCases:
    def test_zero_premium_leg(self):
        engine = _zero_slippage_engine()
        leg = LegCostInput(premium=0, side="BUY", lots=1, lot_size=25, bid=0, ask=0)
        costs = engine.calculate_leg_costs(leg)
        # Only brokerage + GST on brokerage
        assert costs.brokerage == 20.0
        assert costs.stt == 0.0
        assert costs.exchange_charges == 0.0

    def test_custom_rates(self):
        engine = CostEngine(
            brokerage_per_order=0,
            gst_rate=0,
            stt_sell_rate=0,
            exchange_rate=0,
            sebi_fee_rate=0,
            stamp_duty_rate=0,
            slippage_model=SlippageModel.OPTIMISTIC,
        )
        leg = LegCostInput(premium=100, side="SELL", lots=1, lot_size=25, bid=100, ask=100)
        costs = engine.calculate_leg_costs(leg)
        # Only slippage (bid=ask so spread=0 => slippage=0)
        assert costs.brokerage == 0
        assert costs.stt == 0
        assert costs.total == 0.0
