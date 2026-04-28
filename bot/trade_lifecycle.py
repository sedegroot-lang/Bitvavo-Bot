# -*- coding: utf-8 -*-
"""Trade persistence: save_trades, load_trades, cleanup_trades, quarantine.

Extracted from trailing_bot.py to reduce monolith size.
All shared state accessed via ``bot.shared.state``.
"""
from __future__ import annotations

import json
import os
import threading
import time


def _get_state():
    from bot.shared import state
    return state


# ── Module-local state (only used by save_trades) ──────────────────
_SAVE_TRADES_LOCK = threading.Lock()
_SAVE_TRADES_DEBOUNCE_TS = 0.0
_SAVE_TRADES_MIN_INTERVAL = 2.0  # seconds


# ─── save_trades ────────────────────────────────────────────────────

def save_trades(force: bool = False):
    """Save trades with debouncing to prevent excessive writes and file corruption."""
    global _SAVE_TRADES_DEBOUNCE_TS

    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    open_trades = S.open_trades
    closed_trades = S.closed_trades
    market_profits = S.market_profits
    trades_lock = S.trades_lock
    TRADE_LOG = S.TRADE_LOG
    ARCHIVE_FILE = S.ARCHIVE_FILE
    MAX_CLOSED = S.MAX_CLOSED
    write_json_locked = S.write_json_locked

    now = time.time()

    # FIX #4: Debounce rapid saves (unless forced)
    if not force and (now - _SAVE_TRADES_DEBOUNCE_TS) < _SAVE_TRADES_MIN_INTERVAL:
        return  # Skip this save, too soon since last one

    # FIX #4: Global lock to prevent concurrent writes
    with _SAVE_TRADES_LOCK:
        _SAVE_TRADES_DEBOUNCE_TS = now

        # Automatische parameter optimizer
        all_trades = []
        if closed_trades:
            all_trades = closed_trades.copy()
        try:
            with open(ARCHIVE_FILE, 'r') as f:
                archive = json.load(f)
            if isinstance(archive, dict) and 'trades' in archive:
                all_trades += archive['trades']
            elif isinstance(archive, list):
                all_trades += archive
        except Exception as arc_err:
            log(f"[WARNING] Kon trade archive niet laden: {arc_err}", level='warning')
        S.optimize_parameters(all_trades)

    # reconcile pending saldo_error entries before analysis
    pending_file = 'data/pending_saldo.json'
    pending = []
    try:
        if os.path.exists(pending_file):
            with open(pending_file, 'r', encoding='utf-8') as pf:
                pending = json.load(pf)
    except Exception:
        pending = []

    # Filter out immediate saldo_error entries from closed_trades.
    # FIX_LOG #013: only treat RECENT saldo_errors (<48h) as pending.
    # Old archived saldo_errors (months old) were re-detected every cycle,
    # blowing up pending_saldo.json count and triggering Saldo Guard
    # which cancelled DCA buy orders. Stale entries must be ignored.
    saldo_recent_window_s = float((CONFIG.get('SALDO_GUARD') or {}).get('pending_max_age_hours', 48)) * 3600.0
    cutoff_ts = time.time() - saldo_recent_window_s
    new_closed = []
    for t in all_trades:
        if not isinstance(t, dict):
            log(f"Skipping unexpected trade record type {type(t)}: {t}", level='warning')
            continue
        if t.get('reason') == 'saldo_error' and float(t.get('sell_price', 0) or 0) == 0.0:
            ts = float(t.get('timestamp') or t.get('opened_ts') or 0)
            if ts >= cutoff_ts:
                pending.append(t)
                log(f"Detected saldo_error for {t.get('market')}, storing pending for reconciliation", level='warning')
            else:
                # stale: drop silently from closed list, do not re-pend
                pass
        else:
            new_closed.append(t)

    # write back pending list (keep limited size)
    try:
        S.json_write_compat(pending_file, pending[-200:], indent=2)
    except Exception as pend_err:
        log(f"[ERROR] Kon pending saldo reconciliation niet schrijven: {pend_err}", level='error')

    from bot.portfolio import analyse_trades
    win_ratio, avg_win, avg_loss, avg_profit = analyse_trades(new_closed)
    log(f"Trade analyse: win ratio={win_ratio:.2f}, avg win={avg_win:.2f}, avg loss={avg_loss:.2f}, avg profit={avg_profit:.2f}")
    with trades_lock:
        data = {"open": dict(open_trades), "closed": list(closed_trades), "profits": dict(market_profits)}
    try:
        S.save_trade_snapshot(data, TRADE_LOG, indent=2)
    except OSError as e:
        log(f"Kon {TRADE_LOG} niet opslaan: {e}")
    S.cleanup_trades()
    # Force immediate heartbeat update after trade cleanup
    try:
        current_time = time.time()
        ai_active = False
        try:
            ai_hb_file = S.AI_HEARTBEAT_FILE
            if os.path.exists(ai_hb_file):
                with open(ai_hb_file, 'r') as f:
                    ai_hb = json.load(f)
                    ai_last = ai_hb.get('last_seen', 0)
                    ai_active = (current_time - ai_last) < 300
        except Exception as e:
            log(f"exists failed: {e}", level='warning')

        from bot.portfolio import count_active_open_trades, count_dust_trades
        with open(S.HEARTBEAT_FILE, "w", encoding="utf-8") as hb:
            json.dump({
                "ts": current_time,
                "timestamp": current_time,
                "open_trades": count_active_open_trades(threshold=S.DUST_TRADE_THRESHOLD_EUR),
                "open_trades_including_dust": len(open_trades),
                "dust_trade_count": count_dust_trades(),
                "eur_balance": CONFIG.get("EUR_BALANCE", 0),
                "max_eur_per_trade": CONFIG.get("MAX_EUR_PER_TRADE", 0),
                "max_total_eur": CONFIG.get("MAX_TOTAL_EUR", 0),
                "open_exposure_eur": CONFIG.get("OPEN_EXPOSURE_EUR", 0),
                "pending_reservations": S._get_pending_count(),
                "ai_active": ai_active,
                "bot_active": True,
                "last_scan_stats": CONFIG.get("LAST_SCAN_STATS", {}),
            }, hb, indent=2)
    except Exception as hb_err:
        log(f"[ERROR] Heartbeat schrijven mislukt: {hb_err}", level='error')

    # --- Reinvest logic ---
    try:
        if S.REINVEST_ENABLED:
            last_ts = CONFIG.get('LAST_REINVEST_TS', 0)
            valid_trades = [t for t in all_trades if isinstance(t, dict)]
            recent_trades = [t for t in valid_trades if t.get('timestamp', 0) > last_ts]
            recent_profit = sum(t.get('profit', 0) for t in recent_trades)
            recent_count = len(recent_trades)
            if recent_count >= S.REINVEST_MIN_TRADES and recent_profit >= S.REINVEST_MIN_PROFIT:
                proposed_add = recent_profit * S.REINVEST_PORTION
                max_add = S.BASE_AMOUNT_EUR * S.REINVEST_MAX_INCREASE_PCT
                add = min(proposed_add, max_add)
                new_base = min(S.BASE_AMOUNT_EUR + add, S.REINVEST_CAP)
                if new_base > S.BASE_AMOUNT_EUR:
                    old = CONFIG.get('BASE_AMOUNT_EUR', S.BASE_AMOUNT_EUR)
                    CONFIG['BASE_AMOUNT_EUR'] = round(new_base, 2)
                    CONFIG['LAST_REINVEST_TS'] = int(time.time())
                    log(f"Reinvest: toegevoegd {add:.2f} EUR aan BASE_AMOUNT_EUR (van {old} -> {CONFIG['BASE_AMOUNT_EUR']}) op basis van winst {recent_profit:.2f} over {recent_count} trades")
            else:
                log(f"Reinvest: voorwaarden niet gehaald (trades={recent_count}, profit={recent_profit:.2f})")
    except Exception as e:
        log(f"Reinvest logic faalde: {e}", level='error')

    # Save config
    try:
        from modules.config import save_config as _save_cfg
        _save_cfg(CONFIG)
    except Exception as e:
        log(f"Kon config niet opslaan: {e}", level='error')

    # Archive closed trades with duplicate check
    if len(closed_trades) > MAX_CLOSED:
        try:
            with open(ARCHIVE_FILE, 'r') as f:
                archive_data = json.load(f)
            if isinstance(archive_data, dict) and 'trades' in archive_data:
                archive = archive_data['trades']
            elif isinstance(archive_data, list):
                archive = archive_data
            else:
                archive = []
        except Exception:
            archive = []

        def trade_key(t):
            return (t.get('market'), t.get('buy_price'), t.get('sell_price'), t.get('amount'), t.get('timestamp'))

        archive_keys = set(trade_key(t) for t in archive if isinstance(t, dict))
        new_trades = [t for t in closed_trades[:MAX_CLOSED] if isinstance(t, dict) and trade_key(t) not in archive_keys]
        if len(new_trades) < len(closed_trades[:MAX_CLOSED]):
            log(f"Archivering: {len(closed_trades[:MAX_CLOSED]) - len(new_trades)} dubbele trades niet toegevoegd.")
        archive += new_trades
        archive_output = {"trades": archive, "metadata": {"last_updated": time.time()}}
        write_json_locked(ARCHIVE_FILE, archive_output, indent=2)
        del closed_trades[:MAX_CLOSED]
    S.cleanup_trades()
    try:
        if S.risk_manager:
            S.risk_manager.refresh(force=True)
    except Exception as exc:
        log(f"Risk manager refresh mislukt na save_trades: {exc}", level='warning')


