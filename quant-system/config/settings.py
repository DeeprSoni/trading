import os
from dotenv import load_dotenv

load_dotenv()

# BROKER
ZERODHA_API_KEY = os.getenv("ZERODHA_API_KEY")
ZERODHA_API_SECRET = os.getenv("ZERODHA_API_SECRET")
ZERODHA_USER_ID = os.getenv("ZERODHA_USER_ID")

# ANTHROPIC
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# ────────────────────────────────────────────────────────────────
# CAPITAL STRUCTURE  (Total: Rs 7,50,000)
# ────────────────────────────────────────────────────────────────
# Before: Rs 3L idle in "reserve" earning 0%
# After:  All non-deployed capital earns yield
# ────────────────────────────────────────────────────────────────

TOTAL_CAPITAL = 750_000

CAPITAL_STRUCTURE = {
    # Active trading margin deployed per day
    "nifty_active":       90_000,   # Nifty IC/CAL margin
    "banknifty_active":   70_000,   # BankNifty IC margin  (Phase 3)
    "finnifty_active":    40_000,   # FinNifty IC margin   (Phase 3)

    # Parked capital — ALL earning yield now (none idle)
    "liquid_fund":       400_000,   # +Rs 26,000/yr at 6.5% (same-day redemption)
    "arbitrage_fund":    100_000,   # +Rs 7,500/yr at 7.5%  (low-tax, 30-day exit)
    "cash_buffer":        50_000,   # Settlement + emergency buffer in savings
}

PARKED_YIELD = {
    "liquid_fund":     0.065,
    "arbitrage_fund":  0.075,
    "cash_buffer":     0.035,
}

# Annual income from parked capital alone
# Rs 4L × 6.5% + Rs 1L × 7.5% + Rs 50K × 3.5% = Rs 35,750/yr = 4.77% on total
PARKED_CAPITAL_ANNUAL_INCOME = sum(
    CAPITAL_STRUCTURE[k] * PARKED_YIELD[k]
    for k in PARKED_YIELD
    if k in CAPITAL_STRUCTURE
)

# Initially Phase 1: only Nifty active (Rs 90K)
# Phase 3 onwards: all three underlyings active (Rs 2L total)
PHASE_1_ACTIVE_CAPITAL = 90_000
PHASE_3_ACTIVE_CAPITAL = 200_000

# Backward-compat aliases (referenced by existing code)
ACTIVE_TRADING_CAPITAL = PHASE_1_ACTIVE_CAPITAL
RESERVE_BUFFER = 0  # deprecated, all capital now earning yield
COIN_FUND_CAPITAL = CAPITAL_STRUCTURE["liquid_fund"]
CASH_BUFFER = CAPITAL_STRUCTURE["cash_buffer"]

# INSTRUMENTS
NIFTY_LOT_SIZE = 25
BANKNIFTY_LOT_SIZE = 15
PRIMARY_INSTRUMENT = "NIFTY"
NIFTY_INSTRUMENT_TOKEN = 256265  # Kite Connect instrument token for NIFTY 50

# IRON CONDOR PARAMETERS
IC_SHORT_DELTA = 0.16
IC_WING_WIDTH_POINTS = 500
IC_MIN_DTE_ENTRY = 30
IC_MAX_DTE_ENTRY = 45
IC_PROFIT_TARGET_PCT = 0.50
IC_STOP_LOSS_MULTIPLIER = 2.0
IC_TIME_STOP_DTE = 21
IC_MAX_OPEN_POSITIONS = 2
IC_MAX_PCT_CAPITAL_PER_TRADE = 0.05

# ── IC Entry Gates (v2 — relaxed) ────────────────────────────────────────────

# Gate 1: IV Rank — lowered from 30 → 20
# Rationale: IVR 20-30 is still above median; 40% more trade opportunities
IC_IVR_MIN = 20

# NEW: IV must be at least 15% above 30-day realized vol
IC_IV_ABOVE_REALIZED = 0.15

# Gate 2: VIX — replaced binary cutoff with dynamic sizing
# Old rule: skip ALL ICs when VIX > 25 (missed highest-premium windows)
# New rule: trade at any VIX, but adjust wings + size dynamically
IC_VIX_STANDARD_MAX = 25    # below: standard wings + full size
IC_VIX_ELEVATED_MAX = 35    # 25-35: wider wings + half size
IC_VIX_KILLSWITCH = 40      # above: no new ICs (genuine panic)

