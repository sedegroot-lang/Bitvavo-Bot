"""bot.exit_pipeline — Pure exit-decision helpers (Road-to-10 fase 2).

Side-effect-free helpers that return an `ExitDecision`. They do NOT replace
the existing trailing/sync loop in `bot/trailing.py` — they sit alongside as
unit-testable functions that the loop can adopt incrementally.

⚠️ FIX-LOG #003: NO time-based exits and NO loss-sells. The decisions here
honor that strictly — `should_trail_lock_breakeven` is the only exit-related
suggestion and it triggers ONLY when the trade is already in profit (or at
worst at break-even with fees recovered).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(slots=True)
class ExitDecision:
    market: str
    action: str  # 'hold' | 'trail_tighter' | 'lock_breakeven' | 'partial_tp'
    reason: str
    new_trailing_pct: Optional[float] = None
    sell_amount_pct: Optional[float] = None  # for partial_tp
    metadata: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def derive_unrealised_pct(buy_price: float, current_price: float) -> float:
    if buy_price <= 0 or current_price <= 0:
        return 0.0
    return (current_price - buy_price) / buy_price * 100.0


def should_lock_breakeven(
    *,
    market: str,
    buy_price: float,
    current_price: float,
    highest_price: float,
    fee_buffer_pct: float = 0.5,
    activation_pct: float = 1.5,
) -> ExitDecision:
    """Return lock_breakeven when trade has been in profit ≥ activation_pct
    AND has retraced at least 50% of the gain. Never triggers on losing trade.
    """
    high_pct = derive_unrealised_pct(buy_price, highest_price)
    cur_pct = derive_unrealised_pct(buy_price, current_price)

    if high_pct < activation_pct:
        return ExitDecision(
            market=market,
            action="hold",
            reason="not_enough_profit_seen",
            metadata={"high_pct": high_pct, "cur_pct": cur_pct},
        )

    # Retraced ≥ 50% of high
    retraced = cur_pct < (high_pct * 0.5)
    if retraced and cur_pct >= -fee_buffer_pct:
        # Lock at break-even + fee buffer
        new_stop_pct = max(fee_buffer_pct, cur_pct - 0.3)  # tight trail just below current
        return ExitDecision(
            market=market,
            action="lock_breakeven",
            reason=f"retraced_50pct(high={high_pct:.2f}%,cur={cur_pct:.2f}%)",
            new_trailing_pct=new_stop_pct,
            metadata={"high_pct": high_pct, "cur_pct": cur_pct},
        )
    return ExitDecision(
        market=market, action="hold", reason="still_holding", metadata={"high_pct": high_pct, "cur_pct": cur_pct}
    )


def should_partial_tp(
    *,
    market: str,
    buy_price: float,
    current_price: float,
    partial_already_taken_pct: float,
    target_pct: float = 5.0,
    sell_fraction: float = 0.5,
) -> ExitDecision:
    """Take partial profit when up ≥ target_pct AND no partial taken yet."""
    cur_pct = derive_unrealised_pct(buy_price, current_price)
    if partial_already_taken_pct > 0:
        return ExitDecision(market=market, action="hold", reason="partial_already_taken")
    if cur_pct < target_pct:
        return ExitDecision(market=market, action="hold", reason=f"below_target({cur_pct:.2f}<{target_pct})")
    return ExitDecision(
        market=market,
        action="partial_tp",
        reason=f"at_target({cur_pct:.2f}%)",
        sell_amount_pct=sell_fraction * 100,
        metadata={"cur_pct": cur_pct},
    )
