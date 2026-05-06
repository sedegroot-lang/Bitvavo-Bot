"""Dollar-cost averaging helper module."""

from __future__ import annotations

import json
import math
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from modules.logging_utils import file_lock, locked_write_json

# ─── FIX #073: DCA limit order tracking helpers ────────────────────
# Bitvavo MAKER limit orders return status='new' with filledAmountQuote='0'
# while resting on the orderbook. Until the order fills, we must NOT mutate
# trade state (dca_buys, invested_eur) and NOT send "DCA Buy" Telegram.
_OPEN_LIKE_STATUSES = {"new", "open", "partiallyfilled", "partially filled"}
_DEAD_STATUSES = {"cancelled", "canceled", "rejected", "expired"}


def _order_filled_status(buy_result: Any) -> Tuple[bool, float, float, str, str]:
    """Inspect a place_buy() response.

    Returns: (filled, filled_eur, filled_tokens, status, order_id)
        filled       — True if status='filled' OR filledAmount > 0
        filled_eur   — actual quote filled (0 for resting limit)
        filled_tokens — actual base filled (0 for resting limit)
        status       — lowercased status string
        order_id     — orderId from response (empty string if missing)
    """
    if not isinstance(buy_result, dict):
        return False, 0.0, 0.0, "", ""
    status = str(buy_result.get("status", "")).lower().strip()
    order_id = str(buy_result.get("orderId", "") or "")
    try:
        filled_eur = float(buy_result.get("filledAmountQuote", 0) or 0)
    except (TypeError, ValueError):
        filled_eur = 0.0
    try:
        filled_tokens = float(buy_result.get("filledAmount", 0) or 0)
    except (TypeError, ValueError):
        filled_tokens = 0.0
    is_filled = (status == "filled") or (filled_tokens > 0 and filled_eur > 0)
    return is_filled, filled_eur, filled_tokens, status, order_id


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
        self._audit_path = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "dca_audit.log"))
        self._smart_dca_wait_since: Dict[str, float] = {}  # market -> first-block timestamp

    def _log(self, msg: str, level: str = "info") -> None:
        """Wrapper for ctx.log — prevents AttributeError in exception handlers."""
        try:
            self.ctx.log(msg, level=level)
        except Exception:
            pass

    def _compute_perf_metrics(self) -> Dict[str, Optional[float]]:
        """Derive simple performance stats (win rate, max drawdown) from trade_log for sizing guards."""
        out: Dict[str, Optional[float]] = {"win_rate": None, "max_drawdown": None}
        trade_log_path = getattr(self.ctx, "trade_log_path", None)
        if not trade_log_path or not os.path.exists(trade_log_path):
            return out
        try:
            with open(trade_log_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            closed = data.get("closed", []) if isinstance(data, dict) else []
            pnl_list = [float(t.get("profit", 0) or 0) for t in closed if isinstance(t, dict)]
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

    def _record_dca_audit(
        self, market: str, trade: Dict[str, Any], status: str, reason: str, extra: Optional[Dict[str, Any]] = None
    ) -> None:
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
                self._log(f"update failed: {e}", level="debug")
        try:
            os.makedirs(os.path.dirname(self._audit_path), exist_ok=True)
            with open(self._audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except Exception as e:
            self._log(f"makedirs failed: {e}", level="warning")

    def _cap_watchlist_amount(self, trade: Dict[str, Any], eur_amount: float) -> float:
        try:
            cfg = self.ctx.config
        except Exception:
            return eur_amount
        settings = cfg.get("WATCHLIST_SETTINGS") or {}
        if not (trade.get("watchlist_candidate") and settings.get("enabled", True)):
            return eur_amount
        try:
            cap = float(settings.get("micro_trade_amount_eur", eur_amount))
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

        # DCA_MIN_SCORE gate (Road-to-10 #061): skip DCA on positions opened with weak score.
        # Default 0.0 = disabled (legacy behaviour). Roadmap recommends >= 12.0 for stricter DCA.
        try:
            _dca_min_score = float(self.ctx.config.get("DCA_MIN_SCORE", 0.0) or 0.0)
        except Exception:
            _dca_min_score = 0.0
        if _dca_min_score > 0:
            try:
                _trade_score = float(trade.get("score", 0.0) or 0.0)
            except Exception:
                _trade_score = 0.0
            if _trade_score < _dca_min_score:
                self.ctx.log(
                    f"DCA voor {market} overgeslagen: trade-score {_trade_score:.2f} < DCA_MIN_SCORE {_dca_min_score:.2f}"
                )
                self._record_dca_audit(
                    market,
                    trade,
                    "skip",
                    "score_below_min",
                    {"trade_score": _trade_score, "min_score": _dca_min_score},
                )
                return

        # DCA cooldown after sync: skip DCA for 5 minutes after a position is synced
        # to prevent cascading DCAs from potentially inaccurate buy_price
        import time as _time_mod

        synced_at = trade.get("synced_at")
        if synced_at:
            cooldown_sec = float(self.ctx.config.get("DCA_SYNC_COOLDOWN_SEC", 300))
            elapsed = _time_mod.time() - float(synced_at)
            if elapsed < cooldown_sec:
                self.ctx.log(f"DCA voor {market} overgeslagen: sync cooldown ({cooldown_sec - elapsed:.0f}s remaining)")
                self._record_dca_audit(
                    market, trade, "skip", "sync_cooldown", {"elapsed": elapsed, "cooldown": cooldown_sec}
                )
                return

        # FIX #087: per-trade DCA action cooldown to break placement/cancel/fail spam loops.
        # After ANY DCA-side action (limit placed, order failed, fill applied, pending cleared),
        # require a minimum quiet period before evaluating placement again.
        # Default 300s (5 min). Set DCA_ACTION_COOLDOWN_SECONDS=0 to disable.
        try:
            _action_cooldown = float(self.ctx.config.get("DCA_ACTION_COOLDOWN_SECONDS", 300) or 0)
        except Exception:
            _action_cooldown = 300.0
        if _action_cooldown > 0:
            try:
                _last_action_ts = float(trade.get("last_dca_action_ts", 0) or 0)
            except Exception:
                _last_action_ts = 0.0
            if _last_action_ts > 0:
                _age = _time_mod.time() - _last_action_ts
                if _age < _action_cooldown:
                    self._record_dca_audit(
                        market,
                        trade,
                        "skip",
                        "action_cooldown",
                        {"age_s": round(_age, 1), "cooldown_s": _action_cooldown},
                    )
                    return

        ctx = self.ctx
        cfg = ctx.config
        log = ctx.log
        cp = float(current_price)

        watch_cfg = cfg.get("WATCHLIST_SETTINGS") or {}
        if trade.get("watchlist_candidate") and watch_cfg.get("enabled", True):
            if watch_cfg.get("disable_dca", True):
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
            trade.setdefault("dca_next_price", float(trade.get("buy_price", cp)) * (1 - settings.drop_pct))
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
            self._record_dca_audit(
                market, trade, "skip", "rsi_block", {"rsi": rsi_val, "rsi_threshold": rsi_dca_threshold}
            )
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
                    ctx.log(
                        f"Smart DCA {market}: deep drop override ({_drop_actual * 100:.1f}% >> {settings.drop_pct * 100:.1f}%), executing DCA"
                    )
                elif _timed_out:
                    self._smart_dca_wait_since.pop(market, None)
                    ctx.log(
                        f"Smart DCA {market}: timeout after {(_time.time() - _wait_start) / 60:.0f}min, executing DCA"
                    )
                else:
                    _smart_ok, _smart_reason = should_smart_dca(
                        prices,
                        cp,
                        _buy_px,
                        dca_drop_pct=settings.drop_pct,
                        bb_window=int(cfg.get("SMART_DCA_BB_WINDOW", 20)),
                        bandwidth_threshold=float(cfg.get("SMART_DCA_BW_THRESHOLD", 0.04)),
                    )
                    if not _smart_ok and _smart_reason == "waiting_for_squeeze":
                        if market not in self._smart_dca_wait_since:
                            self._smart_dca_wait_since[market] = _time.time()
                        _waited = (_time.time() - self._smart_dca_wait_since[market]) / 60
                        ctx.log(
                            f"Smart DCA {market}: waiting for BB squeeze ({_waited:.0f}min, timeout {_timeout_sec / 60:.0f}min)"
                        )
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
                ctx.log(f"DCA HYBRID {market}: in profit ({((cp / buy_price) - 1) * 100:.1f}%), using pyramid-up mode")
                self._execute_pyramid_up(market, trade, cp, settings, size_bias)
            elif not in_profit:
                # Position is in loss → average down
                ctx.log(f"DCA HYBRID {market}: in loss ({((cp / buy_price) - 1) * 100:.1f}%), using average-down mode")
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
            self._record_dca_audit(
                market, trade, "skip", "pyramid_max_reached", {"pyramid_buys": pyramid_buys, "max": max_adds}
            )
            return

        if profit_pct < min_profit_pct:
            self._record_dca_audit(
                market, trade, "skip", "not_in_profit", {"profit_pct": round(profit_pct, 4), "min": min_profit_pct}
            )
            return

        # Position size decreases with each pyramid level
        eur_amount = float(settings.amount_eur) * float(size_bias) * (scale_down**pyramid_buys)

        # Headroom check
        max_total = float(cfg.get("MAX_TOTAL_EXPOSURE_EUR", 0) or 0)
        if max_total > 0:
            try:
                current_exposure = ctx.current_open_exposure_eur()
                if current_exposure + eur_amount > max_total:
                    log(
                        f"Pyramid DCA blocked for {market}: exposure €{current_exposure:.2f} + €{eur_amount:.2f} > max €{max_total:.2f}"
                    )
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

        buy_result = ctx.place_buy(market, eur_amount, current_price, is_dca=True)
        if not ctx.is_order_success(buy_result):
            log(f"Pyramid DCA buy for {market} failed")
            self._record_dca_audit(market, trade, "fail", "pyramid_order_failed")
            return

        # Update trade state
        old_amount = float(trade.get("amount", 0) or 0)
        new_amount = old_amount + base_amount
        old_invested = float(trade.get("invested_eur", 0) or 0)
        if old_invested <= 0:
            log(f"Pyramid DCA for {market} skipped: invested_eur is 0 (derive_cost_basis needed)")
            self._record_dca_audit(market, trade, "skip", "pyramid_no_invested_eur")
            return
        new_invested = old_invested + eur_amount
        new_avg_price = new_invested / new_amount if new_amount > 0 else buy_price

        trade["buy_price"] = round(new_avg_price, 8)
        trade["amount"] = round(new_amount, 8)
        # Use TradeInvestment module for invested_eur consistency
        from core.trade_investment import add_dca as _ti_add_dca

        _ti_add_dca(trade, float(eur_amount), source="pyramid_up")
        # FIX #007: Use dca_state.record_dca() as SINGLE source of truth
        from core.dca_state import record_dca as _ds_record

        _ds_record(
            trade,
            price=float(current_price),
            amount_eur=float(eur_amount),
            tokens_bought=float(base_amount),
            dca_max=max_adds,
            source="pyramid",
        )

        log(
            f"✅ Pyramid DCA #{pyramid_buys + 1} for {market}: "
            f"+€{eur_amount:.2f} at {current_price:.4f} "
            f"(profit {profit_pct * 100:.1f}%, new avg {new_avg_price:.4f})"
        )
        self._record_dca_audit(
            market,
            trade,
            "executed",
            "pyramid_up",
            {
                "profit_pct": round(profit_pct, 4),
                "eur_amount": round(eur_amount, 2),
                "new_avg": round(new_avg_price, 8),
            },
        )
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

        # FIX #073: handle pending DCA limit-order from previous iteration first.
        _pending_status = self._check_pending_dca_order(market, trade, settings)
        if _pending_status in ("still_open", "timed_out_cancelled", "error"):
            return  # do NOT place a new order while one is in flight or just cancelled

        buys_this_call = 0
        max_per_iter = (
            int(settings.max_buys_per_iteration)
            if getattr(settings, "max_buys_per_iteration", None)
            else settings.max_buys
        )
        while trade.get("dca_buys", 0) < settings.max_buys and buys_this_call < max_per_iter:
            index = int(trade.get("dca_buys", 0))
            step_pct = float(settings.drop_pct) * (float(settings.step_multiplier) ** index)
            # FIX #003: Use last_dca_price as reference to prevent cascading DCAs.
            # Before: buy_price (weighted avg) drops with each DCA, letting the next
            # DCA trigger at the same market price.  Now each DCA requires an
            # additional drop_pct from where the previous DCA actually executed.
            ref_price = float(trade.get("last_dca_price", trade.get("buy_price", current_price)))
            target_price = ref_price * (1 - step_pct)
            trade["dca_next_price"] = target_price  # keep persisted target in sync with live calculation
            if current_price > target_price:
                self._record_dca_audit(
                    market,
                    trade,
                    "skip",
                    "price_above_target",
                    {"price": current_price, "target": target_price, "step_index": index},
                )
                break

            # Use per-trade dynamic DCA amount if available, else global setting
            _per_trade_dca = float(trade.get("dca_amount_eur", 0) or 0)
            _base_dca = _per_trade_dca if _per_trade_dca >= 5.0 else float(settings.amount_eur)
            eur_amount = _base_dca * float(size_bias) * (float(settings.size_multiplier) ** index)
            eur_amount *= dd_penalty
            # Floor at DCA_MIN_AMOUNT_EUR so late levels keep buying instead of stopping
            dca_floor = float(cfg.get("DCA_MIN_AMOUNT_EUR", 5.0) or 5.0)
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
                        self._record_dca_audit(
                            market, trade, "skip", "no_headroom", {"requested_eur": eur_amount, "max_total": max_total}
                        )
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
                log(f"DCA voor {market} overgeslagen (te klein): {base_amount:.8f} < min {min_size}")
                # NOTE: Do NOT set dca_buys = max_buys here — that corrupts the counter
                # when no actual DCA was executed. Just break and retry next iteration.
                self._record_dca_audit(
                    market, trade, "skip", "under_min_size", {"base_amount": base_amount, "min_size": min_size}
                )
                break

            buy_result = ctx.place_buy(market, eur_amount, current_price, is_dca=True)
            if not ctx.is_order_success(buy_result):
                log(f"DCA buy voor {market} mislukt.")
                # release reservation if purchase failed
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level="warning")
                # FIX #087: stamp action timestamp so cooldown gate kicks in next loop
                trade["last_dca_action_ts"] = float(time.time())
                self._record_dca_audit(
                    market, trade, "fail", "order_failed", {"eur_amount": eur_amount, "price": current_price}
                )
                break

            # FIX #073: detect MAKER limit order (status='new', filledAmountQuote=0).
            # If not filled yet, stash orderId on trade so next iter can poll/cancel.
            # Do NOT mutate dca_buys / invested_eur and do NOT send "DCA Buy" Telegram.
            _filled, _fa_eur, _fa_tokens, _ord_status, _ord_id = _order_filled_status(buy_result)
            if not _filled:
                try:
                    _limit_px = (
                        float(buy_result.get("price", current_price))
                        if isinstance(buy_result, dict)
                        else float(current_price)
                    )
                except Exception:
                    _limit_px = float(current_price)
                if _ord_id:
                    self._stash_pending_dca(trade, market, _ord_id, eur_amount, _limit_px)
                    self._send_dca_placed_alert(
                        market,
                        eur_amount,
                        _limit_px,
                        int(trade.get("dca_buys", 0)) + 1,
                        int(settings.max_buys or 3),
                    )
                    self._record_dca_audit(
                        market,
                        trade,
                        "placed",
                        "limit_order_resting",
                        {
                            "order_id": _ord_id,
                            "commit_eur": eur_amount,
                            "limit_price": _limit_px,
                            "status": _ord_status,
                        },
                    )
                    ctx.save_trades()
                else:
                    self._record_dca_audit(
                        market,
                        trade,
                        "fail",
                        "placed_no_orderId_no_fill",
                        {"eur_amount": eur_amount, "status": _ord_status},
                    )
                # Release reservation: no actual exposure was added yet
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level="warning")
                break  # do not attempt next ladder level until this resolves

            # Order filled — proceed with ACTUAL fill amounts
            actual_dca_eur = _fa_eur
            actual_dca_tokens = _fa_tokens

            prev_amount = float(trade.get("amount", 0.0))
            new_amount = prev_amount + float(actual_dca_tokens)
            # Snapshot before mutation for rollback on failure
            _snap = {
                "invested_eur": float(trade.get("invested_eur", 0) or 0),
                "dca_buys": int(trade.get("dca_buys", 0)),
                "dca_events": list(trade.get("dca_events", [])),
                "buy_price": float(trade.get("buy_price", 0) or 0),
                "amount": prev_amount,
            }
            if new_amount > 0:
                prev_buy = float(trade.get("buy_price", current_price))
                trade["buy_price"] = (
                    (prev_buy * prev_amount) + (float(current_price) * float(actual_dca_tokens))
                ) / new_amount
            trade["amount"] = new_amount
            # Use TradeInvestment module for all invested_eur mutations
            try:
                from core.trade_investment import add_dca as _ti_add_dca

                _ti_add_dca(trade, float(actual_dca_eur), source="dca_market_buy")
                # FIX #007: Use dca_state.record_dca() as SINGLE source of truth
                # for dca_buys, dca_events, last_dca_price, and dca_next_price.
                from core.dca_state import record_dca as _ds_record

                dca_max_limit = int(settings.max_buys or 3)
                _dca_state = _ds_record(
                    trade,
                    price=float(current_price),
                    amount_eur=float(actual_dca_eur),
                    tokens_bought=float(actual_dca_tokens),
                    dca_max=dca_max_limit,
                    source="bot",
                    drop_pct=float(settings.drop_pct),
                    step_multiplier=float(settings.step_multiplier),
                )
                new_dca_buys = _dca_state.dca_buys
            except Exception as _dca_err:
                # Rollback trade to pre-mutation snapshot
                for _k, _v in _snap.items():
                    trade[_k] = _v
                self._log(f"DCA state mutation failed for {market}, rolled back: {_dca_err}", level="error")
                break
            log(f"DCA buy {trade['dca_buys']} voor {market} op {current_price:.6f} (EUR {eur_amount:.2f})")
            # Telegram notification for DCA buy (FILLED — see FIX #073)
            try:
                if ctx.send_alert:
                    _inv = float(trade.get("invested_eur", 0))
                    _avg = float(trade.get("buy_price", current_price))
                    ctx.send_alert(
                        f"\u2705 DCA Buy {new_dca_buys}/{dca_max_limit} GEVULD | {market}\n"
                        f"Prijs: \u20ac{current_price:.4f} | Bedrag: \u20ac{actual_dca_eur:.2f}\n"
                        f"Totaal invested: \u20ac{_inv:.2f} | Gem. prijs: \u20ac{_avg:.4f}"
                    )
            except Exception as _tg_err:
                log(f"[DCA] Telegram notify failed: {_tg_err}", level="warning")
            # Signal Publisher: publiceer DCA signaal
            try:
                from modules import signal_publisher as _sp

                _avg = float(trade.get("buy_price", current_price))
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
                self._log(f"_release_reservation failed: {e}", level="warning")

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

        # FIX #073: handle pending DCA limit-order from previous iteration first.
        _pending_status = self._check_pending_dca_order(market, trade, settings)
        if _pending_status in ("still_open", "timed_out_cancelled", "error"):
            return  # do NOT place a new order while one is in flight or just cancelled

        buys_this_call = 0
        max_per_iter = (
            int(settings.max_buys_per_iteration)
            if getattr(settings, "max_buys_per_iteration", None)
            else dynamic_max_buys
        )
        while trade.get("dca_buys", 0) < dynamic_max_buys and buys_this_call < max_per_iter:
            index = int(trade.get("dca_buys", 0))
            # FIX #003: Use last_dca_price as reference to prevent cascading DCAs
            ref_price = float(trade.get("last_dca_price", trade.get("buy_price", current_price)))
            target_price = ref_price * (1 - dca_drop_pct * (settings.step_multiplier**index))
            trade["dca_next_price"] = target_price  # keep UI in sync with volatility/drawdown-adjusted ladder
            if current_price > target_price:
                self._record_dca_audit(
                    market,
                    trade,
                    "skip",
                    "price_above_target",
                    {"price": current_price, "target": target_price, "step_index": index},
                )
                break

            eur_amount = float(dynamic_amount_eur) * (settings.size_multiplier**index)
            # Floor at DCA_MIN_AMOUNT_EUR so late levels keep buying instead of stopping
            dca_floor = float(ctx.config.get("DCA_MIN_AMOUNT_EUR", 5.0) or 5.0)
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
                        self._record_dca_audit(
                            market, trade, "skip", "no_headroom", {"requested_eur": eur_amount, "max_total": max_total}
                        )
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
                log(f"DCA (dynamic) voor {market} overgeslagen (te klein): {base_amount:.8f} < min {min_size}")
                # NOTE: Do NOT set dca_buys = max here — that corrupts the counter
                # when no actual DCA was executed. Just break and retry next iteration.
                self._record_dca_audit(
                    market, trade, "skip", "under_min_size", {"base_amount": base_amount, "min_size": min_size}
                )
                break

            buy_result = ctx.place_buy(market, eur_amount, current_price, is_dca=True)
            if not ctx.is_order_success(buy_result):
                log(f"DCA (dynamic) buy voor {market} mislukt.")
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level="warning")
                # FIX #087: stamp action timestamp so cooldown gate kicks in next loop
                trade["last_dca_action_ts"] = float(time.time())
                self._record_dca_audit(
                    market, trade, "fail", "order_failed", {"eur_amount": eur_amount, "price": current_price}
                )
                break

            # FIX #073: stash MAKER limit orders that haven't filled yet.
            _filled, _fa_eur, _fa_tokens, _ord_status, _ord_id = _order_filled_status(buy_result)
            if not _filled:
                try:
                    _limit_px = (
                        float(buy_result.get("price", current_price))
                        if isinstance(buy_result, dict)
                        else float(current_price)
                    )
                except Exception:
                    _limit_px = float(current_price)
                if _ord_id:
                    self._stash_pending_dca(trade, market, _ord_id, eur_amount, _limit_px)
                    self._send_dca_placed_alert(
                        market,
                        eur_amount,
                        _limit_px,
                        int(trade.get("dca_buys", 0)) + 1,
                        int(settings.max_buys or 3),
                    )
                    self._record_dca_audit(
                        market,
                        trade,
                        "placed",
                        "limit_order_resting",
                        {
                            "order_id": _ord_id,
                            "commit_eur": eur_amount,
                            "limit_price": _limit_px,
                            "status": _ord_status,
                            "path": "dynamic",
                        },
                    )
                    ctx.save_trades()
                else:
                    self._record_dca_audit(
                        market,
                        trade,
                        "fail",
                        "placed_no_orderId_no_fill",
                        {"eur_amount": eur_amount, "status": _ord_status, "path": "dynamic"},
                    )
                try:
                    if reservation_id is not None:
                        self._release_reservation(reservation_id)
                except Exception as e:
                    self._log(f"_release_reservation failed: {e}", level="warning")
                break

            # Order filled — proceed with ACTUAL fill amounts
            actual_dca_eur = _fa_eur
            actual_dca_tokens = _fa_tokens

            prev_amount = float(trade.get("amount", 0.0))
            new_amount = prev_amount + float(actual_dca_tokens)
            # Snapshot before mutation for rollback on failure
            _snap = {
                "invested_eur": float(trade.get("invested_eur", 0) or 0),
                "dca_buys": int(trade.get("dca_buys", 0)),
                "dca_events": list(trade.get("dca_events", [])),
                "buy_price": float(trade.get("buy_price", 0) or 0),
                "amount": prev_amount,
            }
            if new_amount > 0:
                prev_buy = float(trade.get("buy_price", current_price))
                trade["buy_price"] = (
                    (prev_buy * prev_amount) + (float(current_price) * float(actual_dca_tokens))
                ) / new_amount
            trade["amount"] = new_amount
            # Use TradeInvestment module for all invested_eur mutations
            try:
                from core.trade_investment import add_dca as _ti_add_dca

                _ti_add_dca(trade, float(actual_dca_eur), source="dca_dynamic_buy")
                # FIX #007: Use dca_state.record_dca() as SINGLE source of truth
                # for dca_buys, dca_events, last_dca_price, and dca_next_price.
                from core.dca_state import record_dca as _ds_record

                dca_max_limit = int(settings.max_buys or 3)
                _dca_state = _ds_record(
                    trade,
                    price=float(current_price),
                    amount_eur=float(actual_dca_eur),
                    tokens_bought=float(actual_dca_tokens),
                    dca_max=dca_max_limit,
                    source="bot",
                    drop_pct=float(dca_drop_pct),
                    step_multiplier=float(settings.step_multiplier),
                )
                new_dca_buys = _dca_state.dca_buys
            except Exception as _dca_err:
                # Rollback trade to pre-mutation snapshot
                for _k, _v in _snap.items():
                    trade[_k] = _v
                self._log(f"DCA (dynamic) state mutation failed for {market}, rolled back: {_dca_err}", level="error")
                break
            log(f"DCA (dynamic) buy {trade['dca_buys']} voor {market} op {current_price:.6f} (EUR {eur_amount:.2f})")
            # Telegram notification for dynamic DCA buy (FILLED — see FIX #073)
            try:
                if ctx.send_alert:
                    _inv = float(trade.get("invested_eur", 0))
                    _avg = float(trade.get("buy_price", current_price))
                    ctx.send_alert(
                        f"\u2705 DCA Buy {new_dca_buys}/{dca_max_limit} GEVULD | {market}\n"
                        f"Prijs: \u20ac{current_price:.4f} | Bedrag: \u20ac{actual_dca_eur:.2f}\n"
                        f"Totaal invested: \u20ac{_inv:.2f} | Gem. prijs: \u20ac{_avg:.4f}"
                    )
            except Exception as _tg_err:
                log(f"[DCA] Telegram notify failed: {_tg_err}", level="warning")
            ctx.save_trades()
            buys_this_call += 1
            try:
                if reservation_id is not None:
                    self._release_reservation(reservation_id)
            except Exception as e:
                self._log(f"_release_reservation failed: {e}", level="warning")

    # ------------------------------------------------------------------
    # Cross-process reservation helpers
    # ------------------------------------------------------------------
    def _reservations_path(self) -> str:
        base = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data"))
        try:
            os.makedirs(base, exist_ok=True)
        except Exception as e:
            self._log(f"makedirs failed: {e}", level="debug")
        suffix = "default"
        try:
            trade_log_path = getattr(self.ctx, "trade_log_path", None)
            if trade_log_path:
                candidate = os.path.splitext(os.path.basename(str(trade_log_path)))[0]
                if candidate:
                    suffix = candidate
        except Exception:
            suffix = "default"
        filename = "dca_reservations.json" if suffix == "default" else f"dca_reservations_{suffix}.json"
        return os.path.join(base, filename)

    def _load_reservations(self):
        path = self._reservations_path()
        try:
            with file_lock:
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                        if isinstance(data, list):
                            return data
        except Exception as e:
            self._log(f"exists failed: {e}", level="warning")
        return []

    def _save_reservations(self, reservations):
        path = self._reservations_path()
        try:
            with file_lock:
                locked_write_json(path, reservations, indent=2)
        except Exception as e:
            self._log(f"locked_write_json failed: {e}", level="warning")

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
                valid = [r for r in reservations if now - r.get("ts", 0) < 300]
                reserved_sum = sum(float(r.get("amount", 0) or 0) for r in valid)
                current_exp = float(ctx.current_open_exposure_eur() or 0.0)
                headroom = max_total - (current_exp + reserved_sum)
                if headroom <= 0:
                    return None, 0.0
                reserved_amount = float(min(amount_eur, headroom))
                rid = f"{os.getpid()}_{int(now * 1000)}_{uuid.uuid4().hex[:6]}"
                entry = {"id": rid, "ts": now, "pid": os.getpid(), "amount": reserved_amount}
                valid.append(entry)
                self._save_reservations(valid)
                return rid, reserved_amount
        except Exception:
            return None, 0.0

    def _release_reservation(self, rid: str) -> None:
        try:
            with file_lock:
                reservations = self._load_reservations()
                filtered = [r for r in reservations if r.get("id") != rid]
                self._save_reservations(filtered)
        except Exception as e:
            self._log(f"_load_reservations failed: {e}", level="warning")

    # ──────────────────────────────────────────────────────────────
    # FIX #073: pending DCA limit-order tracking
    # ──────────────────────────────────────────────────────────────
    def _clear_pending_dca(self, trade: Dict[str, Any]) -> None:
        for k in (
            "pending_dca_order_id",
            "pending_dca_order_ts",
            "pending_dca_order_eur",
            "pending_dca_order_price",
            "pending_dca_order_market",
        ):
            trade.pop(k, None)
        # FIX #087: stamp action timestamp so cooldown gate kicks in next loop
        trade["last_dca_action_ts"] = float(time.time())

    def _stash_pending_dca(
        self,
        trade: Dict[str, Any],
        market: str,
        order_id: str,
        commit_eur: float,
        limit_price: float,
    ) -> None:
        trade["pending_dca_order_id"] = str(order_id)
        trade["pending_dca_order_ts"] = float(time.time())
        trade["pending_dca_order_eur"] = float(commit_eur)
        trade["pending_dca_order_price"] = float(limit_price)
        trade["pending_dca_order_market"] = market
        # FIX #087: stamp action timestamp so we don't immediately retry placement
        trade["last_dca_action_ts"] = float(time.time())

    def _cancel_order_safe(self, market: str, order_id: str) -> bool:
        """Cancel via Bitvavo, retrying with operatorId fallback (errorCode 203)."""
        ctx = self.ctx
        op_id = self.ctx.config.get("BITVAVO_OPERATOR_ID") or "1"
        try:
            try:
                ctx.bitvavo.cancelOrder(market, order_id, operatorId=str(op_id))
                return True
            except TypeError:
                # python_bitvavo_api may accept operatorId as positional/dict
                pass
            try:
                ctx.bitvavo.cancelOrder(market, order_id, {"operatorId": str(op_id)})
                return True
            except Exception:
                pass
            try:
                ctx.bitvavo.cancelOrder(market, order_id)
                return True
            except Exception as e:
                self._log(f"cancelOrder {market} {order_id} failed: {e}", level="warning")
                return False
        except Exception as e:
            self._log(f"cancelOrder outer failure {market} {order_id}: {e}", level="warning")
            return False

    def _record_filled_dca(
        self,
        market: str,
        trade: Dict[str, Any],
        actual_eur: float,
        actual_tokens: float,
        fill_price: float,
        settings: DCASettings,
    ) -> int:
        """Apply a confirmed DCA fill to the trade. Returns new dca_buys count."""
        from core.dca_state import record_dca as _ds_record
        from core.trade_investment import add_dca as _ti_add_dca

        prev_amount = float(trade.get("amount", 0.0) or 0.0)
        new_amount = prev_amount + float(actual_tokens)
        if new_amount > 0:
            prev_buy = float(trade.get("buy_price", fill_price) or fill_price)
            trade["buy_price"] = ((prev_buy * prev_amount) + (float(fill_price) * float(actual_tokens))) / new_amount
        trade["amount"] = new_amount
        _ti_add_dca(trade, float(actual_eur), source="dca_limit_fill")
        dca_max_limit = int(settings.max_buys or 3)
        st = _ds_record(
            trade,
            price=float(fill_price),
            amount_eur=float(actual_eur),
            tokens_bought=float(actual_tokens),
            dca_max=dca_max_limit,
            source="bot",
            drop_pct=float(settings.drop_pct),
            step_multiplier=float(settings.step_multiplier),
        )
        # FIX #087: stamp action timestamp so cooldown gate kicks in next loop
        trade["last_dca_action_ts"] = float(time.time())
        return int(st.dca_buys)

    def _send_dca_filled_alert(
        self,
        market: str,
        trade: Dict[str, Any],
        actual_eur: float,
        fill_price: float,
        new_dca_buys: int,
        dca_max_limit: int,
    ) -> None:
        try:
            if not self.ctx.send_alert:
                return
            inv = float(trade.get("invested_eur", 0) or 0)
            avg = float(trade.get("buy_price", fill_price) or fill_price)
            self.ctx.send_alert(
                f"\u2705 DCA Buy {new_dca_buys}/{dca_max_limit} GEVULD | {market}\n"
                f"Prijs: \u20ac{fill_price:.4f} | Bedrag: \u20ac{actual_eur:.2f}\n"
                f"Totaal invested: \u20ac{inv:.2f} | Gem. prijs: \u20ac{avg:.4f}"
            )
        except Exception as e:
            self._log(f"DCA filled telegram failed: {e}", level="warning")

    def _send_dca_placed_alert(
        self,
        market: str,
        commit_eur: float,
        limit_price: float,
        next_level: int,
        dca_max_limit: int,
    ) -> None:
        try:
            if not self.ctx.send_alert:
                return
            self.ctx.send_alert(
                f"\U0001f4e5 DCA limit GEPLAATST {next_level}/{dca_max_limit} | {market}\n"
                f"Limit prijs: \u20ac{limit_price:.4f} | Bedrag: \u20ac{commit_eur:.2f}\n"
                f"Wacht op fill..."
            )
        except Exception as e:
            self._log(f"DCA placed telegram failed: {e}", level="warning")

    def _check_pending_dca_order(
        self,
        market: str,
        trade: Dict[str, Any],
        settings: DCASettings,
    ) -> str:
        """Check the trade's stashed pending DCA limit order.

        Returns one of:
          'no_pending' — nothing stashed; placement may proceed
          'still_open' — order still resting on book within timeout; CALLER MUST RETURN
          'timed_out_cancelled' — stale order was cancelled; CALLER MUST RETURN (wait next loop)
          'filled' — order filled and applied to trade; CALLER MAY CONTINUE to next level
          'cleared' — order is dead/cancelled/rejected; cleared, placement may proceed
          'error' — couldn't determine status; CALLER MUST RETURN (be conservative)
        """
        ctx = self.ctx
        order_id = str(trade.get("pending_dca_order_id", "") or "")
        if not order_id:
            return "no_pending"

        try:
            order = ctx.safe_call(ctx.bitvavo.getOrder, market, order_id)
        except Exception as e:
            self._log(f"getOrder {market} {order_id} failed: {e}", level="warning")
            order = None

        # Fall-back: if getOrder fails (None), try ordersOpen scan
        if not order:
            try:
                open_orders = ctx.safe_call(ctx.bitvavo.ordersOpen, {"market": market}) or []
                match = next((o for o in open_orders if str(o.get("orderId", "")) == order_id), None)
                if match is not None:
                    order = match
            except Exception:
                pass

        if not order:
            # Order not visible anywhere via getOrder() or ordersOpen. The order may
            # have FILLED externally between our loops (Bitvavo MAKER limits sometimes
            # disappear from getOrder() shortly after fill) or it may have been
            # cancelled/rejected and dropped from history.
            #
            # FIX #074 (REGRESSION FROM #073):
            # Old behaviour silently cleared the pending without ever recording the
            # fill. Result: dca_buys / dca_events stayed at 0 while the position
            # actually grew (sync engine updated amount/buy_price), so the next loop
            # fired ANOTHER DCA at the same level. ENJ-EUR executed 4 DCAs (max=3)
            # this way before price recovered.
            #
            # New behaviour: invoke dca_reconcile.reconcile_trade() against Bitvavo's
            # order history. If a missing fill is recovered → 'filled'. Otherwise the
            # order genuinely never filled → 'cleared'.
            try:
                from core.dca_reconcile import reconcile_trade  # local import to avoid cycles

                before_count = len(trade.get("dca_events") or [])
                rec = reconcile_trade(
                    ctx.bitvavo,
                    market,
                    trade,
                    dca_max=int(settings.max_buys or 3),
                    dry_run=False,
                )
                after_count = len(trade.get("dca_events") or [])
                events_added = max(0, after_count - before_count)
                if events_added > 0:
                    self._record_dca_audit(
                        market,
                        trade,
                        "executed",
                        "pending_invisible_reconciled",
                        {
                            "order_id": order_id,
                            "events_added": events_added,
                            "events_total": after_count,
                            "invested_corrected": rec.invested_corrected,
                        },
                    )
                    self._clear_pending_dca(trade)
                    ctx.save_trades()
                    return "filled"
                # No new events found in history — order really never filled.
                self._record_dca_audit(
                    market,
                    trade,
                    "info",
                    "pending_order_invisible_no_fill_in_history",
                    {"order_id": order_id},
                )
                self._clear_pending_dca(trade)
                ctx.save_trades()
                return "cleared"
            except Exception as exc:
                # Reconcile itself failed. Be conservative: keep the pending stash so
                # next loop retries getOrder() rather than firing a duplicate DCA.
                self._log(
                    f"reconcile after invisible pending {market} {order_id} failed: {exc}",
                    level="warning",
                )
                self._record_dca_audit(
                    market,
                    trade,
                    "skip",
                    "pending_invisible_reconcile_failed",
                    {"order_id": order_id, "error": str(exc)[:200]},
                )
                return "error"

        status = str(order.get("status", "")).lower().strip()
        try:
            filled_eur = float(order.get("filledAmountQuote", 0) or 0)
        except (TypeError, ValueError):
            filled_eur = 0.0
        try:
            filled_tokens = float(order.get("filledAmount", 0) or 0)
        except (TypeError, ValueError):
            filled_tokens = 0.0
        try:
            limit_price = float(order.get("price", 0) or 0)
        except (TypeError, ValueError):
            limit_price = float(trade.get("pending_dca_order_price", 0) or 0)

        if status == "filled" or (filled_tokens > 0 and filled_eur > 0 and status not in _OPEN_LIKE_STATUSES):
            fill_price = (filled_eur / filled_tokens) if filled_tokens > 0 else (limit_price or 0.0)
            new_dca_buys = self._record_filled_dca(
                market,
                trade,
                filled_eur,
                filled_tokens,
                fill_price,
                settings,
            )
            self._send_dca_filled_alert(
                market,
                trade,
                filled_eur,
                fill_price,
                new_dca_buys,
                int(settings.max_buys or 3),
            )
            self._record_dca_audit(
                market,
                trade,
                "executed",
                "limit_filled",
                {
                    "order_id": order_id,
                    "filled_eur": filled_eur,
                    "filled_tokens": filled_tokens,
                    "fill_price": fill_price,
                },
            )
            self._clear_pending_dca(trade)
            ctx.save_trades()
            return "filled"

        if status in _OPEN_LIKE_STATUSES:
            try:
                age = time.time() - float(trade.get("pending_dca_order_ts", 0) or 0)
            except Exception:
                age = 0.0
            timeout = float(
                ctx.config.get("DCA_LIMIT_ORDER_TIMEOUT_SECONDS", ctx.config.get("LIMIT_ORDER_TIMEOUT_SECONDS", 600))
                or 600
            )
            if timeout > 0 and age > timeout:
                cancelled = self._cancel_order_safe(market, order_id)
                # Even if cancel call failed, partial fill may have happened — record any partial
                if filled_tokens > 0 and filled_eur > 0:
                    fill_price = filled_eur / filled_tokens
                    new_dca_buys = self._record_filled_dca(
                        market,
                        trade,
                        filled_eur,
                        filled_tokens,
                        fill_price,
                        settings,
                    )
                    self._send_dca_filled_alert(
                        market,
                        trade,
                        filled_eur,
                        fill_price,
                        new_dca_buys,
                        int(settings.max_buys or 3),
                    )
                self._record_dca_audit(
                    market,
                    trade,
                    "cancel",
                    "limit_timeout",
                    {
                        "order_id": order_id,
                        "age_s": age,
                        "timeout_s": timeout,
                        "cancel_ok": cancelled,
                        "partial_eur": filled_eur,
                        "partial_tokens": filled_tokens,
                    },
                )
                self._clear_pending_dca(trade)
                ctx.save_trades()
                return "timed_out_cancelled"
            self._record_dca_audit(
                market,
                trade,
                "skip",
                "pending_limit_order",
                {"order_id": order_id, "age_s": age, "timeout_s": timeout, "status": status},
            )
            return "still_open"

        if status in _DEAD_STATUSES:
            # Cancelled/rejected/expired — apply any partial fill, then clear.
            if filled_tokens > 0 and filled_eur > 0:
                fill_price = filled_eur / filled_tokens
                new_dca_buys = self._record_filled_dca(
                    market,
                    trade,
                    filled_eur,
                    filled_tokens,
                    fill_price,
                    settings,
                )
                self._send_dca_filled_alert(
                    market,
                    trade,
                    filled_eur,
                    fill_price,
                    new_dca_buys,
                    int(settings.max_buys or 3),
                )
                self._record_dca_audit(
                    market,
                    trade,
                    "executed",
                    f"partial_fill_after_{status}",
                    {"order_id": order_id, "filled_eur": filled_eur, "filled_tokens": filled_tokens},
                )
            else:
                self._record_dca_audit(market, trade, "info", f"pending_{status}", {"order_id": order_id})
            self._clear_pending_dca(trade)
            ctx.save_trades()
            return "cleared"

        # Unknown status — conservative
        self._record_dca_audit(
            market, trade, "skip", "unknown_pending_status", {"order_id": order_id, "status": status}
        )
        return "error"
