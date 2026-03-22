"""
Cost Engine — complete Indian F&O transaction cost calculator.

Covers every real-world cost for options trading on NSE:
brokerage, STT, exchange charges, SEBI fee, stamp duty, GST,
slippage (three models), and margin opportunity cost.

All rates default to FY 2024-25 actuals from config/settings.py.
"""

from dataclasses import dataclass, field
from enum import Enum

from config import settings


class SlippageModel(Enum):
    OPTIMISTIC = "optimistic"      # 50% of bid-ask spread
    REALISTIC = "realistic"        # 75% of bid-ask spread
    CONSERVATIVE = "conservative"  # 100% of spread + Rs 1


@dataclass
class LegCostInput:
    """Input for a single option leg cost calculation."""
    premium: float       # execution price per unit
    side: str           # "BUY" or "SELL"
    lots: int = 1
    lot_size: int = 25  # Nifty default
    bid: float = 0.0    # optional, for spread-based slippage
    ask: float = 0.0    # optional, for spread-based slippage


@dataclass
class LegCosts:
    """Breakdown of costs for a single leg."""
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_fee: float
    stamp_duty: float
    gst: float
    slippage: float
    total: float


@dataclass
class TradeCosts:
    """Total costs for a complete trade (all legs, entry + exit)."""
    total_brokerage: float
    total_stt: float
    total_exchange_charges: float
    total_sebi_fee: float
    total_stamp_duty: float
    total_gst: float
    total_slippage: float
    total_costs: float
    cost_per_unit: float          # total / (lots * lot_size)
    cost_as_pct_of_premium: float  # total / net_premium_value
    margin_opportunity_cost: float = 0.0
    leg_count: int = 0


