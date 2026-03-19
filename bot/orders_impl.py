# -*- coding: utf-8 -*-
"""Order execution: place_buy, place_sell, and related helpers.

Extracted from trailing_bot.py to reduce monolith size.
All shared state accessed via ``bot.shared.state``.
"""
from __future__ import annotations

import json
import os
import time
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional


def _get_state():
    from bot.shared import state
    return state


# ── Module-local mutable state ──────────────────────────────────────
_BALANCE_API_FAILURE_TS: float = 0.0


# ─── place_buy ──────────────────────────────────────────────────────

def place_buy(market, eur_amount, entry_price, order_type=None, *, is_dca: bool = False):
    global _BALANCE_API_FAILURE_TS
    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    open_trades = S.open_trades
    trades_lock = S.trades_lock
    bitvavo = S.bitvavo
    safe_call = S.safe_call

    # --- Saldo Guard cooldown (skip for DCA — existing position maintenance) ---
    if not is_dca:
        cooldown_until = float(CONFIG.get('_SALDO_COOLDOWN_UNTIL', 0))
        if cooldown_until and time.time() < cooldown_until:
            remaining = int(cooldown_until - time.time())
            log(f"🛡️ Saldo Guard cooldown actief ({remaining}s resterend) — entry {market} overgeslagen", level='warning')
            return {"error": "saldo_guard_cooldown"}

    # --- Watchlist ---
    watch_cfg = S._get_watchlist_runtime_settings()
    if watch_cfg['enabled'] and S.is_watchlist_market(market):
        if watch_cfg['paper_only']:
            log(f"Watchlist paper mode skip real order for {market}", level='info')
            return {"simulated": True, "watchlist": True, "mode": "paper"}
        micro_cap = max(0.0, watch_cfg['micro_trade_amount_eur'])
        if micro_cap > 0 and eur_amount > micro_cap:
            log(f"Watchlist clamp {market}: {eur_amount:.2f} -> {micro_cap:.2f} EUR", level='debug')
            eur_amount = micro_cap

    # 1. Max open trades check
    max_trades = max(1, int(CONFIG.get('MAX_OPEN_TRADES', 5)))
    pending_bitvavo = S.get_pending_bitvavo_orders()
    pending_bitvavo_markets = [o['market'] for o in pending_bitvavo if o['market'] != market]
    pending_markets = S._get_pending_markets_dict()
    reserved = len([m for m in pending_markets if m != market])
    pending_orders = len(pending_bitvavo_markets)
    from bot.portfolio import count_active_open_trades, current_open_exposure_eur
    current = count_active_open_trades(threshold=S.DUST_TRADE_THRESHOLD_EUR)
    total_slots_used = current + reserved + pending_orders
    if total_slots_used >= max_trades and market not in open_trades:
        log(f"Max open trades limiet bereikt ({current} active + {pending_orders} pending orders + {reserved} reserved = {total_slots_used}/{max_trades}), geen nieuwe trade voor {market}", level='warning')
        return {"error": "max_open_trades_reached"}

    # 1b. Cluster/correlation throttle
    base = market.split('-')[0]
    cluster_positions = [t for mk, t in (open_trades or {}).items() if isinstance(mk, str) and mk.startswith(f"{base}-")]
    MAX_CLUSTER_TRADES_PER_BASE = int(CONFIG.get('MAX_CLUSTER_TRADES_PER_BASE', max(1, max_trades // 2)))
    MAX_CLUSTER_EXPOSURE_EUR = float(CONFIG.get('MAX_CLUSTER_EXPOSURE_EUR', CONFIG.get('MAX_TOTAL_EXPOSURE_EUR', 300.0)))
    if market not in open_trades and len(cluster_positions) >= MAX_CLUSTER_TRADES_PER_BASE:
        log(f"Clusterlimiet bereikt voor {base}: {len(cluster_positions)}/{MAX_CLUSTER_TRADES_PER_BASE}, skip {market}", level='warning')
        return {"error": "cluster_limit_reached"}
    try:
        cluster_exposure = sum(float(t.get('amount', 0.0) or 0.0) * float(t.get('buy_price', 0.0) or 0.0) for t in cluster_positions)
    except Exception:
        cluster_exposure = 0.0
    if market not in open_trades and (cluster_exposure + eur_amount) > MAX_CLUSTER_EXPOSURE_EUR:
        log(f"Cluster exposure te hoog voor {base}: {cluster_exposure+eur_amount:.2f}>{MAX_CLUSTER_EXPOSURE_EUR:.2f}, skip {market}", level='warning')
        return {"error": "cluster_exposure_limit"}

    # 1c. Total portfolio exposure guard
    try:
        max_total_exp = float(CONFIG.get('MAX_TOTAL_EXPOSURE_EUR', 9999))
        if max_total_exp < 9000:
            cur_exp = current_open_exposure_eur(include_dust=False)
            if (cur_exp + eur_amount) > max_total_exp:
                log(f"Total exposure limiet bereikt: {cur_exp:.2f}+{eur_amount:.2f}={cur_exp+eur_amount:.2f} > {max_total_exp:.2f} EUR, skip {market}", level='warning')
                return {"error": "total_exposure_limit"}
    except Exception as e:
        log(f"Total exposure check failed: {e}", level='warning')

    # 1c-2. Budget reservation
    try:
        _budget_cfg = CONFIG.get('BUDGET_RESERVATION', {})
        if _budget_cfg.get('enabled', False):
            _budget_mode = _budget_cfg.get('mode', 'static')
            if _budget_mode == 'dynamic':
                try:
                    import bot.api as _api_mod
                    _eur_bal = _api_mod.get_eur_balance(force_refresh=False) or 0.0
                    _eur_in_order = 0.0
                    try:
                        _balances = safe_call(bitvavo.balance, {})
                        if isinstance(_balances, list):
                            for _be in _balances:
                                if isinstance(_be, dict) and _be.get('symbol') == 'EUR':
                                    _eur_in_order = float(_be.get('inOrder', 0.0))
                                    _eur_bal = float(_be.get('available', 0.0))
                                    break
                    except Exception:
                        pass
                    _total_eur = _eur_bal + _eur_in_order
                    # Include open crypto exposure in portfolio total so budget
                    # doesn't shrink as EUR is converted to positions (deadlock fix)
                    _open_exp_for_budget = current_open_exposure_eur(include_dust=False)
                    _portfolio_total = _total_eur + _open_exp_for_budget
                    _trailing_pct = float(_budget_cfg.get('trailing_pct', 55)) / 100.0
                    _reserve_eur = float(_budget_cfg.get('min_reserve_eur', 10))
                    trailing_max_base = max(0, (_portfolio_total - _reserve_eur) * _trailing_pct)
                except Exception:
                    trailing_max_base = float(_budget_cfg.get('trailing_bot_max_eur', 9999))
            else:
                trailing_max_base = float(_budget_cfg.get('trailing_bot_max_eur', 180))
            trailing_profit_bonus = 0.0
            if _budget_cfg.get('reinvest_trailing_profits', True):
                try:
                    _tl_path_b = CONFIG.get('TRADE_LOG', 'data/trade_log.json')
                    if os.path.exists(_tl_path_b):
                        with open(_tl_path_b, 'r', encoding='utf-8') as _fb:
                            _tl_b = json.load(_fb)
                        _closed_b = _tl_b.get('closed', []) if isinstance(_tl_b, dict) else []
                        trailing_profit_bonus = max(0, sum(
                            float(t.get('profit', 0) or 0) for t in _closed_b
                            if isinstance(t, dict) and 'profit' in t
                        ))
                except Exception:
                    trailing_profit_bonus = 0.0
            trailing_effective_max = trailing_max_base + trailing_profit_bonus
            trailing_cur_exp = current_open_exposure_eur(include_dust=False)
            if (trailing_cur_exp + eur_amount) > trailing_effective_max:
                log(f"Trailing budget limiet: {trailing_cur_exp:.2f}+{eur_amount:.2f}={trailing_cur_exp+eur_amount:.2f} > {trailing_effective_max:.2f} EUR (base {trailing_max_base:.0f} + profit {trailing_profit_bonus:.2f}), skip {market}", level='warning')
                return {"error": "trailing_budget_limit"}
    except Exception as e:
        log(f"Budget reservation check failed: {e}", level='warning')

    # 1d. Daily/weekly loss circuit breaker
    try:
        _daily_limit = float(CONFIG.get('RISK_MAX_DAILY_LOSS', 9999) or 9999)
        _weekly_limit = float(CONFIG.get('RISK_MAX_WEEKLY_LOSS', 9999) or 9999)
        if _daily_limit < 9000 or _weekly_limit < 9000:
            _tl_path = CONFIG.get('TRADE_LOG', 'data/trade_log.json')
            if os.path.exists(_tl_path):
                with open(_tl_path, 'r', encoding='utf-8') as _fh:
                    _tl_data = json.load(_fh)
                _closed = _tl_data.get('closed', []) if isinstance(_tl_data, dict) else []
                _now = time.time()
                _daily_loss = sum(
                    abs(float(t.get('profit', 0) or 0))
                    for t in _closed
                    if float(t.get('profit', 0) or 0) < 0 and (_now - float(t.get('timestamp', 0) or 0)) < 86400
                )
                _weekly_loss = sum(
                    abs(float(t.get('profit', 0) or 0))
                    for t in _closed
                    if float(t.get('profit', 0) or 0) < 0 and (_now - float(t.get('timestamp', 0) or 0)) < 604800
                )
                if _daily_limit < 9000 and _daily_loss >= _daily_limit:
                    log(f"🛑 Daily loss limiet bereikt: {_daily_loss:.2f} >= {_daily_limit:.2f} EUR, skip {market}", level='warning')
                    return {"error": "daily_loss_limit"}
                if _weekly_limit < 9000 and _weekly_loss >= _weekly_limit:
                    log(f"🛑 Weekly loss limiet bereikt: {_weekly_loss:.2f} >= {_weekly_limit:.2f} EUR, skip {market}", level='warning')
                    return {"error": "weekly_loss_limit"}
    except Exception as e:
        log(f"Daily/weekly loss check failed: {e}", level='warning')

    # 2. EUR balance safeguard
    try:
        balances = S.sanitize_balance_payload(safe_call(bitvavo.balance, {}), source='place_buy.balance_guard')
        eur_bal = 0.0
        for a in balances:
            if a.get('symbol') == 'EUR':
                eur_bal = float(a.get('available', 0) or 0)
                break
        min_required = CONFIG.get('BASE_AMOUNT_EUR', 25) + CONFIG.get('MIN_BALANCE_RESERVE', 5)
        if eur_bal < min_required:
            log(f"EUR balans te laag ({eur_bal:.2f} < {min_required:.2f}), geen nieuwe trade voor {market}", level='warning')
            return {"error": "eur_balance_too_low"}
    except Exception as e:
        log(f"Kon EUR-saldo niet ophalen voor safeguard: {e}", level='warning')

    # Determine order type
    ot = str(order_type or S.ORDER_TYPE or 'auto').lower()
    book = S.get_ticker_best_bid_ask(market)
    use_limit = False
    if ot == 'limit':
        use_limit = True if book else False
    elif ot == 'market':
        use_limit = False
    else:
        if book:
            spread = (book['ask'] - book['bid']) / ((book['ask'] + book['bid']) / 2)
            if spread < 0.001:
                use_limit = True

    # Reference price
    ref_price = None
    try:
        if entry_price is not None:
            ref_price = float(entry_price)
        elif book:
            ref_price = float(book['bid']) if book.get('bid') else float((book['bid'] + book['ask']) / 2)
        else:
            p = S.get_current_price(market)
            ref_price = float(p) if p is not None else None
    except Exception:
        ref_price = None

    # Enforce minimum order size
    amt_decimals = S.get_amount_precision(market)
    px_decimals = S.get_price_precision(market)
    min_size = S.get_min_order_size(market)
    if ref_price is not None and min_size:
        try:
            est_base = float(eur_amount) / float(ref_price)
        except Exception:
            est_base = None
        if est_base is not None and (est_base < min_size):
            log(f"Order te klein voor {market}: {est_base:.8f} < min {min_size}", level='warning')
            return {"error": "order_too_small"}

    # TEST_MODE shortcut
    if S.TEST_MODE or not S.LIVE_TRADING:
        est_txt = f"~{(float(eur_amount)/float(ref_price)):.8f}" if ref_price else "~?"
        log(f"(SIM) BUY {market} voor {eur_amount} EUR ({est_txt}) [TEST_MODE]")
        return {"simulated": True}

    # AUTO_USE_FULL_BALANCE
    if S.AUTO_USE_FULL_BALANCE:
        try:
            balances = S.sanitize_balance_payload(safe_call(bitvavo.balance, {}), source='place_buy.balance_auto_use')
            eur_bal = 0.0
            for a in balances:
                if a.get('symbol') == 'EUR':
                    eur_bal = float(a.get('available', 0) or 0)
                    break
            if eur_bal and eur_bal > 0:
                use_amount = eur_bal * S.FULL_BALANCE_PORTION
                use_amount = min(use_amount, S.FULL_BALANCE_MAX_EUR)
                log(f"AUTO_USE_FULL_BALANCE active: available EUR={eur_bal:.2f}, using {use_amount:.2f} EUR for this buy")
                eur_amount = round(use_amount, 2)
        except Exception as e:
            log(f"Kon EUR-saldo niet ophalen voor AUTO_USE_FULL_BALANCE: {e}", level='warning')

    # Block if operator ID missing
    if S.LIVE_TRADING and not S.PLACE_ORDERS_ENABLED:
        log(f"Blocked BUY for {market}: missing BITVAVO_OPERATOR_ID (operatorId).", level='error')
        return {"error": "operator_id_missing"}

    if use_limit and book:
        limit_offset_pct = CONFIG.get('LIMIT_ORDER_PRICE_OFFSET_PCT', 0.1) / 100.0
        price_for_limit = float(book['bid']) * (1 + limit_offset_pct)
        amount_base = float(eur_amount) / float(price_for_limit)
        q_amt = Decimal(str(amount_base)).quantize(Decimal('1.' + '0' * amt_decimals), rounding=ROUND_DOWN)
        q_px = Decimal(str(price_for_limit)).quantize(Decimal('1.' + '0' * px_decimals), rounding=ROUND_DOWN)
        params = {
            'amount': float(q_amt),
            'price': float(q_px)
        }
        OPERATOR_ID = S.OPERATOR_ID
        if OPERATOR_ID:
            params['operatorId'] = OPERATOR_ID
        resp = safe_call(bitvavo.placeOrder, market, 'buy', 'limit', params)
        if isinstance(resp, dict) and resp.get('errorCode') in (101, 429) and 'decimal' in str(resp.get('error', '')).lower():
            tighter = Decimal(str(amount_base)).quantize(Decimal('1.' + '0' * max(0, amt_decimals - 1)), rounding=ROUND_DOWN)
            params['amount'] = float(tighter)
            log(f"Rondingsherkansing amount voor {market}: {params['amount']} (prec {amt_decimals-1})")
            resp = safe_call(bitvavo.placeOrder, market, 'buy', 'limit', params)
        log(f"BUY resp={resp} (MAKER, limit order)")
    else:
        if ref_price is None:
            p = S.get_current_price(market)
            try:
                ref_price = float(p) if p is not None else None
            except Exception:
                ref_price = None
        if ref_price is not None and min_size:
            try:
                est_base = float(eur_amount) / float(ref_price)
                if est_base < min_size:
                    log(f"Market order te klein voor {market}: {est_base:.8f} < min {min_size}", level='warning')
                    return {"error": "order_too_small"}
            except Exception as e:
                log(f"est_base failed: {e}", level='error')
        q_eur = Decimal(str(eur_amount)).quantize(Decimal('1.00'), rounding=ROUND_DOWN)
        params = {
            'amountQuote': float(q_eur)
        }
        OPERATOR_ID = S.OPERATOR_ID
        if OPERATOR_ID:
            params['operatorId'] = OPERATOR_ID
        resp = safe_call(bitvavo.placeOrder, market, 'buy', 'market', params)
        log(f"BUY resp={resp} (TAKER, market order)")
    return resp


# ─── place_sell ─────────────────────────────────────────────────────

def place_sell(market, amount_base, *, skip_dust: bool = False):
    global _BALANCE_API_FAILURE_TS
    S = _get_state()
    log = S.log
    CONFIG = S.CONFIG
    open_trades = S.open_trades
    trades_lock = S.trades_lock
    bitvavo = S.bitvavo
    safe_call = S.safe_call

    if S.TEST_MODE or not S.LIVE_TRADING:
        log(f"(SIM) SELL {market} amount={amount_base:.8f} [TEST_MODE]")
        return {"simulated": True}

    # Check saldo
    symbol = market.split('-')[0]
    raw_balances = safe_call(bitvavo.balance, {})
    balances = S.sanitize_balance_payload(raw_balances, source='place_sell.balance_check')
    available = None
    if raw_balances is None:
        now = time.time()
        if now - _BALANCE_API_FAILURE_TS > 60:
            _BALANCE_API_FAILURE_TS = now
            log(f"Balance API returned None — skipping force-closes. Will retry later.", level='error')
        return {"error": "Balance API unavailable"}

    for asset in balances or []:
        if asset.get('symbol') == symbol:
            available = float(asset.get('available', 0))
            break

    # Reset saldo retry counter when balance IS found
    if available and available > 0 and market in open_trades:
        trade = open_trades.get(market)
        if trade and trade.get('_saldo_retry_count'):
            log(f"[saldo_retry] {market}: saldo gevonden, retry counter gereset", level='info')
            trade.pop('_saldo_retry_count', None)
            trade.pop('_saldo_last_error_ts', None)

    if available is None or available == 0:
        bitvavo_bal = None
        try:
            bals = S.sanitize_balance_payload(safe_call(bitvavo.balance, {}), source='place_sell.balance_retry')
            bitvavo_bal = next((b for b in bals if b.get('symbol') == symbol), None)
            if bitvavo_bal:
                retry_available = float(bitvavo_bal.get('available', 0) or 0)
                if retry_available > 0:
                    log(f"[saldo_retry] Herpoging succesvol: {symbol} saldo={retry_available:.8f}", level='info')
                    available = retry_available
        except Exception:
            bitvavo_bal = None

    if available is None or available == 0:
        log(f"[saldo_error] Geen saldo voor {symbol} na herpoging. Trade blijft open voor sync.", level='error')
        log(f"[saldo_error] Bitvavo saldo: {bitvavo_bal}", level='error')
        log(f"[saldo_error] Open trade: {open_trades.get(market)}", level='error')

        try:
            S.register_saldo_error(market, bitvavo_bal, open_trades.get(market))
        except Exception as saldo_err:
            log(f"[ERROR] register_saldo_error mislukt voor {market}: {saldo_err}", level='error')

        max_retries = int((CONFIG.get('SALDO_GUARD') or {}).get('max_retries_before_close', 3))
        with trades_lock:
            if market in open_trades:
                t = open_trades[market]
                retries = int(t.get('_saldo_retry_count', 0) or 0) + 1
                t['_saldo_retry_count'] = retries
                t['_saldo_last_error_ts'] = time.time()

                if retries >= max_retries:
                    log(f"[saldo_error] {market}: {retries} retries bereikt, trade wordt gesloten", level='error')
                    from bot.helpers import as_float
                    invested_eur = S.get_true_invested_eur(t, market=market)
                    partial_tp_returned = float(t.get('partial_tp_returned_eur', 0) or 0)
                    saldo_loss = -(invested_eur - partial_tp_returned)
                    closed_entry = {
                        'market': market,
                        'buy_price': t.get('buy_price', 0.0),
                        'buy_order_id': t.get('buy_order_id'),
                        'sell_price': 0.0,
                        'sell_order_id': None,
                        'amount': t.get('amount', 0.0),
                        'profit': round(saldo_loss, 4),
                        'invested_eur': round(invested_eur, 4),
                        'total_invested_eur': round(float(t.get('total_invested_eur', invested_eur) or invested_eur), 4),
                        'initial_invested_eur': round(float(t.get('initial_invested_eur', 0) or 0), 4),
                        'partial_tp_returned_eur': round(partial_tp_returned, 4),
                        'timestamp': time.time(),
                        'reason': 'saldo_error',
                        'bitvavo_balance': bitvavo_bal,
                        'saldo_retries': retries,
                    }
                    S._finalize_close_trade(market, t, closed_entry)
                else:
                    log(f"[saldo_error] {market}: retry {retries}/{max_retries} — trade blijft open, wacht op sync", level='warning')
        return {"error": "No balance (retry pending)"}

    # Sell-side slippage/spread awareness
    best = S.get_ticker_best_bid_ask(market)
    spread_pct = None
    if best and best.get('ask') and best.get('bid'):
        try:
            spread_pct = (best['ask'] - best['bid']) / ((best['ask'] + best['bid']) / 2)
        except Exception:
            spread_pct = None
    ref_price = best['bid'] if best and best.get('bid') else None

    import bot.api as _api_mod
    sell_slip = _api_mod.get_expected_slippage_sell(market, amount_base, ref_price)
    MAX_SPREAD_PCT = S.MAX_SPREAD_PCT
    if spread_pct is not None and spread_pct > MAX_SPREAD_PCT * 2:
        log(f"⚠️ Spread breed bij exit {market}: {spread_pct*100:.2f}%", level='warning')
    if sell_slip is not None and sell_slip > 0.01:
        log(f"⚠️ Verwachte sell-slippage hoog voor {market}: {sell_slip*100:.2f}%", level='warning')
    sell_amount = min(amount_base, available)
    if sell_amount < amount_base * 0.95:
        log(f"Waarschuwing: verkoophoeveelheid ({sell_amount:.8f}) veel lager dan gevraagd ({amount_base:.8f}) voor {symbol}")
    norm_amount = S.normalize_amount(market, sell_amount)
    if norm_amount <= 0:
        log(f"Sell amount voor {market} normaliseerde naar 0, verkoop overgeslagen.", level='warning')
        return {"error": "normalized_to_zero"}

    min_size = S.get_min_order_size(market)
    if min_size > 0 and norm_amount < min_size:
        log(f"⚠️ Sell amount {norm_amount:.8f} < min order size {min_size:.8f} for {market}, trying full available balance {available:.8f}", level='warning')
        norm_amount = S.normalize_amount(market, available)
        if norm_amount < min_size:
            log(f"❌ Even full balance {norm_amount:.8f} < min order {min_size:.8f} for {market} — dust trade, skipping sell", level='warning')
            return {"error": "below_minimum_order_size"}

    def _place_sell_order(amount: float):
        params = {'amount': float(amount)}
        if S.LIVE_TRADING and not S.PLACE_ORDERS_ENABLED:
            log(f"Blocked SELL for {market}: missing BITVAVO_OPERATOR_ID (operatorId). Trade not sent to Bitvavo.", level='error')
            return {"error": "operator_id_missing"}
        OPERATOR_ID = S.OPERATOR_ID
        if OPERATOR_ID:
            params['operatorId'] = OPERATOR_ID
        order_resp = safe_call(bitvavo.placeOrder, market, 'sell', 'market', params)
        if isinstance(order_resp, dict) and (order_resp.get('errorCode') in (101, 429) or 'decimal' in str(order_resp.get('error', '')).lower() or 'minimum' in str(order_resp.get('error', '')).lower()):
            error_str = str(order_resp.get('error', ''))
            if 'decimal' in error_str.lower():
                prec = S.get_amount_precision(market)
                tighter = float(Decimal(str(amount)).quantize(Decimal('1.' + '0' * max(0, prec)), rounding=ROUND_DOWN))
                if tighter <= 0:
                    tighter = S.normalize_amount(market, amount * 0.999)
                params['amount'] = float(tighter)
                log(f"Rondingsherkansing SELL amount voor {market}: {params['amount']} (prec={prec})")
            elif 'minimum' in error_str.lower():
                log(f"⚠️ Below minimum for {market}, amount={amount:.8f}", level='warning')
                return order_resp
            else:
                tighter = S.normalize_amount(market, amount * 0.999999)
                params['amount'] = float(tighter)
                log(f"Rondingsherkansing SELL amount voor {market}: {params['amount']}")
            order_resp = safe_call(bitvavo.placeOrder, market, 'sell', 'market', params)
        return order_resp

    # Exit liquidity guard: chunk sells
    chunk_count = 1
    if sell_slip is not None and sell_slip > 0.03:
        chunk_count = min(5, max(2, int((sell_slip / 0.02) + 1)))
    elif spread_pct is not None and spread_pct > MAX_SPREAD_PCT * 2:
        chunk_count = 2

    if chunk_count > 1:
        orders = []
        remaining = norm_amount
        for i in range(chunk_count):
            chunk = S.normalize_amount(market, remaining / (chunk_count - i))
            if chunk <= 0:
                break
            resp = _place_sell_order(chunk)
            orders.append(resp)
            try:
                filled = float(resp.get('filledAmount', chunk)) if isinstance(resp, dict) else chunk
            except Exception:
                filled = chunk
            remaining = max(0.0, remaining - filled)
            if remaining <= chunk * 0.05:
                break
        log(f"SELL chunked ({chunk_count}) resp={orders}")
        if not skip_dust:
            try:
                _cleanup_market_dust(market)
            except Exception as exc:
                log(f"[dust] cleanup fout voor {market}: {exc}", level='debug')
        return {'chunked': True, 'orders': orders, 'remaining': remaining}

    resp = _place_sell_order(norm_amount)
    log(f"SELL resp={resp}")
    if not skip_dust:
        try:
            _cleanup_market_dust(market)
        except Exception as exc:
            log(f"[dust] cleanup fout voor {market}: {exc}", level='debug')
    return resp


# ─── Helpers ────────────────────────────────────────────────────────

def is_order_success(resp):
    try:
        if not isinstance(resp, dict):
            return False
        if 'error' in resp or 'errorCode' in resp:
            return False
        status = str(resp.get('status', '')).lower()
        if status in ('rejected', 'expired', 'cancelled'):
            return False
        return True
    except Exception:
        return False


def _verify_sell_response(sell_response: dict, market: str, expected_amount: float) -> tuple:
    S = _get_state()
    log = S.log
    if not sell_response:
        return False, [], expected_amount, None
    if sell_response.get('error') or sell_response.get('errorCode'):
        return False, [], expected_amount, None

    if sell_response.get('chunked'):
        order_ids = []
        total_filled = 0.0
        weighted_price_sum = 0.0
        for o in sell_response.get('orders', []):
            if not isinstance(o, dict):
                continue
            if o.get('orderId'):
                order_ids.append(o['orderId'])
            try:
                filled = float(o.get('filledAmount', 0) or 0)
                if filled > 0:
                    total_filled += filled
                    if o.get('price'):
                        price = float(o['price'])
                        weighted_price_sum += price * filled
                    elif o.get('filledAmountQuote'):
                        quote = float(o['filledAmountQuote'])
                        weighted_price_sum += quote
            except Exception:
                pass
        remaining = float(sell_response.get('remaining', 0))
        avg_price = None
        if total_filled > 0 and weighted_price_sum > 0:
            avg_price = weighted_price_sum / total_filled
        if remaining > expected_amount * 0.05:
            log(f"⚠️ Chunked sell for {market} left {remaining:.8f} unsold ({remaining/expected_amount*100:.1f}%)", level='warning')
            return False, order_ids, remaining, avg_price
        return True, order_ids, remaining, avg_price

    order_id = sell_response.get('orderId')
    actual_price = None
    try:
        if sell_response.get('price'):
            actual_price = float(sell_response['price'])
        elif sell_response.get('filledAmount') and sell_response.get('filledAmountQuote'):
            filled_base = float(sell_response['filledAmount'])
            filled_quote = float(sell_response['filledAmountQuote'])
            if filled_base > 0:
                actual_price = filled_quote / filled_base
    except Exception as e:
        log(f"Could not extract execution price for {market}: {e}", level='debug')
    return True, [order_id] if order_id else [], 0.0, actual_price


def safe_sell(market, amount_base, precision):
    S = _get_state()
    log = S.log
    try:
        if amount_base is None:
            return None
        amt = float(amount_base)
        if amt <= 0:
            return None
        if isinstance(precision, int) and precision >= 0:
            quant = Decimal('1') if precision == 0 else Decimal('1.' + '0' * precision)
            amt = float(Decimal(str(amt)).quantize(quant, rounding=ROUND_DOWN))
        if amt <= 0:
            return None
        return place_sell(market, amt)
    except Exception as exc:
        log(f"safe_sell mislukt voor {market}: {exc}", level='error')
        return None


# ─── Dust cleanup ──────────────────────────────────────────────────

_DUST_SWEEP_TS: Dict[str, float] = {}


def _cleanup_market_dust(market: str) -> None:
    S = _get_state()
    log = S.log
    DUST_SWEEP_ENABLED = bool(S.CONFIG.get('DUST_SWEEP_ENABLED', True))
    DUST_THRESHOLD_EUR = float(S.CONFIG.get('DUST_THRESHOLD_EUR', 1.0))
    if not DUST_SWEEP_ENABLED or DUST_THRESHOLD_EUR <= 0:
        return
    if S.TEST_MODE or not S.LIVE_TRADING:
        return
    now = time.time()
    last = _DUST_SWEEP_TS.get(market)
    if last and (now - last) < 60:
        return
    symbol = market.split('-')[0]
    balances = S.sanitize_balance_payload(S.safe_call(S.bitvavo.balance, {}), source='dust_check')
    available = None
    for asset in balances or []:
        if asset.get('symbol') == symbol:
            try:
                available = float(asset.get('available', 0) or 0.0)
            except Exception:
                available = 0.0
            break
    if not available or available <= 0:
        return
    if market in S.open_trades:
        return
    from bot.helpers import coerce_positive_float
    price = coerce_positive_float(S.get_current_price(market))
    if price is None or price <= 0:
        return
    value_eur = available * price
    if value_eur >= DUST_THRESHOLD_EUR:
        return
    _DUST_SWEEP_TS[market] = now
    log(f"[dust] Restsaldo {symbol} ≈ €{value_eur:.2f} (amount={available:.8f}), poging tot opschonen.", level='info')
    resp = place_sell(market, available, skip_dust=True)
    if isinstance(resp, dict) and resp.get('error'):
        log(f"[dust] Opschonen mislukt voor {market}: {resp.get('error')}", level='warning')


def sweep_all_dust_positions() -> dict:
    S = _get_state()
    log = S.log
    DUST_SWEEP_ENABLED = bool(S.CONFIG.get('DUST_SWEEP_ENABLED', True))
    DUST_THRESHOLD_EUR = float(S.CONFIG.get('DUST_THRESHOLD_EUR', 1.0))
    if not DUST_SWEEP_ENABLED or DUST_THRESHOLD_EUR <= 0:
        return {'swept': [], 'errors': [], 'message': 'Dust sweep disabled'}
    if S.TEST_MODE or not S.LIVE_TRADING:
        return {'swept': [], 'errors': [], 'message': 'Test mode active'}

    log("[dust_sweep] Starting full account dust sweep...", level='info')
    balances = S.sanitize_balance_payload(S.safe_call(S.bitvavo.balance, {}), source='dust_sweep_all')
    if not balances:
        return {'swept': [], 'errors': [], 'message': 'Could not fetch balances'}

    swept = []
    errors = []
    for asset in balances:
        symbol = asset.get('symbol', '')
        if symbol == 'EUR':
            continue
        try:
            available = float(asset.get('available', 0) or 0.0)
        except Exception:
            continue
        if available <= 0:
            continue
        market = f"{symbol}-EUR"
        if market in S.open_trades:
            continue
        from bot.helpers import coerce_positive_float
        price = coerce_positive_float(S.get_current_price(market))
        if price is None or price <= 0:
            continue
        value_eur = available * price
        if value_eur >= DUST_THRESHOLD_EUR:
            continue
        log(f"[dust_sweep] Found dust: {symbol} = {available:.8f} (€{value_eur:.4f})", level='info')
        try:
            resp = place_sell(market, available, skip_dust=True)
            if isinstance(resp, dict) and resp.get('error'):
                errors.append({'market': market, 'error': resp.get('error')})
            else:
                swept.append({'market': market, 'amount': available, 'value_eur': value_eur})
        except Exception as exc:
            errors.append({'market': market, 'error': str(exc)})

    log(f"[dust_sweep] Complete: {len(swept)} swept, {len(errors)} errors", level='info')
    return {'swept': swept, 'errors': errors, 'message': f'Swept {len(swept)} positions'}
