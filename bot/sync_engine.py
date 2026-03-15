# -*- coding: utf-8 -*-
"""Bitvavo balance/position sync engine.

Extracted from trailing_bot.py to reduce monolith size.
All shared state accessed via ``bot.shared.state``.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, List, Optional


def _get_state():
    from bot.shared import state
    return state


def sync_with_bitvavo():
    """Safe sync: fetch balances from Bitvavo and reconcile in-memory open_trades.

    Only writes trade_log.json when changes are detected.
    """
    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    open_trades = S.open_trades
    trades_lock = S.trades_lock
    bitvavo = S.bitvavo
    safe_call = S.safe_call

    try:
        balances = S.sanitize_balance_payload(safe_call(bitvavo.balance, {}), source='sync_with_bitvavo.balance')
        markets = safe_call(bitvavo.markets, {}) or []
        market_set = set(m.get('market') for m in markets if m.get('market'))

        # Write raw debug dumps
        try:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            # Go up one level from bot/ to project root
            project_root = os.path.dirname(base_dir)
            dbg_bal = os.path.join(project_root, 'data', 'sync_raw_balances.json')
            dbg_mark = os.path.join(project_root, 'data', 'sync_raw_markets.json')
            S.json_write_compat(dbg_bal, balances, indent=2)
            S.json_write_compat(dbg_mark, markets, indent=2)
            log(f"Sync: wrote raw balances to {dbg_bal} and markets to {dbg_mark}", level='info')
        except Exception as e:
            log(f"Sync: failed to write raw debug files: {e}", level='error')

        log(f"Sync: fetched {len(balances)} balances and {len(market_set)} markets from Bitvavo", level='info')

        # Collect positive balances and build live snapshot
        positive_balances = []
        hodl_markets = set()
        try:
            hodl_cfg = CONFIG.get('HODL_SCHEDULER') or {}
            for sched in (hodl_cfg.get('schedules') or []):
                market = sched.get('market', '')
                if market:
                    hodl_markets.add(market.upper())
            if hodl_markets:
                log(f"Sync: excluding HODL markets from trailing: {hodl_markets}", level='info')
        except Exception as e:
            log(f"Sync: failed to load HODL markets: {e}", level='warning')

        DCA_MAX_BUYS = int(CONFIG.get('DCA_MAX_BUYS', 3))
        DCA_DROP_PCT = float(CONFIG.get('DCA_DROP_PCT', 0.05))

        live_open = {}
        for b in balances:
            symbol = b.get('symbol')
            if not symbol:
                continue
            if symbol.upper() == 'EUR':
                continue
            market = f"{symbol}-EUR"

            if market.upper() in hodl_markets:
                log(f"Sync: skipping HODL asset {market} (managed by HODL scheduler)", level='info')
                continue

            try:
                amount = float(b.get('available', 0) or b.get('balance', 0) or 0)
            except Exception:
                amount = 0
            if amount <= 0:
                continue
            positive_balances.append({'symbol': symbol, 'market': market, 'amount': amount})
            if market not in market_set:
                alt_candidates = [f"{symbol}-USDC", f"{symbol}-USDT", f"{symbol}-BTC"]
                for alt in alt_candidates:
                    if alt in market_set:
                        market = alt
                        break
            tick = safe_call(bitvavo.tickerPrice, {'market': market})
            price = None
            if tick and isinstance(tick, dict):
                try:
                    price = float(tick.get('price') or 0)
                except Exception:
                    price = None

            # Skip dust balances: positions below minimum EUR value are not tradeable
            dust_threshold = float(CONFIG.get('SYNC_DUST_VALUE_EUR', 5.0))
            position_value = (price or 0) * amount
            if price and position_value < dust_threshold:
                log(
                    f"Sync: {market} balance {amount:.6f} (≈€{position_value:.2f}) is below "
                    f"dust threshold (€{dust_threshold:.0f}) — skipping to avoid phantom trade loop.",
                    level='info',
                )
                continue

            live_open[market] = {
                'buy_price': price,
                'highest_price': price,
                'amount': amount,
                'timestamp': time.time(),
                'tp_levels_done': [False, False, False],
                'partial_tp_events': [],
                'dca_buys': 0,
                'dca_max': int(DCA_MAX_BUYS),
                'dca_next_price': 0.0,
                'tp_last_time': 0.0
            }

        # Persist debug summary
        try:
            S.json_write_compat('data/sync_debug.json', {
                'positive_balances': positive_balances,
                'market_set_size': len(market_set),
                'mapped_open_markets': [[m, v['amount']] for m, v in live_open.items()]
            }, indent=2)
            log(f"Sync: positive balances detected: {positive_balances}", level='info')
        except Exception as e:
            log(f"Failed to write sync_debug.json: {e}", level='error')

        log(f"Bitvavo mapped_open_markets: {list(live_open.keys())}", level='info')

        pre_sync_count = len(open_trades)
        live_count = len(live_open)
        if pre_sync_count == 0 and live_count > 0:
            log(f"🔴 CRITICAL: open_trades is EMPTY but Bitvavo has {live_count} positions! "
                f"Recovery mode: ALL positions will be restored to prevent ghost positions.",
                level='error')

        changes_made = False
        with trades_lock:
            for m, entry in live_open.items():
                if m in open_trades:
                    local = open_trades.get(m, {})
                    old_amount = float(local.get('amount') or 0)
                    new_amount = float(entry.get('amount') or 0)
                    local['amount'] = new_amount
                    if not local.get('buy_price') and entry.get('buy_price') is not None:
                        local['buy_price'] = entry.get('buy_price')

                    # STALE BUY_PRICE DETECTION
                    try:
                        _stored_bp = float(local.get('buy_price') or 0)
                        if _stored_bp > 0 and new_amount > 0:
                            _ticker = safe_call(bitvavo.tickerPrice, {'market': m})
                            _ticker_price = float(_ticker.get('price', 0)) if isinstance(_ticker, dict) else 0
                            if _ticker_price > 0:
                                _deviation = abs(_stored_bp - _ticker_price) / _ticker_price
                                if _deviation > 0.50:
                                    log(f"⚠️ STALE BUY_PRICE detected for {m}: stored €{_stored_bp:.6f} vs ticker €{_ticker_price:.6f} (deviation {_deviation*100:.1f}%). Re-deriving from order history.", level='warning')
                                    try:
                                        _fresh_basis = S.derive_cost_basis(bitvavo, m, new_amount, tolerance=0.05)
                                        if _fresh_basis and getattr(_fresh_basis, 'avg_price', 0) > 0:
                                            _new_bp = float(_fresh_basis.avg_price)
                                            _new_inv = float(_fresh_basis.invested_eur)
                                            log(f"✅ STALE FIX {m}: buy_price €{_stored_bp:.6f} → €{_new_bp:.6f}, invested €{_new_inv:.2f}", level='warning')
                                            local['buy_price'] = _new_bp
                                            local['invested_eur'] = _new_inv
                                            local['initial_invested_eur'] = _new_inv
                                            local['total_invested_eur'] = _new_inv
                                            if hasattr(_fresh_basis, 'earliest_timestamp') and _fresh_basis.earliest_timestamp:
                                                local['opened_ts'] = float(_fresh_basis.earliest_timestamp)
                                            # Preserve existing DCA history — only reset if truly empty
                                            if not local.get('dca_events'):
                                                local.setdefault('dca_buys', 0)
                                                local.setdefault('dca_events', [])
                                        else:
                                            log(f"⚠️ STALE FIX {m}: derive failed, using ticker €{_ticker_price:.6f} as buy_price", level='warning')
                                            local['buy_price'] = _ticker_price
                                            _fallback_inv = round(_ticker_price * new_amount, 4)
                                            local['invested_eur'] = _fallback_inv
                                            # Only set initial if not already set (preserve DCA history)
                                            if not local.get('initial_invested_eur'):
                                                local['initial_invested_eur'] = _fallback_inv
                                            local['total_invested_eur'] = _fallback_inv
                                    except Exception as _stale_err:
                                        log(f"⚠️ STALE FIX {m} failed: {_stale_err}", level='error')
                    except Exception as _stale_check_err:
                        log(f"Stale buy_price check failed for {m}: {_stale_check_err}", level='debug')

                    # Recalculate invested_eur when amount changes
                    try:
                        buy_p = float(local.get('buy_price') or 0)
                        old_invested = float(local.get('invested_eur') or 0)
                        if buy_p > 0 and new_amount > 0:
                            correct_invested = round(buy_p * new_amount, 4)
                            if old_invested > 0 and abs(correct_invested - old_invested) / old_invested > 0.20:
                                log(f"Sync: FIXING invested_eur for {m}: {old_invested:.2f} -> {correct_invested:.2f}", level='warning')
                                local['invested_eur'] = correct_invested
                                local['total_invested_eur'] = correct_invested
                                # NEVER overwrite initial_invested_eur if DCA history exists
                                # When DCAs are done, initial != current is expected
                                init_inv = float(local.get('initial_invested_eur') or 0)
                                has_dca_history = int(local.get('dca_buys', 0) or 0) > 0 or len(local.get('dca_events', []) or []) > 0
                                if not has_dca_history and init_inv > 0 and abs(correct_invested - init_inv) / init_inv > 0.20:
                                    local['initial_invested_eur'] = correct_invested
                    except Exception as sync_inv_err:
                        log(f"Sync: invested_eur recalc failed for {m}: {sync_inv_err}", level='debug')

                    try:
                        if entry.get('highest_price') and (local.get('highest_price') is None or entry.get('highest_price') > local.get('highest_price')):
                            local['highest_price'] = entry.get('highest_price')
                    except Exception:
                        local['highest_price'] = entry.get('highest_price')
                    local['timestamp'] = time.time()
                    local.setdefault('tp_levels_done', [False, False, False])
                    local.setdefault('dca_buys', 0)
                    local.setdefault('dca_events', [])
                    local.setdefault('partial_tp_returned_eur', 0.0)
                    local.setdefault('partial_tp_events', [])
                    # Ensure critical trailing/DCA config fields exist with config defaults
                    local.setdefault('trailing_activation_pct', float(CONFIG.get('TRAILING_ACTIVATION_PCT', 0.015)))
                    local.setdefault('base_trailing_pct', float(CONFIG.get('DEFAULT_TRAILING', 0.025)))
                    local.setdefault('cost_buffer_pct', float(CONFIG.get('FEE_TAKER', 0.0025)) * 2 + float(CONFIG.get('SLIPPAGE_PCT', 0.001)))
                    local.setdefault('dca_drop_pct', float(CONFIG.get('DCA_DROP_PCT', 0.05)))
                    local.setdefault('dca_amount_eur', float(CONFIG.get('DCA_AMOUNT_EUR', 30)))
                    local.setdefault('dca_step_mult', float(CONFIG.get('DCA_STEP_MULTIPLIER', 1.0)))
                    local.setdefault('score', 0.0)
                    local.setdefault('volatility_at_entry', 0.0)
                    local.setdefault('opened_regime', 'unknown')

                    if 'dca_max' not in local:
                        try:
                            inferred_max = None
                            if 'basis' in dir() and basis and getattr(basis, 'buy_order_count', None) is not None:
                                inferred_max = int(getattr(basis, 'buy_order_count') or 0)
                        except Exception:
                            inferred_max = None
                        try:
                            if inferred_max and inferred_max > 0:
                                local['dca_max'] = max(inferred_max, int(local.get('dca_buys', 0) or 0))
                            else:
                                local['dca_max'] = max(int(DCA_MAX_BUYS), int(local.get('dca_buys', 0) or 0))
                        except Exception:
                            local['dca_max'] = int(DCA_MAX_BUYS)

                    try:
                        existing_next = local.get('dca_next_price')
                        local_drop = float(local.get('dca_drop_pct', DCA_DROP_PCT))
                        base_price = float(local.get('buy_price') or entry.get('buy_price') or entry.get('highest_price') or 0.0)
                        if not existing_next or existing_next <= 0:
                            local['dca_next_price'] = base_price * (1 - local_drop)
                    except Exception:
                        local['dca_next_price'] = float(local.get('buy_price') or entry.get('buy_price') or 0.0)

                    try:
                        existing_last = local.get('last_dca_price')
                        if not existing_last:
                            local['last_dca_price'] = float(local.get('buy_price') or entry.get('buy_price') or 0.0)
                    except Exception:
                        local.setdefault('last_dca_price', local.get('buy_price'))

                    local.setdefault('trailing_activated', False)
                    local.setdefault('activation_price', None)
                    local.setdefault('highest_since_activation', None)

                    # Derive cost basis for NEW trades without initial_invested_eur
                    initial_inv = float(local.get('initial_invested_eur', 0) or 0)
                    basis = None
                    if initial_inv <= 0:
                        try:
                            from core.trade_investment import set_initial as _ti_set_initial
                            basis = S.derive_cost_basis(bitvavo, m, float(entry.get('amount') or 0.0), tolerance=0.02)
                            if basis and getattr(basis, 'avg_price', 0) > 0:
                                local['buy_price'] = float(basis.avg_price)
                                _ti_set_initial(local, float(basis.invested_eur), source="sync_derive_existing")
                                local['opened_ts'] = float(basis.earliest_timestamp or local.get('opened_ts'))
                                local['dca_buys'] = 0
                                local['dca_events'] = []
                                log(f"Sync: Derived initial values for NEW trade {m}: invested=€{basis.invested_eur:.2f}", level='info')
                        except Exception as e:
                            log(f"Sync: Failed to derive cost basis for {m}: {e}", level='warning')
                    elif not local.get('buy_price') or float(local.get('buy_price', 0)) <= 0:
                        try:
                            basis = S.derive_cost_basis(bitvavo, m, float(entry.get('amount') or 0.0), tolerance=0.02)
                            if basis and getattr(basis, 'avg_price', 0) > 0:
                                local['buy_price'] = float(basis.avg_price)
                        except Exception as e:
                            log(f"derive_cost_basis failed: {e}", level='error')

                    try:
                        local['highest_price'] = max(float(local.get('highest_price') or 0.0), float(local.get('buy_price') or 0.0))
                    except Exception as e:
                        log(f"local update failed: {e}", level='error')

                    open_trades[m] = local
                    changes_made = True
                else:
                    # New live balance not yet tracked
                    try:
                        new_local = {
                            'market': m,
                            'buy_price': entry.get('buy_price'),
                            'highest_price': entry.get('highest_price'),
                            'amount': entry.get('amount'),
                            'timestamp': time.time(),
                            'tp_levels_done': entry.get('tp_levels_done', [False, False, False]),
                            'partial_tp_events': entry.get('partial_tp_events', []),
                            'partial_tp_returned_eur': 0.0,
                            'dca_buys': 0,
                            'dca_events': [],
                            'dca_max': int(DCA_MAX_BUYS),
                            'dca_next_price': entry.get('dca_next_price', 0.0),
                            'dca_drop_pct': float(CONFIG.get('DCA_DROP_PCT', 0.05)),
                            'dca_amount_eur': float(CONFIG.get('DCA_AMOUNT_EUR', 30)),
                            'dca_step_mult': float(CONFIG.get('DCA_STEP_MULTIPLIER', 1.0)),
                            'tp_last_time': entry.get('tp_last_time', 0.0),
                            'trailing_activation_pct': float(CONFIG.get('TRAILING_ACTIVATION_PCT', 0.015)),
                            'base_trailing_pct': float(CONFIG.get('DEFAULT_TRAILING', 0.025)),
                            'cost_buffer_pct': float(CONFIG.get('FEE_TAKER', 0.0025)) * 2 + float(CONFIG.get('SLIPPAGE_PCT', 0.001)),
                            'score': 0.0,
                            'volatility_at_entry': 0.0,
                            'opened_regime': 'unknown',
                        }
                    except Exception:
                        new_local = {'market': m, 'buy_price': entry.get('buy_price'), 'amount': entry.get('amount', 0.0), 'dca_buys': 0, 'dca_events': [], 'partial_tp_returned_eur': 0.0}

                    try:
                        from core.trade_investment import set_initial as _ti_set_initial
                        basis = S.derive_cost_basis(bitvavo, m, float(entry.get('amount') or 0.0), tolerance=0.02)
                        if basis and getattr(basis, 'avg_price', 0) > 0:
                            new_local['buy_price'] = float(basis.avg_price)
                            _ti_set_initial(new_local, float(basis.invested_eur), source="sync_new_trade")
                            new_local['opened_ts'] = float(basis.earliest_timestamp or time.time())
                            log(f"Sync: NEW trade {m} detected with invested=€{basis.invested_eur:.2f}", level='info')
                    except Exception as e:
                        log(f"Sync: Failed to derive cost basis for new trade {m}: {e}", level='warning')

                    try:
                        new_local['highest_price'] = max(float(new_local.get('highest_price') or 0.0), float(new_local.get('buy_price') or 0.0))
                    except Exception as hp_err:
                        log(f"[ERROR] highest_price init mislukt voor {m}: {hp_err}", level='error')
                        new_local['highest_price'] = new_local.get('buy_price', 0.0)

                    new_local.setdefault('trailing_activated', False)
                    new_local.setdefault('activation_price', None)
                    new_local.setdefault('highest_since_activation', None)

                    max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
                    current_count = len(open_trades)
                    if current_count >= max_trades:
                        log(f"⚠️ SYNC OVER LIMIT: Adding {m} ({current_count+1}/{max_trades}) — "
                            f"position exists on Bitvavo, MUST track for proper management.",
                            level='warning')

                    open_trades[m] = new_local
                    changes_made = True

            # Remove local trades no longer on Bitvavo (if enabled)
            disable_sync_remove = CONFIG.get('DISABLE_SYNC_REMOVE', True)
            if not disable_sync_remove:
                closed_trades = S.closed_trades
                for m in list(open_trades.keys()):
                    if m not in live_open:
                        t = open_trades.get(m)
                        try:
                            closed_entry = {
                                'market': m,
                                'buy_price': t.get('buy_price', 0.0) if isinstance(t, dict) else 0.0,
                                'buy_order_id': t.get('buy_order_id') if isinstance(t, dict) else None,
                                'sell_price': 0.0,
                                'sell_order_id': None,
                                'amount': t.get('amount', 0.0) if isinstance(t, dict) else 0.0,
                                'profit': -t.get('buy_price', 0.0) * t.get('amount', 0.0) if isinstance(t, dict) and t.get('buy_price') else 0.0,
                                'timestamp': time.time(),
                                'reason': 'sync_removed',
                                'bitvavo_balance': None,
                                'open_trade': t,
                            }
                            S.archive_trade(**closed_entry)
                            closed_trades.append(closed_entry)
                            S._record_market_stats_for_close(m, closed_entry, t)
                        except Exception as arc_err:
                            log(f"[CRITICAL] Failed to archive sync_removed trade {m}: {arc_err}", level='error')
                        try:
                            del open_trades[m]
                        except Exception as del_err:
                            log(f"[ERROR] Failed to delete stale trade {m}: {del_err}", level='error')
                        changes_made = True

            if changes_made:
                try:
                    S.save_trades_fn()
                    log('Sync: changes persisted to trade_log.json', level='info')
                except Exception as e:
                    log(f'Sync: failed to persist changes: {e}', level='error')

        log(f"Na sync open_trades: {list(open_trades.keys())}", level='info')

    except Exception as e:
        log(f'Sync: unexpected error: {e}', level='error')
