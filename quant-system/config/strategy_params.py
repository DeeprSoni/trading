PARAM_SETS = {
    "base": {
        "ic_short_delta": 0.16,
        "ic_profit_target_pct": 0.50,
        "ic_min_iv_rank": 30,
        "ic_stop_loss_multiplier": 2.0,
    },
    "conservative": {
        "ic_short_delta": 0.10,
        "ic_profit_target_pct": 0.25,
        "ic_min_iv_rank": 40,
        "ic_stop_loss_multiplier": 1.5,
    },
    "aggressive": {
        "ic_short_delta": 0.20,
        "ic_profit_target_pct": 0.75,
        "ic_min_iv_rank": 20,
        "ic_stop_loss_multiplier": 2.5,
    },
    "high_iv_only": {
        "ic_short_delta": 0.16,
        "ic_profit_target_pct": 0.50,
        "ic_min_iv_rank": 50,
        "ic_stop_loss_multiplier": 2.0,
    },
}