# Gate 5: Event blackout — reduced from 25 → 7 days
# Rationale: 25-day window was blocking ~60% of the calendar year
# New rule: avoid entries if EXPIRY falls within 3 days of a major event
IC_EVENT_BLACKOUT_DAYS = 7
IC_EVENT_EXPIRY_BLACKOUT_DAYS = 3

# Backward-compat alias
IC_MIN_IV_RANK = IC_IVR_MIN

# ── Dynamic wing width based on VIX ──────────────────────────────────────────
IC_WING_TABLE = {
    # (vix_min, vix_max): wing_points
    (0,  15): 400,
    (15, 20): 500,
    (20, 25): 600,
    (25, 30): 700,
    (30, 35): 800,
    (35, 99): 900,
}

IC_SIZE_TABLE = {
    # (vix_min, vix_max): position_size_multiplier
    (0,  25): 1.00,
    (25, 30): 0.75,
    (30, 35): 0.50,
    (35, 99): 0.25,
}


def get_ic_wing_width(vix: float) -> int:
    for (lo, hi), w in IC_WING_TABLE.items():
        if lo <= vix < hi:
            return w
    return 600


def get_ic_size_multiplier(vix: float) -> float:
    for (lo, hi), m in IC_SIZE_TABLE.items():
        if lo <= vix < hi:
            return m
    return 0.50

# CALENDAR SPREAD PARAMETERS
# Nifty weekly expiries were discontinued by NSE in late 2024.
# Front month uses the nearest MONTHLY expiry (~20-30 DTE) instead of weeklies.
CAL_BACK_MONTH_MIN_DTE = 60
CAL_BACK_MONTH_MAX_DTE = 75
CAL_FRONT_MONTH_MIN_DTE = 20  # Nearest monthly expiry (was 7 for weeklies)
CAL_FRONT_MONTH_MAX_DTE = 35  # Upper bound for front month selection
CAL_PROFIT_TARGET_PCT = 0.50
CAL_BACK_MONTH_CLOSE_DTE = 25
CAL_MAX_MOVE_PCT_TO_ADJUST = 0.02
CAL_MAX_MOVE_PCT_TO_CLOSE = 0.04
CAL_MAX_OPEN_POSITIONS = 2

# RISK CONTROLS
VIX_MAX_FOR_IC = IC_VIX_STANDARD_MAX  # backward compat
VIX_HIGH_THRESHOLD = 28
ACCOUNT_DRAWDOWN_SIZE_DOWN = 0.03
ACCOUNT_DRAWDOWN_STOP = 0.05
ROLLING_WIN_RATE_YELLOW = 0.62
ROLLING_WIN_RATE_RED = 0.58
PROFIT_FACTOR_YELLOW = 1.1
PROFIT_FACTOR_RED = 1.0

# COSTS (Updated to FY 2024-25 rates)
COST_BROKERAGE_PER_ORDER = 20
COST_BROKERAGE_GST_RATE = 0.18
COST_STT_SELL_RATE = 0.000625  # 0.0625% on sell side (Budget 2024)
COST_STT_ITM_EXPIRY_RATE = 0.00125  # 0.125% of intrinsic value on ITM expiry
COST_NSE_EXCHANGE_RATE = 0.00053  # NSE F&O transaction charge
COST_SEBI_FEE_RATE = 0.000001  # Rs 10 per crore = 0.0001%
COST_STAMP_DUTY_RATE = 0.00003  # 0.003% on buy side
COST_SLIPPAGE_PER_UNIT_PER_LEG = 2
COST_LIQUID_FUND_RATE_ANNUAL = 0.065

# TELEGRAM ALERTS (primary notification channel)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# SYSTEM
DATABASE_URL = "sqlite:///./quant_system.db"
DATABASE_WAL_MODE = True
TIMEZONE = "Asia/Kolkata"
MARKET_OPEN = "09:15"
MARKET_CLOSE = "15:30"
DATA_REFRESH_INTERVAL_MIN = 15
POSITION_POLL_INTERVAL_SEC = 60
