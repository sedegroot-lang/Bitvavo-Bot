"""Monitoring utilities for the trading bot."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

from modules.metrics import MetricsCollector

if TYPE_CHECKING:  # pragma: no cover - typing only
    from modules.trading_risk import RiskMetrics


@dataclass
class MonitoringContext:
    log: Callable[[str], None]
    write_json_locked: Callable[[str, Any], None]
    safe_call: Callable[..., Any]
    bitvavo: Any
    estimate_max_eur_per_trade: Callable[[], Optional[float]]
    estimate_max_total_eur: Callable[[], Optional[float]]
    current_open_exposure_eur: Callable[[], Optional[float]]
    trade_log_path: str
    heartbeat_file: str = "data/heartbeat.json"
    ai_heartbeat_path: str = "data/ai_heartbeat.json"
    ai_heartbeat_stale_seconds: int = 900
    metrics_collector: Optional[MetricsCollector] = None
    risk_metrics_provider: Optional[Callable[[], "RiskMetrics"]] = None
    consume_api_error_count: Optional[Callable[[], int]] = None
    portfolio_snapshot_path: Optional[str] = None
    partial_tp_stats_provider: Optional[Callable[[], Dict[str, Any]]] = None
    event_hook_status_provider: Optional[Callable[[], Dict[str, Any]]] = None


class MonitoringManager:
    """Encapsulates background monitoring helpers."""

    def __init__(self, ctx: MonitoringContext) -> None:
        self.ctx = ctx

    def start_reservation_watchdog(
        self,
        reservations: Union[Dict[str, float], Callable[[], Dict[str, float]]],
        *,
        interval: int = 30,
        max_age_seconds: int = 300,
    ) -> threading.Thread:
        """Start a watchdog thread to clean up stale reservations.

        Note: If using ReservationManager (callable), the manager handles
        auto-expiry internally, so this watchdog becomes a no-op monitor.
        """
        log = self.ctx.log

        def cleaner() -> None:
            while True:
                try:
                    # Support both dict and callable (ReservationManager)
                    if callable(reservations):
                        # ReservationManager handles expiry internally
                        # Just log stats for monitoring
                        try:
                            current = reservations() or {}
                            if current:
                                log(f"Reservation watchdog: {len(current)} active reservations", level="debug")
                        except Exception:
                            pass
                    else:
                        # Legacy dict mode - clean up manually
                        now = time.time()
                        stale = [
                            market for market, ts in list(reservations.items()) if (now - float(ts)) > max_age_seconds
                        ]
                        for market in stale:
                            reservations.pop(market, None)
                            log(
                                f"Reservation watchdog: removed stale reservation for {market}",
                                level="warning",
                            )
                except Exception:
                    pass
                time.sleep(interval)

        thread = threading.Thread(target=cleaner, daemon=True)
        thread.start()
        return thread

    def start_heartbeat_writer(
        self,
        open_trades_provider: Callable[[], Dict[str, Any]],
        pending_new_markets: Union[Dict[str, Any], Callable[[], Dict[str, Any]]],
        *,
        interval: int = 30,
        dust_threshold_eur: float = 1.0,
        scan_stats_provider: Callable[[], Dict] = None,
    ) -> threading.Thread:
        ctx = self.ctx
        log = ctx.log

        def writer() -> None:
            while True:
                try:
                    try:
                        open_trades = open_trades_provider() or {}
                        if isinstance(open_trades, dict):
                            # Filter out dust trades: only count trades above threshold
                            filtered_trades = {
                                m: t
                                for m, t in open_trades.items()
                                if isinstance(t, dict) and float(t.get("invested_eur", 0) or 0) >= dust_threshold_eur
                            }
                            open_len = len(filtered_trades)
                            open_len_including_dust = len(open_trades)
                            dust_count = open_len_including_dust - open_len
                        else:
                            open_len = 0
                            open_len_including_dust = 0
                            dust_count = 0
                    except Exception:
                        open_len = 0
                        open_len_including_dust = 0
                        dust_count = 0

                    try:
                        # If the in-memory provider returned a valid open_len, prefer it.
                        # Only consult the trade log on disk as a fallback when the provider
                        # could not supply a value (open_len == 0).
                        if open_len == 0 and os.path.exists(ctx.trade_log_path):
                            with open(ctx.trade_log_path, "r", encoding="utf-8") as fh:
                                data = json.load(fh)
                            file_open = data.get("open", {})
                            if isinstance(file_open, dict):
                                # Apply dust filter to fallback as well
                                filtered_file = {
                                    m: t
                                    for m, t in file_open.items()
                                    if isinstance(t, dict)
                                    and float(t.get("invested_eur", 0) or 0) >= dust_threshold_eur
                                }
                                open_len = len(filtered_file)
                                open_len_including_dust = len(file_open)
                                dust_count = open_len_including_dust - open_len
                    except Exception:
                        pass

                    # Get pending reservations (supports both dict and callable)
                    try:
                        if callable(pending_new_markets):
                            pending_dict = pending_new_markets() or {}
                        else:
                            pending_dict = pending_new_markets or {}
                        pending_count = len(pending_dict)
                    except Exception:
                        pending_count = 0

                    # Determine source label for debugging: prefer 'memory' when provider supplied a non-zero value
                    source = "memory" if open_len and open_len > 0 else "file"
                    current_ts = time.time()
                    payload = {
                        "ts": current_ts,
                        "timestamp": current_ts,  # Dashboard compatibility
                        "open_trades": open_len,
                        "open_trades_including_dust": open_len_including_dust,
                        "dust_trade_count": dust_count,
                        "open_trades_source": source,
                        "eur_balance": None,
                        "max_eur_per_trade": ctx.estimate_max_eur_per_trade(),
                        "max_total_eur": ctx.estimate_max_total_eur(),
                        "open_exposure_eur": ctx.current_open_exposure_eur() or 0.0,
                        "pending_reservations": pending_count,
                        "last_scan_stats": scan_stats_provider() if scan_stats_provider else {},
                    }

                    try:
                        balances = ctx.safe_call(ctx.bitvavo.balance, {}) or []
                        for entry in balances:
                            if entry.get("symbol") == "EUR":
                                payload["eur_balance"] = float(entry.get("available", 0) or 0)
                                break
                    except Exception:
                        payload["eur_balance"] = None

                    try:
                        ai_payload = {"online": False, "last_seen": None}
                        ai_active = False  # Dashboard compatibility flag
                        ai_path = ctx.ai_heartbeat_path
                        stale = max(60, int(ctx.ai_heartbeat_stale_seconds or 0))
                        if ai_path and os.path.exists(ai_path):
                            with open(ai_path, "r", encoding="utf-8") as af:
                                ai_doc = json.load(af) or {}
                            ts_val = ai_doc.get("ts")
                            status_text = ai_doc.get("status")
                            last_seen = float(ts_val) if isinstance(ts_val, (int, float)) else None
                            if last_seen is not None:
                                ai_payload["last_seen"] = last_seen
                                ai_online = (time.time() - last_seen) <= stale
                                ai_payload["online"] = ai_online
                                ai_active = ai_online  # Set dashboard flag
                            if status_text:
                                ai_payload["status"] = str(status_text)
                        payload["ai_status"] = ai_payload
                        payload["ai_active"] = ai_active  # Dashboard compatibility
                    except Exception:
                        payload["ai_status"] = {"online": False, "last_seen": None}
                        payload["ai_active"] = False  # Dashboard compatibility

                    # Bot is actively writing heartbeat, so it's online
                    payload["bot_active"] = True

                    if ctx.event_hook_status_provider:
                        try:
                            payload["event_hooks"] = ctx.event_hook_status_provider() or {}
                        except Exception:
                            payload["event_hooks"] = {"enabled": False, "error": "status_fetch_failed"}

                    # Build portfolio snapshot from actual trade_log.json to avoid stale data
                    if ctx.trade_log_path:
                        try:
                            if os.path.exists(ctx.trade_log_path):
                                with open(ctx.trade_log_path, "r", encoding="utf-8") as tf:
                                    trade_doc = json.load(tf) or {}
                                open_trades_data = trade_doc.get("open", {})
                                if isinstance(open_trades_data, dict) and open_trades_data:
                                    per_market = {}
                                    total_exp = 0.0
                                    for market, trade in open_trades_data.items():
                                        if isinstance(trade, dict):
                                            try:
                                                amount = float(trade.get("amount", 0) or 0)
                                                buy_price = float(trade.get("buy_price", 0) or 0)
                                                exposure = amount * buy_price
                                                if exposure > 0:
                                                    per_market[market] = exposure
                                                    total_exp += exposure
                                            except (ValueError, TypeError):
                                                pass
                                    if per_market:
                                        sorted_markets = sorted(per_market.items(), key=lambda kv: kv[1], reverse=True)
                                        top_markets = dict(sorted_markets[:5])
                                        payload["portfolio_snapshot"] = {
                                            "total_exposure_eur": total_exp,
                                            "open_trade_count": len(per_market),
                                            "top_markets": top_markets,
                                        }
                        except Exception:
                            pass

                    if ctx.partial_tp_stats_provider:
                        try:
                            partial_stats = ctx.partial_tp_stats_provider()
                            if partial_stats:
                                payload["partial_tp_stats"] = partial_stats
                        except Exception:
                            pass

                    try:
                        # Schrijf de meest recente heartbeat atomair naar het hoofd-pad
                        ctx.write_json_locked(ctx.heartbeat_file, payload)
                        # Append een compacte history-regel (NDJSON) zodat de dashboard
                        # een tijdreeks kan tonen van o.a. eur_balance.
                        try:
                            hb_history_path = f"{ctx.heartbeat_file}.history.jsonl"
                            line = json.dumps(
                                {
                                    "ts": payload.get("ts"),
                                    "eur_balance": payload.get("eur_balance"),
                                    "open_trades": payload.get("open_trades"),
                                },
                                ensure_ascii=False,
                            )
                            with open(hb_history_path, "a", encoding="utf-8") as hf:
                                hf.write(line + "\n")
                        except Exception:
                            pass

                        # NIEUW: Schrijf ook complete Bitvavo balance history
                        # Dit logt totale account waarde (EUR + alle crypto in EUR)
                        try:
                            balance_history_path = os.path.join(
                                os.path.dirname(ctx.heartbeat_file), "balance_history.jsonl"
                            )

                            # Bereken totaal saldo
                            total_eur = 0.0
                            try:
                                balances = ctx.safe_call(ctx.bitvavo.balance, {}) or []
                                for bal in balances:
                                    symbol = bal.get("symbol")
                                    available = float(bal.get("available", 0) or 0)
                                    in_order = float(bal.get("inOrder", 0) or 0)
                                    total_amount = available + in_order

                                    if total_amount > 0:
                                        if symbol == "EUR":
                                            total_eur += total_amount
                                        else:
                                            # Converteer crypto naar EUR
                                            try:
                                                market = f"{symbol}-EUR"
                                                ticker = ctx.safe_call(ctx.bitvavo.tickerPrice, {"market": market})
                                                if ticker and "price" in ticker:
                                                    price = float(ticker["price"])
                                                    total_eur += total_amount * price
                                            except Exception:
                                                pass
                            except Exception:
                                total_eur = 0.0

                            # Schrijf alleen als we een valide totaal hebben
                            if total_eur > 0:
                                balance_line = json.dumps(
                                    {"ts": payload.get("ts"), "total_eur": round(total_eur, 2)},
                                    ensure_ascii=False,
                                )
                                with open(balance_history_path, "a", encoding="utf-8") as bf:
                                    bf.write(balance_line + "\n")
                        except Exception:
                            pass  # Balance history is optional, don't fail if it errors

                        log(
                            f"Heartbeat written to {ctx.heartbeat_file}: {payload}",
                            level="info",
                        )
                    except Exception as exc:
                        log(f"Failed to write heartbeat: {exc}", level="error")

                    if ctx.metrics_collector:
                        metrics_out: Dict[str, float] = {
                            "bot_open_trades": float(open_len),
                            "bot_open_exposure_eur": float(payload.get("open_exposure_eur", 0.0) or 0.0),
                            "bot_pending_reservations": float(payload.get("pending_reservations", 0) or 0),
                        }
                        balance = payload.get("eur_balance")
                        if isinstance(balance, (int, float)):
                            metrics_out["bot_eur_balance"] = float(balance)
                        snapshot_payload = payload.get("portfolio_snapshot")
                        if isinstance(snapshot_payload, dict):
                            total_exp = snapshot_payload.get("total_exposure_eur")
                            if isinstance(total_exp, (int, float)):
                                metrics_out["bot_portfolio_total_exposure_eur"] = float(total_exp)
                            per_segment = snapshot_payload.get("per_segment") or {}
                            if isinstance(per_segment, dict):
                                for segment, exposure in per_segment.items():
                                    if isinstance(exposure, (int, float)):
                                        metrics_out[f"bot_portfolio_segment_eur_{segment}"] = float(exposure)
                        risk_metrics = None
                        if ctx.risk_metrics_provider:
                            try:
                                risk_metrics = ctx.risk_metrics_provider()
                            except Exception as exc:
                                log(f"Risk metrics ophalen mislukt: {exc}", level="warning")
                        if risk_metrics is not None:
                            metrics_out["bot_global_drawdown_eur"] = float(risk_metrics.global_current_drawdown)
                            metrics_out["bot_global_max_drawdown_eur"] = float(risk_metrics.global_max_drawdown)
                            metrics_out["bot_win_rate"] = float(risk_metrics.win_rate)
                            metrics_out["bot_trade_history"] = float(risk_metrics.sample_size)
                            for segment, seg_dd in (risk_metrics.segment_drawdowns or {}).items():
                                metrics_out[f"bot_segment_drawdown_eur_{segment}"] = float(seg_dd)
                            for segment, seg_dd in (risk_metrics.segment_max_drawdowns or {}).items():
                                metrics_out[f"bot_segment_max_drawdown_eur_{segment}"] = float(seg_dd)
                            for segment, threshold in (risk_metrics.segment_thresholds or {}).items():
                                metrics_out[f"bot_segment_threshold_eur_{segment}"] = float(threshold)
                        partial_stats_payload = payload.get("partial_tp_stats")
                        if isinstance(partial_stats_payload, dict):
                            total_events = partial_stats_payload.get("total_events")
                            if isinstance(total_events, (int, float)):
                                metrics_out["bot_partial_tp_total"] = float(total_events)
                            per_level = partial_stats_payload.get("per_level") or {}
                            if isinstance(per_level, dict):
                                for level, info in per_level.items():
                                    if not isinstance(info, dict):
                                        continue
                                    count = info.get("count")
                                    if isinstance(count, (int, float)):
                                        metrics_out[f"bot_partial_tp_count_{level}"] = float(count)
                        counters_out: Dict[str, float] = {}
                        if ctx.consume_api_error_count:
                            try:
                                api_errors = ctx.consume_api_error_count()
                            except Exception as exc:
                                log(f"API error counter ophalen mislukt: {exc}", level="warning")
                                api_errors = None
                            if api_errors:
                                counters_out["bot_api_errors"] = float(api_errors)
                        try:
                            ctx.metrics_collector.publish(
                                metrics_out,
                                counters=counters_out,
                                labels={"source": "heartbeat"},
                                timestamp=payload.get("ts"),
                            )
                        except Exception as exc:
                            log(f"Metrics publish mislukt: {exc}", level="warning")
                except Exception as exc:
                    log(f"Heartbeat writer error: {exc}", level="warning")
                time.sleep(interval)

        thread = threading.Thread(target=writer, daemon=True)
        thread.start()
        return thread

    def start_heartbeat_monitor(
        self,
        send_alert: Callable[[str], None],
        *,
        alert_stale_seconds: int,
        interval: int = 60,
    ) -> threading.Thread:
        ctx = self.ctx
        log = ctx.log

        # Re-read this flag inside the loop so config hot-reload works without restart.
        def _alerts_enabled() -> bool:
            try:
                from modules.config import CONFIG as _CFG

                return bool(_CFG.get("HEARTBEAT_STALE_ALERT_ENABLED", True))
            except Exception:
                return True

        def monitor() -> None:
            # Wacht eerst lang genoeg zodat de bot zijn eerste heartbeat kan schrijven
            # voordat we beginnen te controleren (voorkomt valse alerts na herstart)
            time.sleep(max(alert_stale_seconds, 120))
            last_alert_ts = 0.0
            base_cooldown = max(600, alert_stale_seconds * 3)  # min 10 min between alerts
            current_cooldown = base_cooldown
            max_cooldown = 7200  # max 2 uur tussen alerts bij aanhoudende downtime
            consecutive_stale = 0  # require N consecutive stale reads before alerting
            STALE_CONFIRMATIONS = 3  # ~3 minutes at interval=60s
            while True:
                try:
                    ts = None
                    # Retry the read up to 3x with small backoff so a transient
                    # OS error mid os.replace() doesn't trigger a false alert.
                    for attempt in range(3):
                        try:
                            if os.path.exists(ctx.heartbeat_file):
                                with open(ctx.heartbeat_file, "r", encoding="utf-8-sig") as fh:
                                    content = fh.read().strip()
                                    if content:
                                        data = json.loads(content)
                                        ts = data.get("ts") or data.get("timestamp")
                            if ts is not None:
                                break
                        except (OSError, json.JSONDecodeError):
                            time.sleep(0.1 * (attempt + 1))
                    if ts is not None and time.time() - float(ts) <= alert_stale_seconds:
                        # Heartbeat is healthy — reset state
                        if current_cooldown != base_cooldown:
                            log("Heartbeat hersteld, backoff gereset.", level="info")
                        current_cooldown = base_cooldown
                        last_alert_ts = 0.0
                        consecutive_stale = 0
                    else:
                        consecutive_stale += 1
                        # Only alert after N consecutive confirmations AND if alerts enabled
                        if consecutive_stale < STALE_CONFIRMATIONS:
                            log(
                                f"Heartbeat stale check {consecutive_stale}/{STALE_CONFIRMATIONS} "
                                f"(last_ts={ts}); waiting for confirmation.",
                                level="debug",
                            )
                        else:
                            now = time.time()
                            if now - last_alert_ts >= current_cooldown:
                                msg = f"ALERT: heartbeat stale or missing (last_ts={ts}). Bot may be down."
                                if _alerts_enabled():
                                    send_alert(msg)
                                else:
                                    log(
                                        f"[heartbeat-monitor] {msg} "
                                        "(Telegram alert disabled via HEARTBEAT_STALE_ALERT_ENABLED=false)",
                                        level="warning",
                                    )
                                last_alert_ts = now
                                # Verdubbel de cooldown bij elke herhaalde alert
                                current_cooldown = min(current_cooldown * 2, max_cooldown)
                except Exception as exc:
                    log(f"Heartbeat monitor error: {exc}", level="warning")
                time.sleep(interval)

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        return thread