# ─── load_trades ────────────────────────────────────────────────────

def load_trades():
    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    open_trades = S.open_trades
    closed_trades = S.closed_trades
    market_profits = S.market_profits
    trades_lock = S.trades_lock
    TRADE_LOG = S.TRADE_LOG

    try:
        data = S.load_trade_snapshot(TRADE_LOG)
    except Exception as e:
        log(f"Kon {TRADE_LOG} niet laden: {e}")
        data = {}
    new_open = data.get("open", {}) if isinstance(data, dict) else {}
    new_closed = data.get("closed", []) if isinstance(data, dict) else []
    new_profits = data.get("profits", {}) if isinstance(data, dict) else {}
    with trades_lock:
        open_trades.clear()
        open_trades.update(new_open)
        closed_trades.clear()
        closed_trades.extend(new_closed)
        market_profits.clear()
        market_profits.update(new_profits)

    # Remove HODL assets from open_trades
    try:
        hodl_cfg = CONFIG.get('HODL_SCHEDULER') or {}
        hodl_markets = set()
        for sched in (hodl_cfg.get('schedules') or []):
            market = sched.get('market', '')
            if market:
                hodl_markets.add(market.upper())
        if hodl_markets:
            removed = []
            for m in list(open_trades.keys()):
                if m.upper() in hodl_markets:
                    del open_trades[m]
                    removed.append(m)
            if removed:
                log(f"HODL assets verwijderd uit open_trades (beheerd door HODL scheduler): {removed}", level='info')
                save_trades()
    except Exception as e:
        log(f"Fout bij verwijderen HODL assets uit open_trades: {e}", level='warning')

    # --- STARTUP BUY_PRICE VALIDATION ---
    try:
        _validation_fixes = 0
        for _vm, _vt in list(open_trades.items()):
            _vbp = float(_vt.get('buy_price', 0) or 0)
            _vamt = float(_vt.get('amount', 0) or 0)
            if _vbp <= 0 or _vamt <= 0:
                continue
            try:
                _vticker = S.safe_call(S.bitvavo.tickerPrice, {'market': _vm})
                _vticker_p = float(_vticker.get('price', 0)) if isinstance(_vticker, dict) else 0
                if _vticker_p <= 0:
                    continue
                _vdev = abs(_vbp - _vticker_p) / _vticker_p
                if _vdev > 0.50:
                    log(f"⚠️ STARTUP VALIDATION: {_vm} buy_price €{_vbp:.6f} deviates {_vdev*100:.1f}% from ticker €{_vticker_p:.6f}. Re-deriving.", level='warning')
                    try:
                        _vbasis = S.derive_cost_basis(S.bitvavo, _vm, _vamt, tolerance=0.05)
                        if _vbasis and getattr(_vbasis, 'avg_price', 0) > 0:
                            _old_bp = _vbp
                            _vt['buy_price'] = float(_vbasis.avg_price)
                            _vt['invested_eur'] = float(_vbasis.invested_eur)
                            _vt['initial_invested_eur'] = float(_vbasis.invested_eur)
                            _vt['total_invested_eur'] = float(_vbasis.invested_eur)
                            if hasattr(_vbasis, 'earliest_timestamp') and _vbasis.earliest_timestamp:
                                _vt['opened_ts'] = float(_vbasis.earliest_timestamp)
                            _vt['dca_buys'] = 0
                            _vt['dca_events'] = []
                            _validation_fixes += 1
                            log(f"✅ STARTUP FIX {_vm}: buy_price €{_old_bp:.6f} → €{_vt['buy_price']:.6f}", level='warning')
                    except Exception as _vderr:
                        log(f"⚠️ STARTUP derive failed for {_vm}: {_vderr}", level='error')
            except Exception as _vtick_err:
                log(f"Startup validation ticker fetch failed for {_vm}: {_vtick_err}", level='debug')
        if _validation_fixes > 0:
            log(f"✅ STARTUP VALIDATION: Fixed {_validation_fixes} stale buy_prices", level='warning')
            save_trades()
    except Exception as _val_err:
        log(f"Startup buy_price validation failed: {_val_err}", level='warning')

    try:
        S.load_market_performance()
    except Exception as exc:
        log(f"Kon market_metrics niet herladen: {exc}", level='warning')
    try:
        if S.risk_manager:
            S.risk_manager.refresh(force=True)
    except Exception as exc:
        log(f"Risk manager refresh mislukt na load_trades: {exc}", level='warning')


