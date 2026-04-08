"""Trading synchronization helpers.

This module centralizes the logic that keeps the in-memory trade state in
sync with Bitvavo portfolio balances and trade log persistence.  It exposes
classes that operate on callables/state provided by the main trading bot so
that the heavy lifting lives outside of `trailing_bot.py`.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Import archive_trade for permanent trade storage
try:
    from modules.trade_archive import archive_trade
except ImportError:
    archive_trade = None


def _ensure_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ensure_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


@dataclass
class SyncContext:
    """Configuration bundle required for synchronization helpers."""

    config: Dict[str, Any]
    safe_call: Callable[..., Any]
    bitvavo: Any
    log: Callable[[str], None]
    write_json_locked: Callable[[str, Any], None]
    file_lock: threading.Lock
    save_trades: Callable[[], None]
    trade_log_path: str = "data/trade_log.json"
    pending_saldo_path: str = "data/pending_saldo.json"
    sync_debug_path: str = "sync_debug.json"
    sync_raw_balances_path: str = "sync_raw_balances.json"
    sync_raw_markets_path: str = "sync_raw_markets.json"
    sync_removed_cache_path: str = "sync_removed_cache.json"
    sync_removed_cache_max_age: int = 7 * 24 * 3600
    pending_new_markets: Any = field(default_factory=dict)  # Dict or Callable returning Dict


class TradingSynchronizer:
    """Encapsulates sync operations for the trading bot."""

    def __init__(self, ctx: SyncContext) -> None:
        if ctx.pending_new_markets is None:
            ctx.pending_new_markets = {}
        self.ctx = ctx

    def _get_pending_markets(self) -> Dict[str, float]:
        """Get pending markets dict, supporting both dict and callable."""
        pending = self.ctx.pending_new_markets
        if callable(pending):
            return pending() or {}
        return pending or {}

    # ------------------------------------------------------------------
    # Primary trade_log synchronisation
    # ------------------------------------------------------------------
    def sync_open_trades(
        self,
        open_trades: Dict[str, Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
        market_profits: Dict[str, float],
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], Dict[str, float]]:
        """Return updated copies of the trade state based on live balances."""

        ctx = self.ctx
        log = ctx.log
        safe_call = ctx.safe_call
        bitvavo = ctx.bitvavo

        try:
            balances_payload = safe_call(bitvavo.balance, {}) or []
        except Exception as exc:  # pragma: no cover - network error path
            log(f"Fout bij ophalen balances voor sync: {exc}", level="error")
            return open_trades, closed_trades, market_profits

        if isinstance(balances_payload, dict):
            balances_payload = [balances_payload]
        if not isinstance(balances_payload, list):
            if balances_payload:
                log(
                    "Sync: ontvangen balances payload is geen lijst, wordt genegeerd",
                    level="warning",
                )
            balances_payload = []
        balances = [entry for entry in balances_payload if isinstance(entry, dict)]
        ignored_balances = len(balances_payload) - len(balances)
        if ignored_balances > 0:
            log(
                f"Sync: {ignored_balances} balance entries genegeerd (geen dict)",
                level="warning",
            )

        markets_set: set[str]
        try:
            markets_list = safe_call(bitvavo.markets, {}) or []
            markets_set = {
                m.get("market")
                for m in markets_list
                if isinstance(m, dict) and m.get("market")
            }
        except Exception:
            markets_set = set()

        def find_best_market(base: str) -> Optional[str]:
            candidates = [
                f"{base}-EUR",
                f"{base}-USDC",
                f"{base}-USDT",
                f"{base}-BTC",
            ]
            for candidate in candidates:
                if candidate in markets_set:
                    return candidate
            for item in markets_set:
                if item.startswith(base + "-"):
                    return item
            return None

        open_markets: Dict[str, float] = {}
        for balance_entry in balances:
            symbol = balance_entry.get("symbol")
            available = float(balance_entry.get("available", 0) or 0)
            if not symbol or available <= 0:
                continue
            if "-" in symbol and symbol in markets_set:
                open_markets[symbol] = available
                continue
            best = find_best_market(symbol)
            if best:
                open_markets[best] = open_markets.get(best, 0.0) + available
                continue
            alt = (
                find_best_market(symbol.split()[0])
                if " " in symbol
                else None
            )
            if alt:
                open_markets[alt] = open_markets.get(alt, 0.0) + available

        trade_log_path = ctx.trade_log_path
        data = {"open": {}, "closed": [], "profits": {}}
        if os.path.exists(trade_log_path):
            try:
                with open(trade_log_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if not isinstance(data, dict):
                    raise ValueError("trade_log.json is geen object")
            except Exception as exc:  # pragma: no cover - malformed JSON
                log(f"Fout in trade_log.json: {exc}", level="error")
                data = {"open": {}, "closed": [], "profits": {}}

        open_state = _ensure_dict(data.get("open"))
        closed_state = _ensure_list(data.get("closed"))
        profit_state = _ensure_dict(data.get("profits"))

        changes_made = False

        try:
            debug_payload = {
                "ts": time.time(),
                "raw_balances_count": len(balances),
                "mapped_open_markets": list(open_markets.items())[:200],
                "markets_set_sample": list(markets_set)[:200],
            }
            ctx.write_json_locked(ctx.sync_debug_path, debug_payload, indent=2)
            log(
                f"Wrote {ctx.sync_debug_path} with {len(open_markets)} mapped markets.",
                level="info",
            )
        except Exception as exc:
            log(f"Failed to write {ctx.sync_debug_path}: {exc}", level="warning")

        # --- DISABLE_SYNC_REMOVE guard (Bug fix: respect config flag) ---
        disable_sync_remove = ctx.config.get("DISABLE_SYNC_REMOVE", True)

        to_remove = [
            market
            for market in open_state.keys()
            if market not in open_markets or open_markets.get(market, 0.0) <= 0
        ]

        # API glitch protection: if ALL open_markets are empty but we have
        # open_state entries, the API likely returned bad data — skip removal
        if to_remove and not open_markets and len(open_state) > 0:
            log(
                "Sync: API returned empty balances but we have open trades — "
                "skipping removal to prevent data loss",
                level="warning",
            )
            to_remove = []

        if disable_sync_remove and to_remove:
            log(
                f"Sync: DISABLE_SYNC_REMOVE=true — skipping removal of "
                f"{len(to_remove)} trades: {to_remove}",
                level="warning",
            )
            to_remove = []

        removed_entries: List[Tuple[str, Dict[str, Any]]] = []
        for market in to_remove:
            if market in open_state:
                removed_entries.append((market, open_state[market]))
                open_state.pop(market, None)
                changes_made = True

        if removed_entries:
            ts = time.time()
            for market, entry in removed_entries:
                # Calculate approximate profit instead of hardcoding 0.0
                buy_price = float(entry.get("buy_price") or 0)
                amount = float(entry.get("amount") or 0)
                invested = float(entry.get("invested_eur") or (buy_price * amount))
                profit = -invested if invested > 0 else 0.0  # Assume total loss if removed
                closed_state.append(
                    {
                        "market": market,
                        "buy_price": buy_price,
                        "sell_price": 0.0,
                        "amount": amount,
                        "profit": profit,
                        "invested_eur": invested,
                        "timestamp": ts,
                        "reason": "sync_removed",
                    }
                )
                log(
                    "Sync: verwijderd uit open_trades omdat positie ontbreekt bij Bitvavo: "
                    f"{market} (profit={profit:.2f})",
                    level="info",
                )
            max_closed = max(1, int(ctx.config.get("MAX_CLOSED", 200)))
            if len(closed_state) > max_closed:
                closed_state = closed_state[-max_closed:]

        missing = [
            market
            for market, amount in open_markets.items()
            if market not in open_state and amount > 0
        ]
        try:
            max_trades = max(1, int(ctx.config.get("MAX_OPEN_TRADES", 5)))
            reserved = len(self._get_pending_markets())
            room = max(0, max_trades - (len(open_state) + reserved))
            if room < len(missing):
                missing = missing[:room]
        except Exception:
            pass

        if missing:
            pending_entries: List[Dict[str, Any]] = []
            if os.path.exists(ctx.pending_saldo_path):
                try:
                    with open(ctx.pending_saldo_path, "r", encoding="utf-8") as pf:
                        pending_entries = json.load(pf) or []
                except Exception:
                    pending_entries = []
            for market in missing:
                reconstructed = None
                for pending in pending_entries:
                    if pending.get("market") == market and pending.get("open_trade"):
                        reconstructed = pending.get("open_trade")
                        break
                if reconstructed:
                    if reconstructed.get("buy_price") is None:
                        reconstructed["buy_price"] = (
                            reconstructed.get("highest_price") or 0.0
                        )
                    if reconstructed.get("highest_price") is None:
                        reconstructed["highest_price"] = (
                            reconstructed.get("buy_price") or 0.0
                        )
                    open_state[market] = reconstructed
                    log(
                        f"Sync: reconstructed open trade for {market} from pending_saldo.json",
                        level="info",
                    )
                    changes_made = True
                else:
                    # Auto-discover: position exists on Bitvavo but not tracked locally
                    try:
                        from modules.cost_basis import derive_cost_basis
                        amount = open_markets.get(market, 0.0)
                        basis = derive_cost_basis(ctx.bitvavo, market, amount, tolerance=0.02)
                        if basis and getattr(basis, 'avg_price', 0) > 0:
                            new_entry = {
                                'market': market,
                                'buy_price': float(basis.avg_price),
                                'highest_price': float(basis.avg_price),
                                'amount': amount,
                                'invested_eur': float(basis.invested_eur),
                                'initial_invested_eur': float(basis.invested_eur),
                                'total_invested_eur': float(basis.invested_eur),
                                'timestamp': time.time(),
                                'opened_ts': float(basis.earliest_timestamp or time.time()),
                                'partial_tp_returned_eur': 0.0,
                                'dca_buys': 0,
                                'dca_events': [],
                                'score': 0.0,
                                'volatility_at_entry': 0.0,
                                'opened_regime': 'unknown',
                            }
                            open_state[market] = new_entry
                            changes_made = True
                            log(
                                f"Sync: AUTO-DISCOVERED {market} on Bitvavo — "
                                f"invested=€{basis.invested_eur:.2f}, amount={amount:.6f}",
                                level="warning",
                            )
                        else:
                            log(
                                f"Sync: {market} found on Bitvavo but derive_cost_basis "
                                f"returned no data — skipping auto-add",
                                level="warning",
                            )
                    except Exception as disc_err:
                        log(
                            f"Sync: auto-discover failed for {market}: {disc_err}",
                            level="warning",
                        )

        # retain only markets Bitvavo currently reports — but respect DISABLE_SYNC_REMOVE
        if not disable_sync_remove:
            filtered_state = {
                market: entry
                for market, entry in open_state.items()
                if market in open_markets and open_markets[market] > 0
            }
            removed_by_filter = set(open_state.keys()) - set(filtered_state.keys())
            if removed_by_filter:
                log(
                    f"Sync: filter verwijderde {len(removed_by_filter)} trades niet in API: "
                    f"{removed_by_filter}",
                    level="info",
                )
            open_state = filtered_state
        else:
            # DISABLE_SYNC_REMOVE=true: keep tracked trades even if API didn't return them
            missing_from_api = [m for m in open_state if m not in open_markets]
            if missing_from_api:
                log(
                    f"Sync: DISABLE_SYNC_REMOVE=true — behoud {len(missing_from_api)} "
                    f"trades niet in API response: {missing_from_api}",
                    level="warning",
                )

        # align amounts with live balances AND re-derive invested_eur when
        # amount changed (FIX #014: trading_sync updated amount without
        # recalculating invested_eur, causing invested_eur to go stale).
        for market, entry in open_state.items():
            live_amount = open_markets.get(market)
            if live_amount is None:
                continue
            try:
                current_amount = float(entry.get("amount", 0))
            except Exception:
                current_amount = 0.0
            if abs(current_amount - live_amount) > 1e-8:
                pct_change = abs(current_amount - live_amount) / max(current_amount, 1e-12)
                entry["amount"] = live_amount
                changes_made = True
                # If amount changed significantly (>0.1%), re-derive cost basis
                # so invested_eur stays accurate (see FIX_LOG #014).
                if pct_change > 0.001:
                    try:
                        from modules.cost_basis import derive_cost_basis
                        _basis = derive_cost_basis(
                            ctx.bitvavo, market, live_amount, tolerance=0.02
                        )
                        if _basis and getattr(_basis, "avg_price", 0) > 0:
                            old_inv = float(entry.get("invested_eur", 0) or 0)
                            entry["buy_price"] = float(_basis.avg_price)
                            entry["invested_eur"] = float(_basis.invested_eur)
                            entry["total_invested_eur"] = float(_basis.invested_eur)
                            if _basis.earliest_timestamp:
                                entry.setdefault("opened_ts", float(_basis.earliest_timestamp))
                            log(
                                f"Sync: amount changed for {market} "
                                f"({current_amount:.6f} → {live_amount:.6f}, "
                                f"{pct_change*100:.1f}%) — re-derived invested "
                                f"€{old_inv:.2f} → €{_basis.invested_eur:.2f}",
                                level="warning",
                            )
                    except Exception as deriv_err:
                        log(
                            f"Sync: derive_cost_basis failed for {market} "
                            f"after amount change: {deriv_err}",
                            level="error",
                        )

        if changes_made:
            data["open"] = open_state
            data["closed"] = closed_state
            data["profits"] = profit_state
            try:
                ctx.write_json_locked(trade_log_path, data, indent=2)
                log("Sync: trade_log.json bijgewerkt met actuele open trades.", level="info")
            except Exception as exc:
                log(
                    f"Sync: kon {trade_log_path} niet bijwerken: {exc}",
                    level="error",
                )

        return open_state, closed_state, profit_state

    # ------------------------------------------------------------------
    # Extended reconciliation (used during heavy recovery)
    # ------------------------------------------------------------------
    def reconcile_balances(
        self,
        open_trades: Dict[str, Dict[str, Any]],
        closed_trades: List[Dict[str, Any]],
    ) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
        """Replay the more elaborate reconciliation logic used in recovery."""

        ctx = self.ctx
        log = ctx.log
        safe_call = ctx.safe_call
        bitvavo = ctx.bitvavo

        try:
            balances = safe_call(bitvavo.balance, {}) or []
            markets = safe_call(bitvavo.markets, {}) or []
        except Exception as exc:  # pragma: no cover - network error path
            log(f"Sync: unexpected error: {exc}", level="error")
            return open_trades, closed_trades

        market_set = {
            m.get("market")
            for m in markets
            if isinstance(m, dict) and m.get("market")
        }

        # Filter out dust balances (< 0.0001) before saving - prevents log spam
        filtered_balances = []
        for b in balances:
            try:
                avail = float(b.get("available", 0) or 0)
                if avail >= 0.0001:  # Only keep non-dust balances
                    filtered_balances.append(b)
            except (ValueError, TypeError):
                pass

        # Dump filtered payloads for debugging
        try:
            ctx.write_json_locked(ctx.sync_raw_balances_path, filtered_balances, indent=2)
            ctx.write_json_locked(ctx.sync_raw_markets_path, markets, indent=2)
            log(
                "Sync: wrote raw balances to "
                f"{ctx.sync_raw_balances_path} and markets to {ctx.sync_raw_markets_path}",
                level="info",
            )
        except Exception as exc:
            log(f"Sync: failed to write raw debug files: {exc}", level="error")

        log(
            f"Sync: fetched {len(balances)} balances and {len(market_set)} markets from Bitvavo",
            level="info",
        )

        positive_balances: List[Dict[str, Any]] = []
        live_open: Dict[str, Dict[str, Any]] = {}
        for balance_entry in balances:
            symbol = balance_entry.get("symbol")
            if not symbol:
                continue
            market = f"{symbol}-EUR"
            try:
                amount = float(
                    balance_entry.get("available", 0)
                    or balance_entry.get("balance", 0)
                    or 0
                )
            except Exception:
                amount = 0.0
            if amount <= 0:
                continue
            positive_balances.append(
                {"symbol": symbol, "market": market, "amount": amount}
            )
            if market not in market_set:
                alt_candidates = [
                    f"{symbol}-USDC",
                    f"{symbol}-USDT",
                    f"{symbol}-BTC",
                ]
                for alt in alt_candidates:
                    if alt in market_set:
                        market = alt
                        break
                else:
                    log(
                        f"Sync: skipping {symbol} because {market} not in market_set",
                        level="debug",
                    )
                    continue
            tick = safe_call(bitvavo.tickerPrice, {"market": market})
            price: Optional[float]
            if tick and isinstance(tick, dict):
                try:
                    price = float(tick.get("price") or 0)
                except Exception:
                    price = None
            else:
                price = None
            # CRITICAL FIX: Do NOT use current ticker price for invested_eur!
            # Ticker price is NOT the historical buy price. Leave invested_eur
            # as None so cost_basis derivation fills it from actual order history.
            live_open[market] = {
                "buy_price": price,
                "highest_price": price,
                "amount": amount,
                "invested_eur": None,  # Will be derived from order history later
                "timestamp": time.time(),
                "tp_levels_done": [False, False],
                "dca_buys": 0,
                "dca_next_price": 0.0,
                "tp_last_time": 0.0,
            }

        try:
            ctx.write_json_locked(
                ctx.sync_debug_path,
                {
                    "positive_balances": positive_balances,
                    "market_set_size": len(market_set),
                },
                indent=2,
            )
            log(
                f"Sync: positive balances detected: {positive_balances}",
                level="info",
            )
        except Exception as exc:
            log(f"Failed to write {ctx.sync_debug_path}: {exc}", level="error")

        old_set = set(open_trades.keys())
        new_set = set(live_open.keys())
        to_add = new_set - old_set
        to_remove = old_set - new_set

        # --- DISABLE_SYNC_REMOVE guard (Bug fix: respect config flag) ---
        disable_sync_remove = ctx.config.get("DISABLE_SYNC_REMOVE", True)

        # API glitch protection: don't remove all trades if API returned empty
        if to_remove and not new_set and len(old_set) > 0:
            log(
                "Sync: API returned empty balances but we have open trades — "
                "skipping removal to prevent data loss",
                level="warning",
            )
            to_remove = set()

        if disable_sync_remove and to_remove:
            log(
                f"Sync: DISABLE_SYNC_REMOVE=true — skipping removal of "
                f"{len(to_remove)} trades: {to_remove}",
                level="warning",
            )
            to_remove = set()

        if not to_add and not to_remove:
            log(
                "Sync: no changes detected between Bitvavo and local open_trades",
                level="debug",
            )
            return open_trades, closed_trades

        with ctx.file_lock:
            cache_now = time.time()
            try:
                with open(ctx.sync_removed_cache_path, "r", encoding="utf-8") as cache_fh:
                    removed_cache = json.load(cache_fh)
                    if not isinstance(removed_cache, dict):
                        removed_cache = {}
            except Exception:
                removed_cache = {}

            if removed_cache:
                pruned_cache: Dict[str, Dict[str, Any]] = {}
                for key, payload in removed_cache.items():
                    if not isinstance(payload, dict):
                        continue
                    saved_ts = payload.get("saved_ts")
                    try:
                        saved_ts_val = float(saved_ts)
                    except (TypeError, ValueError):
                        saved_ts_val = 0.0
                    if saved_ts_val and (
                        cache_now - saved_ts_val
                    ) > ctx.sync_removed_cache_max_age:
                        continue
                    pruned_cache[key] = payload
                removed_cache = pruned_cache
            else:
                removed_cache = {}

            try:
                backup_path = ctx.trade_log_path + f".bak.{int(time.time())}"
                shutil.copy2(ctx.trade_log_path, backup_path)
                log(f"Sync: backup created {backup_path}", level="debug")
            except Exception:
                log(
                    "Sync: could not create backup (file may not exist yet)",
                    level="warning",
                )

            for market in to_add:
                entry = live_open.get(market)
                if not entry:
                    continue
                cache_entry = removed_cache.get(market)
                if isinstance(cache_entry, dict):
                    cached_ts = cache_entry.get("saved_ts")
                    try:
                        cached_ts_val = float(cached_ts)
                    except (TypeError, ValueError):
                        cached_ts_val = 0.0
                    if cached_ts_val and (
                        cache_now - cached_ts_val
                    ) <= ctx.sync_removed_cache_max_age:
                        cached_buys = cache_entry.get("dca_buys")
                        if isinstance(cached_buys, (int, float)):
                            entry.setdefault("dca_buys", int(cached_buys))
                        for price_key in ("dca_next_price", "last_dca_price"):
                            val = cache_entry.get(price_key)
                            if isinstance(val, (int, float)) and val > 0:
                                entry[price_key] = float(val)
                        tp_list = cache_entry.get("tp_levels_done")
                        if isinstance(tp_list, list):
                            entry["tp_levels_done"] = tp_list
                        tp_last_val = cache_entry.get("tp_last_time")
                        if isinstance(tp_last_val, (int, float)):
                            entry["tp_last_time"] = float(tp_last_val)
                        removed_cache.pop(market, None)
                open_trades[market] = entry
                # --- FIX #007b: enforce event-sourced DCA state after cache restore ---
                try:
                    from core.dca_state import sync_derived_fields
                    sync_derived_fields(entry)
                except Exception:
                    pass
                log(
                    f"Sync: added open trade {market} (amount={entry.get('amount')},"
                    f" price={entry.get('buy_price')})",
                    level="info",
                )

            timestamp = time.time()
            for market in to_remove:
                trade_entry = open_trades.get(market)
                if not trade_entry:
                    continue
                snapshot: Dict[str, Any] = {"saved_ts": time.time()}
                try:
                    # Use event count as source of truth for dca_buys in cache
                    events = trade_entry.get("dca_events")
                    if isinstance(events, list):
                        snapshot["dca_buys"] = len(events)
                    else:
                        snapshot["dca_buys"] = int(trade_entry.get("dca_buys", 0) or 0)
                except Exception:
                    snapshot["dca_buys"] = 0
                last_dca_price = trade_entry.get("last_dca_price")
                if isinstance(last_dca_price, (int, float)) and last_dca_price > 0:
                    snapshot["last_dca_price"] = float(last_dca_price)
                dca_next = trade_entry.get("dca_next_price")
                if isinstance(dca_next, (int, float)) and dca_next > 0:
                    snapshot["dca_next_price"] = float(dca_next)
                tp_list = trade_entry.get("tp_levels_done")
                if isinstance(tp_list, list):
                    snapshot["tp_levels_done"] = tp_list
                tp_last_time = trade_entry.get("tp_last_time")
                if isinstance(tp_last_time, (int, float)) and tp_last_time > 0:
                    snapshot["tp_last_time"] = float(tp_last_time)
                removed_cache[market] = snapshot
                # Calculate approximate profit instead of hardcoding -10.0
                _bp = float(trade_entry.get("buy_price") or 0)
                _amt = float(trade_entry.get("amount") or 0)
                _inv = float(trade_entry.get("invested_eur") or (_bp * _amt))
                _profit = -_inv if _inv > 0 else 0.0  # Assume total loss if removed
                closed_entry = {
                    "market": market,
                    "buy_price": _bp,
                    "sell_price": 0.0,
                    "amount": _amt,
                    "profit": _profit,
                    "invested_eur": _inv,
                    "timestamp": timestamp,
                    "reason": "sync_removed",
                }
                # Archive trade permanently
                if archive_trade:
                    try:
                        archive_trade(**closed_entry)
                    except Exception:
                        pass
                closed_trades.append(closed_entry)
                open_trades.pop(market, None)
                log(
                    f"Sync: removed open trade {market} and moved to closed_trades",
                    level="info",
                )

            cache_now = time.time()
            if removed_cache:
                cleaned_cache: Dict[str, Dict[str, Any]] = {}
                for key, payload in removed_cache.items():
                    if not isinstance(payload, dict):
                        continue
                    saved_ts = payload.get("saved_ts")
                    try:
                        saved_ts_val = float(saved_ts)
                    except (TypeError, ValueError):
                        saved_ts_val = cache_now
                    if (
                        cache_now - saved_ts_val
                    ) > ctx.sync_removed_cache_max_age:
                        continue
                    payload["saved_ts"] = saved_ts_val
                    cleaned_cache[key] = payload
                removed_cache = cleaned_cache
            try:
                ctx.write_json_locked(
                    ctx.sync_removed_cache_path, removed_cache, indent=2
                )
            except Exception as exc:
                log(
                    f"Sync: kon {ctx.sync_removed_cache_path} niet bijwerken: {exc}",
                    level="warning",
                )

            try:
                ctx.save_trades()
                log("Sync: changes persisted to trade_log.json", level="info")
            except Exception as exc:
                log(f"Sync: failed to persist changes: {exc}", level="error")

        return open_trades, closed_trades

    # ------------------------------------------------------------------
    # Background helpers
    # ------------------------------------------------------------------
    def start_auto_sync(
        self,
        state_provider: Callable[[], Tuple[
            Dict[str, Dict[str, Any]],
            List[Dict[str, Any]],
            Dict[str, float],
        ]],
        state_consumer: Callable[[
            Dict[str, Dict[str, Any]],
            List[Dict[str, Any]],
            Dict[str, float],
        ], None],
        *,
        interval: int = 60,
    ) -> threading.Thread:
        """Start a daemon thread that periodically synchronises trades."""

        def loop() -> None:
            # The loop consults ctx.config dynamically so the enable flag and interval
            # can be toggled at runtime via the shared CONFIG dict (hot-reload aware).
            current_sleep = max(5, int(interval or 60))
            while True:
                try:
                    # Read dynamic config values each iteration
                    try:
                        cfg_enabled = bool(self.ctx.config.get('SYNC_ENABLED', True))
                    except Exception:
                        cfg_enabled = True
                    try:
                        cfg_interval = int(self.ctx.config.get('SYNC_INTERVAL_SECONDS', interval) or interval)
                        cfg_interval = max(5, cfg_interval)
                    except Exception:
                        cfg_interval = max(5, int(interval or 60))

                    # If sync is disabled in config, skip syncing and sleep for the configured interval
                    if not cfg_enabled:
                        time.sleep(cfg_interval)
                        continue

                    current_open, current_closed, current_profits = state_provider()
                    new_open, new_closed, new_profits = self.sync_open_trades(
                        current_open, current_closed, current_profits
                    )
                    state_consumer(new_open, new_closed, new_profits)
                except Exception as exc:  # pragma: no cover - defensive shield
                    self.ctx.log(f"Auto-sync loop error: {exc}", level="error")
                # Sleep for the (possibly updated) configured interval
                try:
                    current_sleep = int(self.ctx.config.get('SYNC_INTERVAL_SECONDS', interval) or interval)
                except Exception:
                    current_sleep = max(5, int(interval or 60))
                time.sleep(max(5, current_sleep))

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        return thread