class CostEngine:
    """
    Complete Indian F&O transaction cost calculator.

    Fee schedule (FY 2024-25):
      Brokerage:       Rs 20 / order (Zerodha flat)
      STT:             0.0625% on sell-side premium (Budget 2024)
      STT ITM expiry:  0.125% of intrinsic value
      Exchange:        0.053% on turnover (both sides)
      SEBI fee:        Rs 10 / crore (0.0001%)
      Stamp duty:      0.003% on buy-side only
      GST:             18% on (brokerage + exchange + SEBI fee)

    Slippage models:
      Optimistic:      50% of bid-ask spread
      Realistic:       75% of bid-ask spread
      Conservative:    100% of spread + Rs 1 per unit
    """

    def __init__(
        self,
        brokerage_per_order: float | None = None,
        gst_rate: float | None = None,
        stt_sell_rate: float | None = None,
        stt_itm_expiry_rate: float | None = None,
        exchange_rate: float | None = None,
        sebi_fee_rate: float | None = None,
        stamp_duty_rate: float | None = None,
        slippage_model: SlippageModel = SlippageModel.REALISTIC,
        default_slippage_per_unit: float | None = None,
    ):
        self.brokerage_per_order = brokerage_per_order if brokerage_per_order is not None else settings.COST_BROKERAGE_PER_ORDER
        self.gst_rate = gst_rate if gst_rate is not None else settings.COST_BROKERAGE_GST_RATE
        self.stt_sell_rate = stt_sell_rate if stt_sell_rate is not None else settings.COST_STT_SELL_RATE
        self.stt_itm_expiry_rate = stt_itm_expiry_rate if stt_itm_expiry_rate is not None else settings.COST_STT_ITM_EXPIRY_RATE
        self.exchange_rate = exchange_rate if exchange_rate is not None else settings.COST_NSE_EXCHANGE_RATE
        self.sebi_fee_rate = sebi_fee_rate if sebi_fee_rate is not None else settings.COST_SEBI_FEE_RATE
        self.stamp_duty_rate = stamp_duty_rate if stamp_duty_rate is not None else settings.COST_STAMP_DUTY_RATE
        self.slippage_model = slippage_model
        self.default_slippage_per_unit = default_slippage_per_unit if default_slippage_per_unit is not None else settings.COST_SLIPPAGE_PER_UNIT_PER_LEG

    # --- Single Leg ---

    def calculate_leg_costs(self, leg: LegCostInput) -> LegCosts:
        """Calculate all transaction costs for a single option leg."""
        turnover = leg.premium * leg.lots * leg.lot_size

        # Brokerage: flat per order
        brokerage = self.brokerage_per_order

        # STT: only on sell side
        stt = turnover * self.stt_sell_rate if leg.side == "SELL" else 0.0

        # Exchange transaction charges: on total turnover (both sides)
        exchange_charges = turnover * self.exchange_rate

        # SEBI fee: on total turnover
        sebi_fee = turnover * self.sebi_fee_rate

        # Stamp duty: only on buy side
        stamp_duty = turnover * self.stamp_duty_rate if leg.side == "BUY" else 0.0

        # GST: 18% on (brokerage + exchange charges + SEBI fee)
        gst = (brokerage + exchange_charges + sebi_fee) * self.gst_rate

        # Slippage
        slippage = self._calculate_slippage(leg)

        total = brokerage + stt + exchange_charges + sebi_fee + stamp_duty + gst + slippage

        return LegCosts(
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_charges=round(exchange_charges, 4),
            sebi_fee=round(sebi_fee, 6),
            stamp_duty=round(stamp_duty, 6),
            gst=round(gst, 2),
            slippage=round(slippage, 2),
            total=round(total, 2),
        )

    # --- Multi-Leg Trade ---

    def calculate_trade_costs(
        self,
        entry_legs: list[LegCostInput],
        exit_legs: list[LegCostInput],
        net_premium_per_unit: float,
        lot_size: int = 25,
        lots: int = 1,
        margin_required: float = 0.0,
        holding_days: int = 0,
    ) -> TradeCosts:
        """
        Calculate total round-trip costs for a multi-leg options trade.

        entry_legs / exit_legs: list of LegCostInput for each leg at entry/exit.
        net_premium_per_unit: net premium collected (IC) or debit paid (calendar) per unit.
        """
        all_legs = entry_legs + exit_legs

        totals = {
            "brokerage": 0.0, "stt": 0.0, "exchange": 0.0,
            "sebi": 0.0, "stamp": 0.0, "gst": 0.0, "slippage": 0.0,
        }

        for leg in all_legs:
            costs = self.calculate_leg_costs(leg)
            totals["brokerage"] += costs.brokerage
            totals["stt"] += costs.stt
            totals["exchange"] += costs.exchange_charges
            totals["sebi"] += costs.sebi_fee
            totals["stamp"] += costs.stamp_duty
            totals["gst"] += costs.gst
            totals["slippage"] += costs.slippage

        total = sum(totals.values())

        # Margin opportunity cost
        margin_opp_cost = 0.0
        if margin_required > 0 and holding_days > 0:
            margin_opp_cost = self.calculate_margin_opportunity_cost(
                margin_required, holding_days
            )
            total += margin_opp_cost

        net_premium_value = abs(net_premium_per_unit) * lot_size * lots
        cost_per_unit = total / (lot_size * lots) if lot_size * lots > 0 else 0
        cost_pct = total / net_premium_value if net_premium_value > 0 else 0

        return TradeCosts(
            total_brokerage=round(totals["brokerage"], 2),
            total_stt=round(totals["stt"], 2),
            total_exchange_charges=round(totals["exchange"], 4),
            total_sebi_fee=round(totals["sebi"], 6),
            total_stamp_duty=round(totals["stamp"], 6),
            total_gst=round(totals["gst"], 2),
            total_slippage=round(totals["slippage"], 2),
            total_costs=round(total, 2),
            cost_per_unit=round(cost_per_unit, 2),
            cost_as_pct_of_premium=round(cost_pct, 4),
            margin_opportunity_cost=round(margin_opp_cost, 2),
            leg_count=len(all_legs),
        )

    # --- Strategy Convenience Methods ---

    def calculate_ic_costs(
        self,
        short_call_premium: float,
        short_put_premium: float,
        long_call_premium: float,
        long_put_premium: float,
        exit_short_call: float | None = None,
        exit_short_put: float | None = None,
        exit_long_call: float | None = None,
        exit_long_put: float | None = None,
        lots: int = 1,
        lot_size: int = 25,
        margin_required: float = 0.0,
        holding_days: int = 0,
    ) -> TradeCosts:
        """
        Convenience method for Iron Condor round-trip costs.

        Entry: sell short call, sell short put, buy long call, buy long put.
        Exit: buy back shorts, sell longs.
        """
        if exit_short_call is None:
            exit_short_call = short_call_premium * 0.5
        if exit_short_put is None:
            exit_short_put = short_put_premium * 0.5
        if exit_long_call is None:
            exit_long_call = long_call_premium * 0.3
        if exit_long_put is None:
            exit_long_put = long_put_premium * 0.3

        entry_legs = [
            LegCostInput(short_call_premium, "SELL", lots, lot_size),
            LegCostInput(short_put_premium, "SELL", lots, lot_size),
            LegCostInput(long_call_premium, "BUY", lots, lot_size),
            LegCostInput(long_put_premium, "BUY", lots, lot_size),
        ]
        exit_legs = [
            LegCostInput(exit_short_call, "BUY", lots, lot_size),
            LegCostInput(exit_short_put, "BUY", lots, lot_size),
            LegCostInput(exit_long_call, "SELL", lots, lot_size),
            LegCostInput(exit_long_put, "SELL", lots, lot_size),
        ]

        net_premium = short_call_premium + short_put_premium - long_call_premium - long_put_premium

        return self.calculate_trade_costs(
            entry_legs, exit_legs, net_premium,
            lot_size, lots, margin_required, holding_days,
        )

    def calculate_calendar_costs(
        self,
        back_month_cost: float,
        front_month_premium: float,
        exit_back_month: float | None = None,
        exit_front_month: float | None = None,
        lots: int = 1,
        lot_size: int = 25,
        margin_required: float = 0.0,
        holding_days: int = 0,
    ) -> TradeCosts:
        """
        Convenience method for Calendar Spread round-trip costs.

        Entry: buy back-month, sell front-month.
        Exit: sell back-month, buy front-month.
        """
        if exit_back_month is None:
            exit_back_month = back_month_cost * 1.2
        if exit_front_month is None:
            exit_front_month = front_month_premium * 0.3

        entry_legs = [
            LegCostInput(back_month_cost, "BUY", lots, lot_size),
            LegCostInput(front_month_premium, "SELL", lots, lot_size),
        ]
        exit_legs = [
            LegCostInput(exit_back_month, "SELL", lots, lot_size),
            LegCostInput(exit_front_month, "BUY", lots, lot_size),
        ]

        net_debit = back_month_cost - front_month_premium

        return self.calculate_trade_costs(
            entry_legs, exit_legs, net_debit,
            lot_size, lots, margin_required, holding_days,
        )

    # --- Margin & ITM Expiry ---

    def calculate_margin_opportunity_cost(
        self, margin_required: float, holding_days: int,
        annual_rate: float | None = None,
    ) -> float:
        """Cost of capital locked up as margin instead of earning in liquid fund."""
        if annual_rate is None:
            annual_rate = settings.COST_LIQUID_FUND_RATE_ANNUAL
        return margin_required * annual_rate * (holding_days / 365)

    def calculate_itm_expiry_stt(
        self, intrinsic_value: float, lot_size: int, lots: int,
    ) -> float:
        """
        STT on ITM options expiring in-the-money.
        Rate: 0.125% of intrinsic value (NOT premium).
        This is often a huge hidden cost — can wipe out small profits.
        """
        return intrinsic_value * lot_size * lots * self.stt_itm_expiry_rate

    # --- Slippage ---

    def estimate_spread_from_premium(self, premium: float) -> float:
        """
        Estimate bid-ask spread when actual bid/ask not available.
        Based on empirical observation of Nifty options:
          ATM (premium > 200):    ~0.8% of premium, min Rs 1
          OTM (50-200):           ~2.0% of premium, min Rs 2
          Far OTM (10-50):        ~5.0% of premium, min Rs 3
          Deep OTM (< 10):       ~15.0% of premium, min Rs 2
        """
        if premium >= 200:
            return max(1.0, premium * 0.008)
        elif premium >= 50:
            return max(2.0, premium * 0.02)
        elif premium >= 10:
            return max(3.0, premium * 0.05)
        else:
            return max(2.0, premium * 0.15)

    def _calculate_slippage(self, leg: LegCostInput) -> float:
        """Calculate slippage cost for a single leg based on the slippage model."""
        quantity = leg.lots * leg.lot_size

        if leg.bid > 0 and leg.ask > 0:
            spread = leg.ask - leg.bid
        else:
            spread = self.estimate_spread_from_premium(leg.premium)

        if self.slippage_model == SlippageModel.OPTIMISTIC:
            slippage_per_unit = spread * 0.50
        elif self.slippage_model == SlippageModel.REALISTIC:
            slippage_per_unit = spread * 0.75
        else:  # CONSERVATIVE
            slippage_per_unit = spread * 1.0 + 1.0

        return slippage_per_unit * quantity
