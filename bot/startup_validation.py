"""Startup validation — config consistency checks.

Extracted from `trailing_bot.validate_config` as part of the Road-to-10
monolith split. Pure function: reads CONFIG, logs warnings, returns the list
of issues for callers/tests.
"""
from __future__ import annotations

from typing import Any, List, Mapping

from modules.logging_utils import log
from bot.helpers import as_float, as_int, as_bool


def validate_config(config: Mapping[str, Any]) -> List[str]:
    """Validate CONFIG for contradictions & nonsensical combinations.

    Returns the list of issue strings (empty when everything is fine). Always
    emits log lines so existing call sites keep their behaviour.
    """
    issues: List[str] = []

    # 1. Whitelist + Blacklist overlap
    wl = set(config.get('WHITELIST', []) or [])
    bl = set(config.get('BLACKLIST', []) or [])
    overlap = wl & bl
    if overlap:
        issues.append(f"CONFIG: Markets in both WHITELIST and BLACKLIST: {overlap}")

    # 2. TP_PCT_MIN > TP_PCT_MAX
    tp_min = as_float(config.get('TP_PCT_MIN'), 0.01)
    tp_max = as_float(config.get('TP_PCT_MAX'), 0.05)
    if tp_min > tp_max:
        issues.append(f"CONFIG: TP_PCT_MIN ({tp_min}) > TP_PCT_MAX ({tp_max})")

    # 3. TIERS max_buy < min_buy
    tiers = config.get('TIERS', []) or []
    for idx, tier in enumerate(tiers):
        if not isinstance(tier, dict):
            continue
        min_buy = as_float(tier.get('min_buy'), 0)
        max_buy = as_float(tier.get('max_buy'), 9999)
        if min_buy > max_buy:
            issues.append(f"CONFIG: TIERS[{idx}] min_buy ({min_buy}) > max_buy ({max_buy})")

    # 4. DCA_MAX_BUYS < 1
    dca_max = as_int(config.get('DCA_MAX_BUYS'), 3)
    if dca_max < 1:
        issues.append(f"CONFIG: DCA_MAX_BUYS ({dca_max}) < 1")

    # 5. AI config contradictions
    if as_bool(config.get('AI_ENABLED'), False):
        ai_min = as_float(config.get('AI_MIN_CONFIDENCE'), 0.6)
        ai_max = as_float(config.get('AI_MAX_CONFIDENCE'), 1.0)
        if ai_min > ai_max:
            issues.append(f"CONFIG: AI_MIN_CONFIDENCE ({ai_min}) > AI_MAX_CONFIDENCE ({ai_max})")

    # 6. Risk limits sanity checks
    max_exp = as_float(config.get('MAX_TOTAL_EXPOSURE_EUR'), 9999)
    base_amt = as_float(config.get('BASE_AMOUNT_EUR'), 6)
    max_trades = as_int(config.get('MAX_OPEN_TRADES'), 5)
    if max_exp >= 9000:
        issues.append(f"CONFIG: MAX_TOTAL_EXPOSURE_EUR={max_exp} is effectively DISABLED (set to a real limit!)")
    elif max_exp < base_amt * max_trades:
        issues.append(
            f"CONFIG: MAX_TOTAL_EXPOSURE_EUR={max_exp} < "
            f"BASE_AMOUNT_EUR*MAX_OPEN_TRADES ({base_amt * max_trades})"
        )
    daily_loss = as_float(config.get('RISK_MAX_DAILY_LOSS'), 9999)
    weekly_loss = as_float(config.get('RISK_MAX_WEEKLY_LOSS'), 9999)
    if daily_loss >= 9000:
        issues.append(f"CONFIG: RISK_MAX_DAILY_LOSS={daily_loss} is effectively DISABLED")
    if weekly_loss >= 9000:
        issues.append(f"CONFIG: RISK_MAX_WEEKLY_LOSS={weekly_loss} is effectively DISABLED")
    if daily_loss < 9000 and weekly_loss < 9000 and daily_loss > weekly_loss:
        issues.append(
            f"CONFIG: RISK_MAX_DAILY_LOSS ({daily_loss}) > "
            f"RISK_MAX_WEEKLY_LOSS ({weekly_loss})"
        )

    if issues:
        log("[CONFIG] Validation warnings:", level='warning')
        for issue in issues:
            log(f"  - {issue}", level='warning')
    else:
        log("[CONFIG] Validation passed: no contradictions found")

    return issues


__all__ = ["validate_config"]
