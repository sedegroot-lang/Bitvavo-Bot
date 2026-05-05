"""Safety-buy fallback (extracted from trailing_bot.py — road-to-10 #066 batch 6).

If the initial limit/best buy fails, retry once with a market order after a
short delay.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Tuple

from bot.shared import state


async def safety_buy(market: str, amt_eur: float, entry_price: float) -> Tuple[Optional[Any], float]:
    log = state.log
    # Lazy import to keep this module decoupled at import time.
    import trailing_bot as _tb

    place_buy = _tb.place_buy
    is_order_success = _tb.is_order_success

    buy_result = place_buy(market, amt_eur, entry_price)
    if not is_order_success(buy_result):
        try:
            log(f"⚠️ Eerste koop voor {market} mislukt, probeer safety buy (market order) na 2s...")
        except Exception:
            pass
        await asyncio.sleep(2)
        buy_result = place_buy(market, amt_eur, None, order_type="market")
        if not is_order_success(buy_result):
            try:
                log(f"❌ Safety buy voor {market} ook mislukt, sla trade over.")
            except Exception:
                pass
            return None, entry_price
    try:
        if isinstance(buy_result, dict) and buy_result.get("price"):
            entry_price = float(buy_result.get("price"))
    except Exception as e:
        try:
            log(f"entry_price failed: {e}", level="error")
        except Exception:
            pass
    return buy_result, entry_price