# ─── load_saldo_quarantine ──────────────────────────────────────────

def load_saldo_quarantine():
    """Return a set of markets that exceeded SALDO_QUARANTINE_THRESHOLD within window days."""
    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    TRADE_LOG = S.TRADE_LOG
    try:
        if not CONFIG.get('SALDO_QUARANTINE_ENABLED'):
            return set()
        thresh = int(CONFIG.get('SALDO_QUARANTINE_THRESHOLD', 2))
        window_days = int(CONFIG.get('SALDO_QUARANTINE_WINDOW_DAYS', 14))
        cutoff = time.time() - window_days * 24 * 3600
        counts = {}
        # pending
        try:
            if os.path.exists('data/pending_saldo.json'):
                with open('data/pending_saldo.json', 'r', encoding='utf-8') as pf:
                    pend = json.load(pf)
                for t in pend:
                    if t.get('reason') == 'saldo_error' and t.get('timestamp', 0) >= cutoff:
                        counts[t.get('market')] = counts.get(t.get('market'), 0) + 1
        except Exception as e:
            log(f"[ERROR] Quarantine pending saldo load failed: {e}", level='error')
        # recent closed
        try:
            data = S.load_trade_snapshot(TRADE_LOG)
            for t in data.get('closed', [])[-2000:]:
                if t.get('reason') == 'saldo_error' and t.get('timestamp', 0) >= cutoff:
                    counts[t.get('market')] = counts.get(t.get('market'), 0) + 1
        except Exception as e:
            log(f"[ERROR] Quarantine closed trades load failed: {e}", level='error')
        return set(m for m, c in counts.items() if c >= thresh)
    except Exception:
        return set()


# ─── cleanup_trades ─────────────────────────────────────────────────

def cleanup_trades():
    S = _get_state()
    log = S.log
    closed_trades = S.closed_trades
    trades_lock = S.trades_lock
    MAX_CLOSED = S.MAX_CLOSED
    ARCHIVE_FILE = S.ARCHIVE_FILE

    with trades_lock:
        if len(closed_trades) > MAX_CLOSED:
            old = closed_trades[:-MAX_CLOSED]
            closed_trades[:] = closed_trades[-MAX_CLOSED:]
            if os.path.exists(ARCHIVE_FILE):
                with open(ARCHIVE_FILE) as f:
                    archive = json.load(f)
            else:
                archive = []
            archive.extend(old)
            S.write_json_locked(ARCHIVE_FILE, archive, indent=2)
            log(f"🗑️ {len(old)} oude trades verplaatst naar {ARCHIVE_FILE}")
