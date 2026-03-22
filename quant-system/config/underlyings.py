"""
Configuration for all traded underlyings.
Add new underlyings here — strategy engine picks them up automatically.

Phase 1: NIFTY only
Phase 3: NIFTY + BANKNIFTY + FINNIFTY
"""

UNDERLYINGS = {
    "NIFTY": {
        "symbol":             "NIFTY",
        "yfinance_ticker":    "^NSEI",
        "lot_size":           25,
        "tick_size":          0.05,
        "expiry_type":        "monthly",   # weeklies discontinued late 2024
        "active_from_phase":  1,           # available from Phase 1
        "capital_pct":        0.45,        # 45% of active capital in Phase 3
        "strategies":         ["IC", "CAL"],
        "iv_typical_range":   (12, 35),
        "wing_base_pts":      500,
        "event_blackout_days": 7,
        "notes": "Primary underlying. Monthly expiries only from Nov 2024.",
    },
    "BANKNIFTY": {
        "symbol":             "BANKNIFTY",
        "yfinance_ticker":    "^NSEBANK",
        "lot_size":           30,          # smaller lot = flexible sizing
        "tick_size":          0.05,
        "expiry_type":        "weekly",    # verify current SEBI status before use
        "active_from_phase":  3,
        "capital_pct":        0.35,
        "strategies":         ["IC"],      # CAL after 3 months paper trading
        "iv_typical_range":   (16, 50),
        "wing_base_pts":      700,         # wider wings for higher vol
        "event_blackout_days": 5,          # tighter — RBI hits BankNifty harder
        "notes": (
            "2x premium vs Nifty for same delta. "
            "Sensitive to RBI decisions. "
            "Paper trade 30 days before live capital."
        ),
    },
    "FINNIFTY": {
        "symbol":             "FINNIFTY",
        "yfinance_ticker":    None,        # not on yfinance — use NSE bhavcopy only
        "lot_size":           65,
        "tick_size":          0.05,
        "expiry_type":        "weekly",
        "active_from_phase":  3,
        "capital_pct":        0.20,
        "strategies":         ["IC"],      # IC only — liquidity validation required
        "iv_typical_range":   (15, 45),
        "wing_base_pts":      600,
        "event_blackout_days": 7,
        "notes": (
            "Validate OTM liquidity before going live. "
            "Avoid strikes > 2% OTM — spreads widen sharply. "
            "Start with 1 lot only."
        ),
    },
}


# Capital allocation validation (must sum to 1.00 across active underlyings)
def validate_allocation(phase: int) -> bool:
    active = [v for v in UNDERLYINGS.values() if v["active_from_phase"] <= phase]
    total = sum(u["capital_pct"] for u in active)
    assert abs(total - 1.0) < 0.01, f"Capital allocation sums to {total}, not 1.0"
    return True
