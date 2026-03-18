"""Dollar-cost averaging helper module."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
from modules.logging_utils import file_lock, locked_write_json
import uuid


@dataclass
class DCASettings:
    enabled: bool
    dynamic: bool
    max_buys: int
    drop_pct: float
    step_multiplier: float
    amount_eur: float
    size_multiplier: float
    max_buys_per_iteration: Optional[int] = None


@dataclass
class DCAContext:
    config: Dict[str, Any]
    safe_call: Callable[..., Any]
    bitvavo: Any
    log: Callable[[str], None]
    current_open_exposure_eur: Callable[[], float]
    get_min_order_size: Callable[[str], float]
    place_buy: Callable[[str, float, float], Any]
    is_order_success: Callable[[Any], bool]
    save_trades: Callable[[], None]
    get_candles: Callable[[str, str, int], Any]
    close_prices: Callable[[Any], List[float]]
    rsi: Callable[[List[float], int], Optional[float]]
    trade_log_path: str
    get_market_perf_snapshot: Optional[Callable[[str], Optional[Dict[str, Any]]]] = None
    get_market_size_multiplier: Optional[Callable[[str, Optional[Dict[str, Any]]], float]] = None
    get_ai_regime_bias: Optional[Callable[[], Tuple[str, float]]] = None
    send_alert: Optional[Callable[[str], None]] = None


class DCAManager:
    """Encapsulates DCA execution logic."""

    def __init__(self, ctx: DCAContext) -> None:
        self.ctx = ctx
        self._audit_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data', 'dca_audit.log'))
        self._smart_dca_wait_since: Dict[str, float] = {}  # market -> first-block timestamp

    def _log(self, msg: str, level: str = 'info') -> None:
        """Wrapper for ctx.log — prevents AttributeError in exception handlers."""
        try:
            self.ctx.log(msg, level=level)
        except Exception:
            pass

    def _compute_perf_metrics(self) -> Dict[str, Optional[float]]:
        """Derive simple performance stats (win rate, max drawdown) from trade_log for sizing guards."""
        out: Dict[str, Optional[float]] = {"win_rate": None, "max_drawdown": None}
        trade_log_path = getattr(self.ctx, 'trade_log_path', None)
        if not trade_log_path or not os.path.exists(trade_log_path):
            return out
        try:
            with open(trade_log_path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            closed = data.get('closed', []) if isinstance(data, dict) else []
            pnl_list = [float(t.get('profit', 0) or 0) for t in closed if isinstance(t, dict)]
            if pnl_list:
                wins = sum(1 for p in pnl_list if p > 0)
                out["win_rate"] = wins / len(pnl_list)
                try:
                    cum_pnl = np.cumsum(pnl_list)
                    peak = np.maximum.accumulate(cum_pnl)
                    out["max_drawdown"] = float(np.max(peak - cum_pnl)) if len(cum_pnl) > 1 else 0.0
                except Exception:
                    out["max_drawdown"] = float(max(pnl_list) - min(pnl_list)) if len(pnl_list) > 1 else 0.0
        except Exception:
            return out
        return out

    def _record_dca_audit(self, market: str, trade: Dict[str, Any], status: str, reason: str, extra: Optional[Dict[str, Any]] = None) -> None:
        """Append a small JSON line for DCA decisions to aid debugging of missed safety buys."""
        entry = {
            "ts": time.time(),
            "market": market,
            "status": status,
            "reason": reason,
        }
        try:
            entry["dca_buys"] = int(trade.get("dca_buys", 0))
        except Exception:
            entry["dca_buys"] = None
        try:
            entry["dca_next_price"] = float(trade.get("dca_next_price", 0) or 0)
        except Exception:
            entry["dca_next_price"] = None
        try:
            entry["buy_price"] = float(trade.get("buy_price", 0) or 0)
        except Exception:
            entry["buy_price"] = None
        try:
            entry["amount"] = float(trade.get("amount", 0) or 0)
        except Exception:
            entry["amount"] = None
        if extra:
            try:
                entry.update(extra)
            except Exception as e:
                self._log(f"update failed: {e}", level='debug')
        try:
            os.makedirs(os.path.dirname(self._audit_path), exist_ok=True)
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception as e:
            self._log(f"makedirs failed: {e}", level='warning')

    def _cap_watchlist_amount(self, trade: Dict[str, Any], eur_amount: float) -> float:
        try:
            cfg = self.ctx.config
        except Exception:
            return eur_amount
        settings = cfg.get('WATCHLIST_SETTINGS') or {}
        if not (trade.get('watchlist_candidate') and settings.get('enabled', True)):
            return eur_amount
        try:
            cap = float(settings.get('micro_trade_amount_eur', eur_amount))
        except Exception:
            cap = eur_amount
        return float(min(eur_amount, cap)) if cap > 0 else eur_amount

    def handle_trade(
        self,
        market: str,
        trade: Dict[str, Any],
        current_price: Optional[float],
        settings: DCASettings,
        *,
        partial_tp_levels: List[Any],
    ) -> None:
        """Mutate *trade* with DCA logic for the provided market."""

        if not settings.enabled:
            self._record_dca_audit(market, trade, "skip", "dca_disabled")
            return
        if current_price is None:
            self._record_dca_audit(market, trade, "skip", "no_current_price")
            return

        # DCA cooldown after sync: skip DCA for 5 minutes after a position is synced
        # to prevent cascading DCAs from potentially inaccurate buy_price
        import time as _time_mod
        synced_at = trade.get('synced_at')
        if synced_at:
            cooldown_sec = float(self.ctx.config.get('DCA_SYNC_COOLDOWN_SEC', 300))
            elapsed = _time_mod.time() - float(synced_at)
            if elapsed < cooldown_sec:
                self.ctx.log(
                    f"DCA voor {market} overgeslagen: sync cooldown ({cooldown_sec - elapsed:.0f}s remaining)"
                )
                self._record_dca_audit(market, trade, "skip", "sync_cooldown", {"elapsed": elapsed, "cooldown": cooldown_sec})
                return

        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log
        cp = float(current_price)

        watch_cfg = cfg.get('WATCHLIST_SETTINGS') or {}
        if trade.get('watchlist_candidate') and watch_cfg.get('enabled', True):
            if watch_cfg.get('disable_dca', True):
                log(f"DCA skipped for {market}: watchlist guard disabled DCA")
                self._record_dca_audit(market, trade, "skip", "watchlist_disabled")
                return

        perf_stats = None
        perf_mult = 1.0
        regime_label = "neutral"
        regime_mult = 1.0
        size_bias = 1.0

        if ctx.get_market_perf_snapshot:
            try:
                perf_stats = ctx.get_market_perf_snapshot(market)
            except Exception:
                perf_stats = None

        if ctx.get_market_size_multiplier:
            try:
                perf_mult = float(ctx.get_market_size_multiplier(market, perf_stats))
            except Exception:
                perf_mult = 1.0

        if ctx.get_ai_regime_bias:
            try:
                regime_label, regime_mult = ctx.get_ai_regime_bias()
            except Exception:
                regime_label, regime_mult = "neutral", 1.0

        try:
            size_bias = float(perf_mult) * float(regime_mult)
        except Exception:
            size_bias = 1.0
        size_bias = max(0.0, size_bias)

        if size_bias <= 0.0:
            log(
                f"DCA voor {market} geblokkeerd: performance bias {perf_mult:.2f}, regime '{regime_label}' multiplier {regime_mult:.2f} levert 0 exposure."
            )
            return

        # Ensure tracking fields exist
        trade.setdefault("buy_price", float(cp))
        trade.setdefault("highest_price", float(cp))
        trade.setdefault("tp_levels_done", [False] * len(partial_tp_levels))
        trade.setdefault("dca_buys", 0)
        try:
            trade.setdefault(
                "dca_next_price", float(trade.get("buy_price", cp)) * (1 - settings.drop_pct)
            )
        except Exception:
            trade.setdefault("dca_next_price", float(cp))
        trade.setdefault("tp_last_time", 0.0)
        trade.setdefault("last_dca_price", trade.get("last_dca_price", trade.get("buy_price")))
        trade.setdefault("opened_ts", trade.get("timestamp"))

        # DCA should use a more lenient RSI check than initial entries
        # Allow DCA when RSI < threshold (default 60), since we're averaging down
        # When RSI_DCA_THRESHOLD >= 100 or RSI unavailable, always allow DCA
        rsi_dca_threshold = float(cfg.get("RSI_DCA_THRESHOLD", 60))
        try:
            candles = ctx.get_candles(market, "1m", 60)
        except Exception:
            candles = []
        prices = ctx.close_prices(candles) if candles else []
        try:
            rsi_val = ctx.rsi(prices, 14) if prices else None
        except Exception:
            rsi_val = None
        
        # Always allow DCA if threshold >= 100 (effectively disabled) or RSI unavailable
        if rsi_dca_threshold >= 100:
            allow_dca = True
        elif rsi_val is None:
            allow_dca = True  # Don't block DCA just because RSI data is missing
            ctx.log(f"DCA for {market}: RSI unavailable, allowing DCA anyway")
        else:
            allow_dca = rsi_val <= rsi_dca_threshold

        if not allow_dca:
            rsi_str = f"{rsi_val:.1f}" if isinstance(rsi_val, (int, float)) else "n/a"
            ctx.log(f"DCA blocked for {market}: RSI {rsi_str} > {rsi_dca_threshold}")
            self._record_dca_audit(market, trade, "skip", "rsi_block", {"rsi": rsi_val, "rsi_threshold": rsi_dca_threshold})
            return

        # --- SMART DCA: Volatility-aware timing (Bollinger Band squeeze) ---
        # When SMART_DCA_ENABLED=true, delay DCA until selling exhaustion is detected
        # (price below lower BB + bandwidth contracting). Falls back to standard DCA
        # when insufficient data or when smart DCA is disabled.
        if bool(cfg.get("SMART_DCA_ENABLED", False)):
            try:
                import time as _time
                from core.smart_dca import should_smart_dca
                _buy_px = float(trade.get("buy_price", cp) or cp)
                _drop_actual = (_buy_px - cp) / _buy_px if _buy_px > 0 else 0
                _deep_drop_mult = float(cfg.get("SMART_DCA_DEEP_DROP_MULT", 1.5))
                _timeout_sec = float(cfg.get("SMART_DCA_TIMEOUT_SEC", 1200))  # 20 min default

                # Deep drop override: if drop >> trigger, DCA immediately (opportunity cost too high)
                _is_deep_drop = _drop_actual >= settings.drop_pct * _deep_drop_mult

                # Timeout override: if we've been waiting too long, fall back to standard DCA
                _wait_start = self._smart_dca_wait_since.get(market)
                _timed_out = _wait_start is not None and (_time.time() - _wait_start) > _timeout_sec

                if _is_deep_drop:
                    self._smart_dca_wait_since.pop(market, None)
                    ctx.log(f"Smart DCA {market}: deep drop override ({_drop_actual*100:.1f}% >> {settings.drop_pct*100:.1f}%), executing DCA")
                elif _timed_out:
                    self._smart_dca_wait_since.pop(market, None)
                    ctx.log(f"Smart DCA {market}: timeout after {(_time.time() - _wait_start)/60:.0f}min, executing DCA")
                else:
                    _smart_ok, _smart_reason = should_smart_dca(
                        prices, cp, _buy_px,
                        dca_drop_pct=settings.drop_pct,
                        bb_window=int(cfg.get("SMART_DCA_BB_WINDOW", 20)),
                        bandwidth_threshold=float(cfg.get("SMART_DCA_BW_THRESHOLD", 0.04)),
                    )
                    if not _smart_ok and _smart_reason == "waiting_for_squeeze":
                        if market not in self._smart_dca_wait_since:
                            self._smart_dca_wait_since[market] = _time.time()
                        _waited = (_time.time() - self._smart_dca_wait_since[market]) / 60
                        ctx.log(f"Smart DCA {market}: waiting for BB squeeze ({_waited:.0f}min, timeout {_timeout_sec/60:.0f}min)")
                        self._record_dca_audit(market, trade, "skip", "smart_dca_waiting")
                        return
                    else:
                        self._smart_dca_wait_since.pop(market, None)
            except Exception:
                pass  # Fall through to standard DCA on any error

        # --- HYBRID DCA MODE ---
        # When DCA_HYBRID=true (or both DCA_ENABLED and DCA_PYRAMID_UP are true):
        #   - Position in LOSS  → average-down (fixed/dynamic DCA)
        #   - Position in PROFIT → pyramid-up (add to winners)
        # This gives the best of both worlds for volatile altcoins.
        pyramid_up = bool(cfg.get("DCA_PYRAMID_UP", False))
        hybrid_mode = bool(cfg.get("DCA_HYBRID", False)) or (pyramid_up and settings.enabled)
        
        buy_price = float(trade.get("buy_price", cp) or cp)
        in_profit = cp > buy_price if buy_price > 0 else False
        
        if hybrid_mode:
            if in_profit and pyramid_up:
                # Position is in profit → pyramid up (add to winner)
                ctx.log(f"DCA HYBRID {market}: in profit ({((cp/buy_price)-1)*100:.1f}%), using pyramid-up mode")
                self._execute_pyramid_up(market, trade, cp, settings, size_bias)
            elif not in_profit:
                # Position is in loss → average down
                ctx.log(f"DCA HYBRID {market}: in loss ({((cp/buy_price)-1)*100:.1f}%), using average-down mode")
                if not settings.dynamic:
                    self._execute_fixed_dca(market, trade, cp, settings, size_bias)
                else:
                    self._execute_dynamic_dca(market, trade, cp, settings, size_bias)
            else:
                # In profit but pyramid_up not enabled → skip (wait for loss or enable pyramid)
                self._record_dca_audit(market, trade, "skip", "hybrid_in_profit_no_pyramid")
        elif pyramid_up:
            self._execute_pyramid_up(market, trade, cp, settings, size_bias)
        elif not settings.dynamic:
            self._execute_fixed_dca(market, trade, cp, settings, size_bias)
        else:
            self._execute_dynamic_dca(market, trade, cp, settings, size_bias)

    # ------------------------------------------------------------------
    # Pyramid-up: only add to winning positions
    # ------------------------------------------------------------------
    def _execute_pyramid_up(
        self,
        market: str,
        trade: Dict[str, Any],
        current_price: float,
        settings: DCASettings,
        size_bias: float,
    ) -> None:
        """DCA only when position is >= PYRAMID_MIN_PROFIT_PCT in profit.

        Config keys:
          DCA_PYRAMID_UP              (bool)  — master switch
          DCA_PYRAMID_MIN_PROFIT_PCT  (float) — min profit % to pyramid (default 0.03 = 3%)
          DCA_PYRAMID_SCALE_DOWN      (float) — each successive buy is N× smaller (default 0.7)
          DCA_PYRAMID_MAX_ADDS        (int)   — max pyramid additions (default 2)
        """
        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log

        min_profit_pct = float(cfg.get("DCA_PYRAMID_MIN_PROFIT_PCT", 0.03))
        scale_down = float(cfg.get("DCA_PYRAMID_SCALE_DOWN", 0.7))
        max_adds = int(cfg.get("DCA_PYRAMID_MAX_ADDS", 2))

        buy_price = float(trade.get("buy_price", current_price) or current_price)
        if buy_price <= 0:
            self._record_dca_audit(market, trade, "skip", "no_buy_price")
            return

        profit_pct = (current_price / buy_price) - 1
        pyramid_buys = int(trade.get("dca_buys", 0) or 0)

        if pyramid_buys >= max_adds:
            self._record_dca_audit(market, trade, "skip", "pyramid_max_reached",
                                   {"pyramid_buys": pyramid_buys, "max": max_adds})
            return

        if profit_pct < min_profit_pct:
            self._record_dca_audit(market, trade, "skip", "not_in_profit",
                                   {"profit_pct": round(profit_pct, 4), "min": min_profit_pct})
            return

        # Position size decreases with each pyramid level
        eur_amount = float(settings.amount_eur) * float(size_bias) * (scale_down ** pyramid_buys)

        # Headroom check
        max_total = float(cfg.get("MAX_TOTAL_EXPOSURE_EUR", 0) or 0)
        if max_total > 0:
            try:
                current_exposure = ctx.current_open_exposure_eur()
                if current_exposure + eur_amount > max_total:
                    log(f"Pyramid DCA blocked for {market}: exposure €{current_exposure:.2f} + €{eur_amount:.2f} > max €{max_total:.2f}")
                    self._record_dca_audit(market, trade, "skip", "pyramid_max_exposure")
                    return
            except Exception:
                pass

        try:
            base_amount = eur_amount / float(current_price)
        except Exception:
            base_amount = 0.0

        min_size = ctx.get_min_order_size(market)
        if base_amount < min_size:
            log(f"Pyramid DCA for {market} skipped (too small): {base_amount:.8f} < min {min_size}")
            self._record_dca_audit(market, trade, "skip", "pyramid_under_min")
            return

        buy_result = ctx.place_buy(market, eur_amount, current_price)
        if not ctx.is_order_success(buy_result):
            log(f"Pyramid DCA buy for {market} failed")
            self._record_dca_audit(market, trade, "fail", "pyramid_order_failed")
            return

        # Update trade state
        old_amount = float(trade.get("amount", 0) or 0)
        old_invested = float(trade.get("invested_eur", 0) or 0) or (buy_price * old_amount)
        new_invested = old_invested + eur_amount
        new_amount = old_amount + base_amount
        new_avg_price = new_invested / new_amount if new_amount > 0 else buy_price

        trade["buy_price"] = round(new_avg_price, 8)
        trade["amount"] = round(new_amount, 8)
        trade["invested_eur"] = round(new_invested, 4)
        trade["total_invested_eur"] = round(
            float(trade.get("total_invested_eur", 0) or 0) + eur_amount, 4
        )
        trade["dca_buys"] = pyramid_buys + 1
        trade["last_dca_price"] = current_price

        log(
            f"✅ Pyramid DCA #{pyramid_buys + 1} for {market}: "
            f"+€{eur_amount:.2f} at {current_price:.4f} "
            f"(profit {profit_pct*100:.1f}%, new avg {new_avg_price:.4f})"
        )
        self._record_dca_audit(market, trade, "executed", "pyramid_up", {
            "profit_pct": round(profit_pct, 4),
            "eur_amount": round(eur_amount, 2),
            "new_avg": round(new_avg_price, 8),
        })
        ctx.save_trades()

    # ------------------------------------------------------------------
    # Fixed ladder implementation
    # ------------------------------------------------------------------
    def _execute_fixed_dca(
        self,
        market: str,
        trade: Dict[str, Any],
        current_price: float,
        settings: DCASettings,
        size_bias: float,
    ) -> None:
        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log

        perf_metrics = self._compute_perf_metrics()
        dd_threshold = float(cfg.get("BASE_AMOUNT_EUR", 0) or 0)
        dd_penalty = 1.0
        try:
            max_dd = perf_metrics.get("max_drawdown")
            if isinstance(max_dd, (int, float)) and dd_threshold > 0 and max_dd > dd_threshold:
                dd_penalty = 0.8
        except Exception as e:
            self.ctx.log(f"[ERROR] DCA dd_penalty calculation failed: {e}")

        buys_this_call = 0
        max_per_iter = int(settings.max_buys_per_iteration) if getattr(settings, 'max_buys_per_iteration', None) else settings.max_buys
        while trade.get("dca_buys", 0) < settings.max_buys and buys_this_call < max_per_iter:
            index = int(trade.get("dca_buys", 0))
            step_pct = float(settings.drop_pct) * (float(settings.step_multiplier) ** index)
            target_price = float(trade.get("buy_price", current_price)) * (1 - step_pct)
            trade["dca_next_price"] = target_price  # keep persisted target in sync with live calculation
            if current_price > target_price:
                self._record_dca_audit(market, trade, "skip", "price_above_target", {"price": current_price, "target": target_price, "step_index": index})
                break

            # Use per-trade dynamic DCA amount if available, else global setting
            _per_trade_dca = float(trade.get('dca_amount_eur', 0) or 0)
            _base_dca = _per_trade_dca if _per_trade_dca >= 5.0 else float(settings.amount_eur)
            eur_amount = (
                _base_dca
                * float(size_bias)
                * (float(settings.size_multiplier) ** index)
            )
            eur_amount *= dd_penalty
            # Floor at DCA_MIN_AMOUNT_EUR so late levels keep buying instead of stopping
            dca_floor = float(cfg.get('DCA_MIN_AMOUNT_EUR', 5.0) or 5.0)
            if eur_amount < dca_floor:
                eur_amount = dca_floor
            eur_amount = self._cap_watchlist_amount(trade, eur_amount)
            # Try to reserve headroom across processes
            reservation_id = None
            reserved_amount = eur_amount
            try:
                max_total = float(cfg.get("MAX_TOTAL_EXPOSURE_EUR", 0) or 0)
                if max_total > 0:
                    # attempt reservation (will succeed only if headroom available)
                    reservation_id, reserved_amount = self._reserve_headroom(eur_amount, max_total, ctx)
                    if reservation_id is None or reserved_amount <= 0:
                        # no headroom available
                        self._record_dca_audit(market, trade, "skip", "no_headroom", {"requested_eur": eur_amount, "max_total": max_total})
                        break
                    eur_amount = reserved_amount
            except Exception as e:
                self.ctx.log(f"[ERROR] DCA headroom reservation failed for {market}: {e}")
                reservation_id = None
                reserved_amount = eur_amount

            try:
                base_amount = eur_amount / float(current_price)
            except Exception:
                base_amount = 0.0

            min_size = ctx.get_min_order_size(market)
            if base_amount < min_size:
                log(
                    f"DCA voor {market} overgeslagen (te klein): {base_amount:.8f} < min {min_size}"
                )
                # NOTE: Do NOT set dca_buys = max_buys here — that corrupts the counter
                # when no actual DCA was executed. Just break and retry next iteration.
                self._record_dca_audit(market, trade, "skip", "under_min_size", {"base_amount": base_amount, "min_size": min_size})
                break

            buy_result = ctx.place_buy(market, eur_amount, current_price)
            if not ctx.is_order_success(buy_result):
                log(f"DCA buy voor {market} mislukt.")
                # release reservation if purchase failed
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level='warning')
                self._record_dca_audit(market, trade, "fail", "order_failed", {"eur_amount": eur_amount, "price": current_price})
                break

            # CRITICAL: Extract ACTUAL invested EUR and tokens from DCA order response
            actual_dca_eur = eur_amount  # Fallback
            actual_dca_tokens = base_amount  # Fallback
            try:
                if isinstance(buy_result, dict):
                    if 'filledAmountQuote' in buy_result:
                        actual_dca_eur = float(buy_result['filledAmountQuote'])
                    if 'filledAmount' in buy_result:
                        actual_dca_tokens = float(buy_result['filledAmount'])
            except Exception as e:
                self._log(f"actual_dca_eur failed: {e}", level='error')

            import uuid
            import time as time_module
            event_id = str(uuid.uuid4())
            event_timestamp = time_module.time()
            
            prev_amount = float(trade.get("amount", 0.0))
            new_amount = prev_amount + float(actual_dca_tokens)
            if new_amount > 0:
                prev_buy = float(trade.get("buy_price", current_price))
                trade["buy_price"] = (
                    (prev_buy * prev_amount) + (float(current_price) * float(actual_dca_tokens))
                ) / new_amount
            trade["amount"] = new_amount
            # Use TradeInvestment module for all invested_eur mutations
            from core.trade_investment import add_dca as _ti_add_dca
            _ti_add_dca(trade, float(actual_dca_eur), source="dca_market_buy")
            new_dca_buys = int(trade.get("dca_buys", 0)) + 1
            # GUARD: Never exceed global max_buys — use settings.max_buys (from global
            # config) as authoritative limit; per-trade dca_max can be corrupted.
            dca_max_limit = int(settings.max_buys or 3)
            if new_dca_buys > dca_max_limit:
                log(f"⚠️ GUARD: dca_buys {new_dca_buys} would exceed dca_max {dca_max_limit} for {market}, capping")
                new_dca_buys = dca_max_limit
            trade["dca_buys"] = new_dca_buys
            trade["dca_max"] = dca_max_limit  # Keep per-trade max in sync
            trade["last_dca_price"] = float(current_price)
            # Add DCA event with unique ID and ACTUAL amounts
            trade.setdefault("dca_events", []).append({
                "event_id": event_id,
                "timestamp": event_timestamp,
                "price": float(current_price),
                "amount_eur": float(actual_dca_eur),
                "tokens_bought": float(actual_dca_tokens),
                "dca_level": new_dca_buys
            })
            # update next expected DCA price based on new averaged buy_price
            try:
                next_step = float(settings.drop_pct) * (float(settings.step_multiplier) ** new_dca_buys)
                trade["dca_next_price"] = float(trade.get("buy_price", current_price)) * (1 - next_step)
            except Exception as e:
                self.ctx.log(f"[ERROR] DCA next_price update failed for {market}: {e}")
            log(
                f"DCA buy {trade['dca_buys']} voor {market} op {current_price:.6f} (EUR {eur_amount:.2f})"
            )
            # Telegram notification for DCA buy
            try:
                if ctx.send_alert:
                    _inv = float(trade.get('invested_eur', 0))
                    _avg = float(trade.get('buy_price', current_price))
                    ctx.send_alert(
                        f"\U0001f4c9 DCA Buy {new_dca_buys}/{dca_max_limit} | {market}\n"
                        f"Prijs: \u20ac{current_price:.4f} | Bedrag: \u20ac{actual_dca_eur:.2f}\n"
                        f"Totaal invested: \u20ac{_inv:.2f} | Gem. prijs: \u20ac{_avg:.4f}"
                    )
            except Exception as _tg_err:
                log(f"[DCA] Telegram notify failed: {_tg_err}", level='warning')
            # Signal Publisher: publiceer DCA signaal
            try:
                from modules import signal_publisher as _sp
                _avg = float(trade.get('buy_price', current_price))
                _drop = ((current_price - _avg) / _avg * 100) if _avg > 0 else 0.0
                _sp.publish_dca(market, new_dca_buys, float(current_price), float(actual_dca_eur), _avg, _drop)
            except Exception:
                pass
            ctx.save_trades()
            buys_this_call += 1
            # reservation consumed by actual exposure; release reservation record
            try:
                if reservation_id is not None:
                    self._release_reservation(reservation_id)
            except Exception as e:
                self._log(f"_release_reservation failed: {e}", level='warning')

    # ------------------------------------------------------------------
    # Dynamic ladder implementation
    # ------------------------------------------------------------------
    def _execute_dynamic_dca(
        self,
        market: str,
        trade: Dict[str, Any],
        current_price: float,
        settings: DCASettings,
        size_bias: float,
    ) -> None:
        ctx = self.ctx
        log = ctx.log

        eur_balance = 0.0
        balances = ctx.safe_call(ctx.bitvavo.balance, {})
        for entry in balances or []:
            if not isinstance(entry, dict):
                continue  # skip malformed balance entries to avoid attribute errors
            if entry.get("symbol") == "EUR":
                eur_balance = float(entry.get("available", 0) or 0)
        dynamic_amount_eur = max(round(eur_balance * 0.02, 2), 5) * float(size_bias)
        dynamic_max_buys = settings.max_buys

        perf_metrics = self._compute_perf_metrics()
        win_rate = perf_metrics.get("win_rate")
        max_drawdown = perf_metrics.get("max_drawdown")
        if isinstance(win_rate, (int, float)) and win_rate > 0.6:
            new_max = min(settings.max_buys + 1, 5)
            if new_max != settings.max_buys:
                log(f"DCA_MAX_BUYS increased to {new_max} due to high win rate.")
            dynamic_max_buys = new_max
        else:
            dd_threshold = float(ctx.config.get("BASE_AMOUNT_EUR", 0) or 0)
            if isinstance(max_drawdown, (int, float)) and dd_threshold > 0 and max_drawdown > dd_threshold:
                new_max = max(settings.max_buys - 1, 1)
                if new_max != settings.max_buys:
                    log(f"DCA_MAX_BUYS decreased to {new_max} due to drawdown ({max_drawdown:.2f} EUR) .")
                dynamic_max_buys = new_max
                size_bias *= 0.85

        candles = ctx.get_candles(market, "1m", 30)
        prices = ctx.close_prices(candles)
        dca_drop_pct = settings.drop_pct
        if prices and len(prices) >= 10:
            mean_price = float(np.mean(prices[-10:])) if np.mean(prices[-10:]) > 0 else 0.0
            vol = float(np.std(prices[-10:]) / mean_price) if mean_price else 0.0
            if vol > 0.03:
                dca_drop_pct = min(settings.drop_pct + 0.03, 0.15)
                if not math.isclose(dca_drop_pct, settings.drop_pct):
                    log(f"DCA_DROP_PCT increased to {dca_drop_pct:.3f} due to high volatility.")
            elif vol < 0.01:
                dca_drop_pct = max(settings.drop_pct - 0.01, 0.01)
                if not math.isclose(dca_drop_pct, settings.drop_pct):
                    log(f"DCA_DROP_PCT decreased to {dca_drop_pct:.3f} due to low volatility.")

        buys_this_call = 0
        max_per_iter = int(settings.max_buys_per_iteration) if getattr(settings, 'max_buys_per_iteration', None) else dynamic_max_buys
        while trade.get("dca_buys", 0) < dynamic_max_buys and buys_this_call < max_per_iter:
            index = int(trade.get("dca_buys", 0))
            target_price = float(trade.get("buy_price", current_price)) * (1 - dca_drop_pct * (settings.step_multiplier ** index))
            trade["dca_next_price"] = target_price  # keep UI in sync with volatility/drawdown-adjusted ladder
            if current_price > target_price:
                self._record_dca_audit(market, trade, "skip", "price_above_target", {"price": current_price, "target": target_price, "step_index": index})
                break

            eur_amount = float(dynamic_amount_eur) * (settings.size_multiplier ** index)
            # Floor at DCA_MIN_AMOUNT_EUR so late levels keep buying instead of stopping
            dca_floor = float(ctx.config.get('DCA_MIN_AMOUNT_EUR', 5.0) or 5.0)
            if eur_amount < dca_floor:
                eur_amount = dca_floor
            eur_amount = self._cap_watchlist_amount(trade, eur_amount)
            # Try to reserve headroom across processes
            reservation_id = None
            reserved_amount = eur_amount
            try:
                max_total = float(ctx.config.get("MAX_TOTAL_EXPOSURE_EUR", 0) or 0)
                if max_total > 0:
                    reservation_id, reserved_amount = self._reserve_headroom(eur_amount, max_total, ctx)
                    if reservation_id is None or reserved_amount <= 0:
                        self._record_dca_audit(market, trade, "skip", "no_headroom", {"requested_eur": eur_amount, "max_total": max_total})
                        break
                    eur_amount = reserved_amount
            except Exception as e:
                self.ctx.log(f"[ERROR] DCA (dynamic) headroom reservation failed for {market}: {e}")
                reservation_id = None
                reserved_amount = eur_amount

            try:
                base_amount = eur_amount / float(current_price)
            except Exception:
                base_amount = 0.0

            min_size = ctx.get_min_order_size(market)
            # Allow a tiny epsilon for floating rounding when comparing with min_size
            if base_amount + 1e-12 < min_size:
                log(
                    f"DCA (dynamic) voor {market} overgeslagen (te klein): {base_amount:.8f} < min {min_size}"
                )
                # NOTE: Do NOT set dca_buys = max here — that corrupts the counter
                # when no actual DCA was executed. Just break and retry next iteration.
                self._record_dca_audit(market, trade, "skip", "under_min_size", {"base_amount": base_amount, "min_size": min_size})
                break

            buy_result = ctx.place_buy(market, eur_amount, current_price)
            if not ctx.is_order_success(buy_result):
                log(f"DCA (dynamic) buy voor {market} mislukt.")
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level='warning')
                self._record_dca_audit(market, trade, "fail", "order_failed", {"eur_amount": eur_amount, "price": current_price})
                break

            # CRITICAL: Extract ACTUAL invested EUR and tokens from DCA order response
            actual_dca_eur = eur_amount  # Fallback
            actual_dca_tokens = base_amount  # Fallback
            try:
                if isinstance(buy_result, dict):
                    if 'filledAmountQuote' in buy_result:
                        actual_dca_eur = float(buy_result['filledAmountQuote'])
                    if 'filledAmount' in buy_result:
                        actual_dca_tokens = float(buy_result['filledAmount'])
            except Exception as e:
                self._log(f"actual_dca_eur failed: {e}", level='error')

            import uuid
            import time as time_module
            event_id = str(uuid.uuid4())
            event_timestamp = time_module.time()
            
            prev_amount = float(trade.get("amount", 0.0))
            new_amount = prev_amount + float(actual_dca_tokens)
            if new_amount > 0:
                prev_buy = float(trade.get("buy_price", current_price))
                trade["buy_price"] = (
                    (prev_buy * prev_amount) + (float(current_price) * float(actual_dca_tokens))
                ) / new_amount
            trade["amount"] = new_amount
            # Use TradeInvestment module for all invested_eur mutations
            from core.trade_investment import add_dca as _ti_add_dca
            _ti_add_dca(trade, float(actual_dca_eur), source="dca_dynamic_buy")
            new_dca_buys = int(trade.get("dca_buys", 0)) + 1
            # GUARD: Never exceed global max_buys — use settings.max_buys (from global
            # config) as authoritative limit; per-trade dca_max can be corrupted.
            dca_max_limit = int(settings.max_buys or 3)
            if new_dca_buys > dca_max_limit:
                log(f"⚠️ GUARD: dca_buys {new_dca_buys} would exceed dca_max {dca_max_limit} for {market}, capping")
                new_dca_buys = dca_max_limit
            trade["dca_buys"] = new_dca_buys
            trade["dca_max"] = dca_max_limit  # Keep per-trade max in sync
            trade["last_dca_price"] = float(current_price)
            # Add DCA event with unique ID and ACTUAL amounts
            trade.setdefault("dca_events", []).append({
                "event_id": event_id,
                "timestamp": event_timestamp,
                "price": float(current_price),
                "amount_eur": float(actual_dca_eur),
                "tokens_bought": float(actual_dca_tokens),
                "dca_level": new_dca_buys
            })
            # update next expected DCA price based on new averaged buy_price
            try:
                next_step = float(dca_drop_pct) * (float(settings.step_multiplier) ** new_dca_buys)
                trade["dca_next_price"] = float(trade.get("buy_price", current_price)) * (1 - next_step)
            except Exception as e:
                self.ctx.log(f"[ERROR] DCA (dynamic) next_price update failed for {market}: {e}")
            log(
                f"DCA (dynamic) buy {trade['dca_buys']} voor {market} op {current_price:.6f} (EUR {eur_amount:.2f})"
            )
            # Telegram notification for dynamic DCA buy
            try:
                if ctx.send_alert:
                    _inv = float(trade.get('invested_eur', 0))
                    _avg = float(trade.get('buy_price', current_price))
                    ctx.send_alert(
                        f"\U0001f4c9 DCA Buy {new_dca_buys}/{dca_max_limit} | {market}\n"
                        f"Prijs: \u20ac{current_price:.4f} | Bedrag: \u20ac{actual_dca_eur:.2f}\n"
                        f"Totaal invested: \u20ac{_inv:.2f} | Gem. prijs: \u20ac{_avg:.4f}"
                    )
            except Exception as _tg_err:
                log(f"[DCA] Telegram notify failed: {_tg_err}", level='warning')
            ctx.save_trades()
            buys_this_call += 1
            try:
                if reservation_id is not None:
                    self._release_reservation(reservation_id)
            except Exception as e:
                self._log(f"_release_reservation failed: {e}", level='warning')

    # ------------------------------------------------------------------
    # Cross-process reservation helpers
    # ------------------------------------------------------------------
    def _reservations_path(self) -> str:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'data'))
        try:
            os.makedirs(base, exist_ok=True)
        except Exception as e:
            self._log(f"makedirs failed: {e}", level='debug')
        suffix = 'default'
        try:
            trade_log_path = getattr(self.ctx, 'trade_log_path', None)
            if trade_log_path:
                candidate = os.path.splitext(os.path.basename(str(trade_log_path)))[0]
                if candidate:
                    suffix = candidate
        except Exception:
            suffix = 'default'
        filename = 'dca_reservations.json' if suffix == 'default' else f'dca_reservations_{suffix}.json'
        return os.path.join(base, filename)

    def _load_reservations(self):
        path = self._reservations_path()
        try:
            with file_lock:
                if os.path.exists(path):
                    with open(path, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            return data
        except Exception as e:
            self._log(f"exists failed: {e}", level='warning')
        return []

    def _save_reservations(self, reservations):
        path = self._reservations_path()
        try:
            with file_lock:
                locked_write_json(path, reservations, indent=2)
        except Exception as e:
            self._log(f"locked_write_json failed: {e}", level='warning')

    def _reserve_headroom(self, amount_eur: float, max_total: float, ctx) -> Tuple[Optional[str], float]:
        """Attempt to reserve EUR headroom across processes.

        Returns a tuple of (reservation_id, reserved_amount). When insufficient headroom is
        available the function returns (None, 0.0).
        """
        try:
            with file_lock:
                reservations = self._load_reservations()
                # cleanup expired (older than 300s)
                now = time.time()
                valid = [r for r in reservations if now - r.get('ts', 0) < 300]
                reserved_sum = sum(float(r.get('amount', 0) or 0) for r in valid)
                current_exp = float(ctx.current_open_exposure_eur() or 0.0)
                headroom = max_total - (current_exp + reserved_sum)
                if headroom <= 0:
                    return None, 0.0
                reserved_amount = float(min(amount_eur, headroom))
                rid = f"{os.getpid()}_{int(now*1000)}_{uuid.uuid4().hex[:6]}"
                entry = {'id': rid, 'ts': now, 'pid': os.getpid(), 'amount': reserved_amount}
                valid.append(entry)
                self._save_reservations(valid)
                return rid, reserved_amount
        except Exception:
            return None, 0.0

    def _release_reservation(self, rid: str) -> None:
        try:
            with file_lock:
                reservations = self._load_reservations()
                filtered = [r for r in reservations if r.get('id') != rid]
                self._save_reservations(filtered)
        except Exception as e:
            self._log(f"_load_reservations failed: {e}", level='warning')
