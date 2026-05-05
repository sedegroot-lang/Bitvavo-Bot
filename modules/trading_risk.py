"""Centralised risk management utilities for the trading bot.

This module analyses historical trade performance to derive drawdown thresholds
per market segment and offers a guard that is consulted before new positions
are opened.  It also exposes optional helpers that attach risk profiles to
trades so the execution loop can respect segment specific stop levels.
"""

from __future__ import annotations

import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, MutableMapping, Optional

import numpy as np

__all__ = [
    "RiskContext",
    "RiskMetrics",
    "RiskDecision",
    "RiskManager",
    "segment_for_market",
    "compute_drawdown_stats",
]


Number = float | int
TradeDict = MutableMapping[str, Any]


def segment_for_market(market: str, config: Mapping[str, Any]) -> str:
    """Return the logical risk segment name for *market*.

    Segments default to ``majors`` (BTC/ETH/BNB), ``stable`` (USDT/USDC/EUR) and
    ``alts`` for everything else.  The sets can be tailored via the configuration
    keys ``RISK_MAJOR_COINS`` and ``RISK_STABLE_COINS``.
    """

    if not market:
        return "alts"
    base_asset = market.split("-", 1)[0].upper()
    majors = {str(sym).upper() for sym in config.get("RISK_MAJOR_COINS", ["BTC", "ETH", "BNB"])}
    stables = {str(sym).upper() for sym in config.get("RISK_STABLE_COINS", ["USDT", "USDC", "DAI", "EUR"])}
    if base_asset in majors:
        return "majors"
    if base_asset in stables:
        return "stable"
    return "alts"


def _as_positive_float(value: Any) -> Optional[float]:
    try:
        res = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(res) or res <= 0:
        return None
    return res


def compute_drawdown_stats(pnls: Iterable[Number]) -> tuple[float, float]:
    """Return ``(current_drawdown, max_drawdown)`` for a PnL series.

    The drawdown amounts are expressed in absolute EUR terms (positive numbers),
    where ``current_drawdown`` is the distance from the latest peak to the current
    value and ``max_drawdown`` is the worst historical drop.
    """

    series = [float(p or 0.0) for p in pnls]
    if not series:
        return 0.0, 0.0
    cum = np.cumsum(series, dtype=float)
    running_max = np.maximum.accumulate(cum)
    drawdowns = running_max - cum
    return float(drawdowns[-1]), float(np.max(drawdowns))


@dataclass(slots=True)
class RiskMetrics:
    """Aggregated drawdown and performance statistics."""

    last_updated: float = 0.0
    global_current_drawdown: float = 0.0
    global_max_drawdown: float = 0.0
    segment_drawdowns: Dict[str, float] = field(default_factory=dict)
    segment_max_drawdowns: Dict[str, float] = field(default_factory=dict)
    segment_thresholds: Dict[str, float] = field(default_factory=dict)
    segment_losses: Dict[str, List[float]] = field(default_factory=dict)
    win_rate: float = 0.0
    sample_size: int = 0


@dataclass(slots=True)
class RiskDecision:
    """Result of evaluating a prospective trade against risk guards."""

    allowed: bool
    reason: str
    metrics: RiskMetrics


@dataclass(slots=True)
class RiskContext:
    """Dependencies required by :class:`RiskManager`."""

    config: Dict[str, Any]
    log: Callable[[str], None]
    load_trade_snapshot: Callable[[], Mapping[str, Any]]
    get_open_trades: Callable[[], Mapping[str, TradeDict]]
    current_open_exposure_eur: Callable[[], float]
    now: Callable[[], float] = time.time


