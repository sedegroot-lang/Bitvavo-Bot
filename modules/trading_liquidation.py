"""Liquidation helpers for freeing exposure and handling saldo floods."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

# Import archive_trade for permanent trade storage
try:
    from modules.trade_archive import archive_trade
except ImportError:
    archive_trade = None


@dataclass
class LiquidationContext:
    config: Dict[str, Any]
    log: Callable[[str], None]
    get_current_price: Callable[[str], Optional[float]]
    place_sell: Callable[[str, float], Any]
    realized_profit: Callable[[float, float, float], float]
    save_trades: Callable[[], None]
    cleanup_trades: Callable[[], None]
    pending_saldo_path: str = "pending_saldo.json"
    cancel_open_buys_fn: Optional[Callable[[], None]] = None
    refresh_balance_fn: Optional[Callable[[], None]] = None


class LiquidationManager:
    """Encapsulates guarding logic around saldo floods and capacity freeing."""

    def __init__(self, ctx: LiquidationContext) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------------
    # Saldo flood guard — NON-DESTRUCTIVE
    # Instead of force-selling at a loss, this version:
    # 1. Cancels pending buy orders (frees EUR)
    # 2. Forces a balance cache refresh
    # 3. Sets a temporary cooldown to pause new entries
    # ------------------------------------------------------------------

    def saldo_flood_guard(
        self,
        open_trades: Dict[str, Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
        market_profits: Dict[str, float],
    ) -> None:
        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log

        # Check old destructive floodguard — disabled by default
        floodguard_cfg = cfg.get("FLOODGUARD", {})
        if floodguard_cfg.get("enabled", False):
            # Legacy path — only if user explicitly re-enables old behavior
            self._legacy_flood_guard(open_trades, closed_trades, market_profits)
            return

        # New smart saldo guard
        guard_cfg = cfg.get("SALDO_GUARD", {})
        if not guard_cfg.get("enabled", True):
            return

        threshold = int(guard_cfg.get("threshold", 5))
        cooldown_secs = float(guard_cfg.get("cooldown_seconds", 300))

        count = self._get_pending_saldo_count()
        if count <= threshold:
            return

        log(
            f"⚠️ Saldo Guard: {count} saldo errors > drempel {threshold} — "
            f"beschermingsmaatregelen actief (GEEN posities verkocht)",
            level="warning",
        )

        # 1. Cancel pending buy orders to free up EUR
        if guard_cfg.get("cancel_pending_buys", True) and ctx.cancel_open_buys_fn:
            try:
                ctx.cancel_open_buys_fn()
                log("🛡️ Saldo Guard: openstaande BUY orders geannuleerd", level="warning")
            except Exception as exc:
                log(f"Saldo Guard: cancel buys mislukt: {exc}", level="error")

        # 2. Force refresh EUR balance cache
        if guard_cfg.get("force_refresh_balance", True) and ctx.refresh_balance_fn:
            try:
                ctx.refresh_balance_fn()
                log("🛡️ Saldo Guard: EUR balance cache vernieuwd", level="info")
            except Exception as exc:
                log(f"Saldo Guard: balance refresh mislukt: {exc}", level="error")

        # 3. Set cooldown — new entries paused for N seconds
        cfg["_SALDO_COOLDOWN_UNTIL"] = time.time() + cooldown_secs
        log(
            f"🛡️ Saldo Guard: nieuwe entries gepauzeerd voor {int(cooldown_secs)}s",
            level="warning",
        )

        # 4. Clear the pending saldo file to prevent re-triggering
        try:
            path = ctx.pending_saldo_path
            with open(path, "w", encoding="utf-8") as fh:
                json.dump([], fh)
        except Exception:
            pass

    def _legacy_flood_guard(
        self,
        open_trades: Dict[str, Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
        market_profits: Dict[str, float],
    ) -> None:
        """Legacy flood guard — PERMANENTLY DISABLED.

        Previously force-sold positions at a loss. This caused unwanted loss sells
        (e.g. DOT -5.4%, INJ -5.3%). Assets should NEVER be sold at a loss except
        by the stop-loss mechanism. This method now delegates to the safe
        non-destructive saldo guard instead.
        """
        ctx = self.ctx
        log = ctx.log
        log(
            "⚠️ Legacy flood guard called but DISABLED — delegating to safe saldo guard. "
            "Positions will NOT be force-sold at a loss.",
            level="warning",
        )
        # Override: run the safe non-destructive path instead
        # Temporarily clear the FLOODGUARD flag to prevent infinite recursion
        cfg = ctx.config
        old_val = cfg.get("FLOODGUARD", {}).get("enabled", False)
        if isinstance(cfg.get("FLOODGUARD"), dict):
            cfg["FLOODGUARD"]["enabled"] = False
        try:
            self.saldo_flood_guard(open_trades, closed_trades, market_profits)
        finally:
            if isinstance(cfg.get("FLOODGUARD"), dict):
                cfg["FLOODGUARD"]["enabled"] = old_val

    def _get_pending_saldo_count(self) -> int:
        try:
            path = self.ctx.pending_saldo_path
            with open(path, "r", encoding="utf-8") as fh:
                pending = json.load(fh)
            return len(pending) if isinstance(pending, list) else 0
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Free tiny positions when at capacity
    # ------------------------------------------------------------------
    def free_capacity_if_needed(
        self,
        open_trades: Dict[str, Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
        market_profits: Dict[str, float],
    ) -> None:
        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log

        current = len(open_trades) if isinstance(open_trades, dict) else 0
        max_trades = int(cfg.get("MAX_OPEN_TRADES", 3))
        if current < max_trades:
            return

        max_per_cycle = max(0, int(cfg.get("AUTO_FREE_MAX_PER_CYCLE", 1)))
        value_threshold = float(cfg.get("AUTO_FREE_MAX_VALUE_EUR", 5.0))
        if max_per_cycle <= 0:
            return

        valuations = []
        for market, trade in open_trades.items():
            if not isinstance(trade, dict):
                continue
            price = ctx.get_current_price(market)
            amount = trade.get("amount", 0.0)
            if price is None or amount is None:
                continue
            try:
                value = float(price) * float(amount)
            except Exception:
                continue
            buy_price = float(trade.get("buy_price", price) or price)
            # Calculate profit percentage for this position
            profit_pct = (price - buy_price) / buy_price if buy_price > 0 else 0
            valuations.append((value, market, float(amount), float(price), buy_price, profit_pct))

        valuations.sort(key=lambda item: item[0])
        freed = 0
        for value, market, amount, price, buy_price, profit_pct in valuations:
            if freed >= max_per_cycle:
                break
            if value > value_threshold:
                break
            if amount <= 0:
                continue
            
            # PROTECTION: Don't auto-free positions that are in loss
            # Only free positions that are at least break-even (including ~0.5% for fees)
            min_profit_pct = float(cfg.get("AUTO_FREE_MIN_PROFIT_PCT", 0.005))  # Default 0.5% to cover fees
            if profit_pct < min_profit_pct:
                log(
                    f"Auto-free: skip {market} (waarde {value:.2f} EUR) - verlies {profit_pct*100:.2f}% < min {min_profit_pct*100:.1f}%",
                    level="info",
                )
                continue
            
            log(
                f"Auto-free: probeer {market} (waarde {value:.2f} EUR, winst {profit_pct*100:.2f}%) te sluiten.",
                level="info",
            )
            sell_resp = ctx.place_sell(market, amount, sell_all=True)
            sell_ok = (
                isinstance(sell_resp, dict)
                and not sell_resp.get('error')
                and not sell_resp.get('errorCode')
            )
            if sell_ok:
                trade = open_trades.get(market, {})
                sell_revenue = price * amount
                invested_eur = float(trade.get("invested_eur", 0) or 0)
                total_invested_eur = float(trade.get("total_invested_eur", invested_eur) or invested_eur)
                partial_tp_returned = float(trade.get("partial_tp_returned_eur", 0) or 0)
                # Profit = total revenue (sell + partial TPs) - total cost
                total_trade_profit = (sell_revenue + partial_tp_returned) - total_invested_eur
                closed_entry = {
                    "market": market,
                    "buy_price": buy_price,
                    "sell_price": price,
                    "amount": amount,
                    "profit": round(total_trade_profit, 4),
                    "invested_eur": invested_eur,
                    "total_invested_eur": total_invested_eur,
                    "initial_invested_eur": float(trade.get("initial_invested_eur", 0) or 0),
                    "partial_tp_returned_eur": partial_tp_returned,
                    "timestamp": time.time(),
                    "reason": "auto_free_slot",
                }
                # Archive trade permanently
                if archive_trade:
                    try:
                        archive_trade(**closed_entry)
                    except Exception:
                        pass
                closed_trades.append(closed_entry)
                market_profits[market] = market_profits.get(market, 0.0) + total_trade_profit
                open_trades.pop(market, None)
                freed += 1
            else:
                _err = sell_resp.get('error', 'unknown') if isinstance(sell_resp, dict) else str(sell_resp)
                log(
                    f"Auto-free: verkoop van {market} mislukt ({_err}), positie blijft open.",
                    level="warning",
                )

        if freed:
            ctx.save_trades()
            ctx.cleanup_trades()