class RiskManager:
    """Analyse trade history and enforce structured risk limits."""

    def __init__(self, ctx: RiskContext) -> None:
        self.ctx = ctx
        self._metrics = RiskMetrics()
        self._lock = threading.RLock()
        self._api_error_counter = 0
        self.refresh(force=True)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    @property
    def metrics(self) -> RiskMetrics:
        with self._lock:
            return self._metrics

    def refresh(self, *, force: bool = False) -> None:
        """Recompute drawdown statistics from the latest trade snapshot."""

        refresh_seconds = float(self.ctx.config.get("RISK_REFRESH_SECONDS", 90.0))
        now = self.ctx.now()
        with self._lock:
            if not force and (now - self._metrics.last_updated) < refresh_seconds:
                return
            try:
                snapshot = self.ctx.load_trade_snapshot() or {}
            except Exception as exc:  # pragma: no cover - defensive logging
                self.ctx.log(f"RiskManager: kon trade snapshot niet laden: {exc}", level="warning")
                snapshot = {}
            closed_iter = snapshot.get("closed")
            if not isinstance(closed_iter, Iterable):
                closed_trades: List[Mapping[str, Any]] = []
            else:
                closed_trades = [t for t in closed_iter if isinstance(t, Mapping)]

            pnls = [float(t.get("profit", 0.0) or 0.0) for t in closed_trades]
            current_dd, max_dd = compute_drawdown_stats(pnls)
            segment_drawdowns: Dict[str, float] = {}
            segment_max: Dict[str, float] = {}
            segment_losses: Dict[str, List[float]] = {}
            segment_thresholds: Dict[str, float] = {}

            for trade in closed_trades:
                market = str(trade.get("market", ""))
                segment = segment_for_market(market, self.ctx.config)
                seg_list = segment_losses.setdefault(segment, [])
                profit = float(trade.get("profit", 0.0) or 0.0)
                if profit < 0:
                    seg_list.append(abs(profit))

            segment_pnls: Dict[str, List[float]] = {}
            for trade, pnl in zip(closed_trades, pnls):
                segment = segment_for_market(str(trade.get("market", "")), self.ctx.config)
                segment_pnls.setdefault(segment, []).append(pnl)

            for segment, seg_pnls in segment_pnls.items():
                seg_current, seg_max = compute_drawdown_stats(seg_pnls)
                segment_drawdowns[segment] = seg_current
                segment_max[segment] = seg_max

            base_limits_cfg = self.ctx.config.get("RISK_SEGMENT_BASE_LIMITS", {})
            if not isinstance(base_limits_cfg, Mapping):
                base_limits_cfg = {}
            default_seg_limit = float(base_limits_cfg.get("default", 100.0))
            multiplier = float(self.ctx.config.get("RISK_SEGMENT_MULTIPLIER", 1.5))

            for segment, losses in segment_losses.items():
                if losses:
                    p95 = statistics.quantiles(losses, n=100, method="inclusive")[94] if len(losses) >= 2 else losses[0]
                    base_limit = float(base_limits_cfg.get(segment, default_seg_limit))
                    segment_thresholds[segment] = max(base_limit, p95 * multiplier)
                else:
                    segment_thresholds[segment] = float(base_limits_cfg.get(segment, default_seg_limit))

            win_rate = 0.0
            if closed_trades:
                wins = sum(1 for trade in closed_trades if float(trade.get("profit", 0.0) or 0.0) > 0)
                win_rate = wins / len(closed_trades)

            self._metrics = RiskMetrics(
                last_updated=now,
                global_current_drawdown=current_dd,
                global_max_drawdown=max_dd,
                segment_drawdowns=segment_drawdowns,
                segment_max_drawdowns=segment_max,
                segment_thresholds=segment_thresholds,
                segment_losses=segment_losses,
                win_rate=win_rate,
                sample_size=len(closed_trades),
            )
            self.ctx.log(
                "Risk metrics geüpdatet: global_dd={:.2f}EUR, thresholds={}".format(current_dd, segment_thresholds),
                level="debug",
            )

    def assess_new_trade(
        self,
        market: str,
        amount_eur: float,
        *,
        entry_price: Optional[float] = None,
        score: Optional[float] = None,
    ) -> RiskDecision:
        """Evaluate whether opening a trade is permitted under current risk limits, incl. portfolio correlation check."""

        self.refresh()
        with self._lock:
            metrics = self._metrics
        segment = segment_for_market(market, self.ctx.config)

        # --- Portfolio correlation check ---
        try:
            open_trades = self.ctx.get_open_trades()
            if open_trades and "BTC-EUR" in open_trades:
                # Verzamel returns van open posities en BTC
                # Simpel: gebruik buy_price vs huidige prijs als return
                def get_return(m, t):
                    buy = t.get("buy_price")
                    cur = t.get("highest_price") or t.get("buy_price")
                    if buy and cur:
                        return (cur - buy) / buy
                    return 0.0

                btc_returns = [get_return("BTC-EUR", open_trades["BTC-EUR"])]
                correlated = 0
                total = 0
                for m, t in open_trades.items():
                    if m == "BTC-EUR":
                        continue
                    r = get_return(m, t)
                    # Simuleer correlatie: als return binnen 70% van BTC return, tel als gecorreleerd
                    if abs(r - btc_returns[0]) < 0.07:  # ±7% return window
                        correlated += 1
                    total += 1
                if total > 0 and correlated / total > 0.7:
                    reason = (
                        f"Portfolio >70% gecorreleerd met BTC (correlated={correlated}/{total}), entry geblokkeerd."
                    )
                    self.ctx.log(reason, level="warning")
                    return RiskDecision(False, reason, metrics)
        except Exception as exc:
            self.ctx.log(f"Portfolio correlatie-check faalde: {exc}", level="error")

        # --- Originele risk checks ---
        segment_threshold = metrics.segment_thresholds.get(segment)
        if segment_threshold is None:
            segment_threshold = float(self.ctx.config.get("RISK_SEGMENT_BASE_LIMITS", {}).get(segment, 100.0))

        segment_drawdown = metrics.segment_drawdowns.get(segment, 0.0)
        if segment_threshold and segment_drawdown >= segment_threshold:
            reason = f"Segment {segment} drawdown {segment_drawdown:.2f} EUR >= threshold {segment_threshold:.2f} EUR"
            return RiskDecision(False, reason, metrics)

        global_block = float(self.ctx.config.get("RISK_BLOCK_DRAWNDOWN_EUR", 0.0))
        if not global_block:
            global_block = float(self.ctx.config.get("RISK_MAX_GLOBAL_DRAWDOWN_EUR", 0.0))
        global_drawdown = metrics.global_current_drawdown
        if global_block and global_drawdown >= global_block:
            reason = f"Global drawdown {global_drawdown:.2f} EUR >= limit {global_block:.2f} EUR"
            return RiskDecision(False, reason, metrics)

        max_total = float(self.ctx.config.get("MAX_TOTAL_EXPOSURE_EUR", 0) or 0)
        if max_total > 0:
            try:
                current_exp = float(self.ctx.current_open_exposure_eur() or 0.0)
            except Exception:
                current_exp = 0.0
            # FIX SESSION2 #4: Tighten tolerance from 5% to 0% — never exceed limit
            if (current_exp + float(amount_eur or 0.0)) > max_total:
                reason = f"Exposure {current_exp + float(amount_eur or 0.0):.2f} EUR zou limiet {max_total:.2f} EUR overschrijden"
                return RiskDecision(False, reason, metrics)

        profile = self._stop_profile_for_segment(segment)
        est_loss = None
        if profile:
            hard_sl_pct = _as_positive_float(profile.get("hard_sl_pct"))
            max_loss_eur = _as_positive_float(profile.get("max_loss_eur"))
            if hard_sl_pct is not None:
                est_loss = float(amount_eur or 0.0) * hard_sl_pct
            if max_loss_eur is not None and est_loss is not None and est_loss > max_loss_eur:
                reason = f"Geschatte verlies {est_loss:.2f} EUR overschrijdt stop-profiel limiet {max_loss_eur:.2f} EUR"
                return RiskDecision(False, reason, metrics)

        return RiskDecision(True, "OK", metrics)

    def apply_stop_profile(self, market: str, trade: TradeDict, *, entry_price: Optional[float] = None) -> None:
        """Attach risk profile metadata to *trade* based on configuration."""

        segment = segment_for_market(market, self.ctx.config)
        profile = self._stop_profile_for_segment(segment)
        if not profile:
            return
        trade.setdefault("risk_profile", {"segment": segment})
        trade["risk_profile"].update({k: v for k, v in profile.items() if k not in {"label"}})
        if entry_price is None:
            try:
                entry_price = float(trade.get("buy_price"))
            except (TypeError, ValueError):
                entry_price = None
        stop_pct = _as_positive_float(profile.get("hard_sl_pct"))
        if stop_pct is not None and entry_price:
            trade["risk_stop_price"] = float(entry_price) * (1.0 - stop_pct)

    def attach_ai_target(self, trade: TradeDict, *, entry_price: float, score: Optional[float] = None) -> None:
        """Set an AI-backed profit target on *trade* based on heuristics."""

        default_gain = float(self.ctx.config.get("AI_TARGET_BASE_GAIN_PCT", 0.05))
        max_gain = float(self.ctx.config.get("AI_TARGET_MAX_GAIN_PCT", 0.12))
        min_gain = float(self.ctx.config.get("AI_TARGET_MIN_GAIN_PCT", 0.03))
        gain = default_gain
        if score is not None:
            gain = min(max_gain, max(min_gain, default_gain + (float(score) - 5.0) * 0.01))
        trade["ai_target_gain_pct"] = gain
        trade["ai_target_price"] = float(entry_price) * (1.0 + gain)

    def record_api_error(self) -> None:
        with self._lock:
            self._api_error_counter += 1

    def consume_api_error_count(self) -> int:
        with self._lock:
            count = self._api_error_counter
            self._api_error_counter = 0
            return count

    # ------------------------------------------------------------------
    # Portfolio-level circuit breaker
    # ------------------------------------------------------------------

    def check_circuit_breaker(self) -> RiskDecision:
        """Check if portfolio drawdown exceeds circuit breaker threshold.

        Config keys:
          RISK_CIRCUIT_BREAKER_EUR   — max portfolio drawdown in EUR (default 50)
          RISK_DAILY_LOSS_LIMIT_EUR  — max loss per calendar day (default 25)
          RISK_CIRCUIT_COOLDOWN_SEC  — seconds to wait after circuit break (default 3600)
        """
        self.refresh()
        with self._lock:
            metrics = self._metrics

        # Portfolio drawdown circuit breaker
        cb_limit = float(self.ctx.config.get("RISK_CIRCUIT_BREAKER_EUR", 50.0))
        if cb_limit > 0 and metrics.global_current_drawdown >= cb_limit:
            reason = (
                f"🔴 CIRCUIT BREAKER: Portfolio drawdown €{metrics.global_current_drawdown:.2f} "
                f">= limit €{cb_limit:.2f} — ALL new trades blocked"
            )
            self.ctx.log(reason, level="error")
            return RiskDecision(False, reason, metrics)

        # Daily loss limit
        daily_limit = float(self.ctx.config.get("RISK_DAILY_LOSS_LIMIT_EUR", 25.0))
        if daily_limit > 0:
            try:
                snapshot = self.ctx.load_trade_snapshot() or {}
                closed = snapshot.get("closed", [])
                today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
                daily_loss = sum(
                    abs(float(t.get("profit", 0) or 0))
                    for t in closed
                    if isinstance(t, dict)
                    and float(t.get("profit", 0) or 0) < 0
                    and float(t.get("timestamp", 0) or 0) >= today_start
                )
                if daily_loss >= daily_limit:
                    reason = f"🔴 DAILY LOSS LIMIT: €{daily_loss:.2f} losses today >= limit €{daily_limit:.2f}"
                    self.ctx.log(reason, level="error")
                    return RiskDecision(False, reason, metrics)
            except Exception as exc:
                self.ctx.log(f"Daily loss check failed: {exc}", level="warning")

        return RiskDecision(True, "OK", metrics)

    # ------------------------------------------------------------------
    # Kelly Criterion position sizing
    # ------------------------------------------------------------------

    def kelly_position_size(
        self,
        base_amount_eur: float,
        *,
        market: Optional[str] = None,
        min_trades: int = 20,
        max_fraction: float = 0.5,
    ) -> float:
        """Calculate position size using fractional Kelly Criterion.

        Uses historical win rate and avg win/loss ratio to determine optimal
        bet fraction, then applies half-Kelly for safety.

        Config keys:
          RISK_KELLY_ENABLED       — master switch (default True)
          RISK_KELLY_FRACTION      — fraction of Kelly to use (default 0.5 = half-Kelly)
          RISK_KELLY_MIN_AMOUNT    — minimum position size EUR (default 5.0)

        Returns the suggested position size in EUR.
        """
        if not self.ctx.config.get("RISK_KELLY_ENABLED", True):
            return base_amount_eur

        with self._lock:
            metrics = self._metrics

        if metrics.sample_size < min_trades:
            # Not enough data for Kelly — use base amount
            return base_amount_eur

        try:
            snapshot = self.ctx.load_trade_snapshot() or {}
            closed = snapshot.get("closed", [])
            if not isinstance(closed, list) or len(closed) < min_trades:
                return base_amount_eur

            wins = []
            losses = []
            for t in closed:
                if not isinstance(t, dict):
                    continue
                profit = float(t.get("profit", 0) or 0)
                invested = float(t.get("invested_eur", 0) or 0)
                if invested <= 0:
                    continue
                pct = profit / invested
                if profit > 0:
                    wins.append(pct)
                elif profit < 0:
                    losses.append(abs(pct))

            if not wins or not losses:
                return base_amount_eur

            win_rate = len(wins) / (len(wins) + len(losses))
            avg_win = statistics.mean(wins)
            avg_loss = statistics.mean(losses)

            if avg_loss <= 0:
                return base_amount_eur

            # Kelly formula: f* = W - (1-W)/R where W=win_rate, R=avg_win/avg_loss
            win_loss_ratio = avg_win / avg_loss
            kelly_fraction = win_rate - (1 - win_rate) / win_loss_ratio

            if kelly_fraction <= 0:
                # Negative Kelly = losing strategy → don't trade
                self.ctx.log(
                    f"Kelly negative ({kelly_fraction:.3f}) — skip new trades until win rate improves",
                    level="warning",
                )
                return 0.0

            # Apply fractional Kelly (default half-Kelly)
            frac = float(self.ctx.config.get("RISK_KELLY_FRACTION", 0.5))
            kelly_fraction *= frac

            # Cap at max_fraction of base
            kelly_fraction = min(kelly_fraction, max_fraction)

            # Calculate final amount
            budget = float(self.ctx.config.get("MAX_INVESTMENT_EUR", 200.0))
            kelly_amount = budget * kelly_fraction
            min_amount = float(self.ctx.config.get("RISK_KELLY_MIN_AMOUNT", 5.0))
            result = max(min_amount, min(kelly_amount, base_amount_eur * 2))

            self.ctx.log(
                f"Kelly sizing: WR={win_rate:.2f}, W/L={win_loss_ratio:.2f}, "
                f"f*={kelly_fraction:.3f}, amount=€{result:.2f}",
                level="debug",
            )
            return result

        except Exception as exc:
            self.ctx.log(f"Kelly calculation failed: {exc}", level="warning")
            return base_amount_eur

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _stop_profile_for_segment(self, segment: str) -> Optional[Mapping[str, Any]]:
        profiles = self.ctx.config.get("RISK_STOP_PROFILES") or {}
        if not isinstance(profiles, Mapping):
            return None
        profile = profiles.get(segment) or profiles.get("default")
        if isinstance(profile, Mapping):
            return profile
        return None
