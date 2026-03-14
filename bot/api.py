"""Bitvavo API wrapper — rate limiting, caching, circuit breaker, precision helpers.

Initialise once via ``init(bitvavo_client, config)`` before calling any function.
All internal cache / rate-limit state lives in this module — no shared globals.
"""
from __future__ import annotations

import copy
import json
import math
import os
import random
import socket
import threading
import time
from collections import deque
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bot.helpers import as_bool, as_int, as_float
from modules.logging_utils import log
from modules.json_compat import write_json_compat

try:
    from modules.metrics import get_collector as get_metrics_collector
except Exception:  # pragma: no cover
    def get_metrics_collector():  # type: ignore[misc]
        return None

try:
    import requests as _requests  # type: ignore
    _REQUESTS_EXC: Tuple[type, ...] = (_requests.exceptions.RequestException,)
except Exception:  # pragma: no cover
    _REQUESTS_EXC = ()

# ---------------------------------------------------------------------------
# Module state — set by init()
# ---------------------------------------------------------------------------
_bv: Any = None          # Bitvavo client
_cfg: dict = {}          # CONFIG dict reference (mutable — always current)
_risk_mgr: Any = None    # RiskManager (optional)

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------
_rate_limit_lock = threading.Lock()
_rate_buckets: Dict[str, deque] = {}

# ---------------------------------------------------------------------------
# API response cache
# ---------------------------------------------------------------------------
_cache_lock = threading.Lock()
_cache_store: Dict[Tuple[str, str, str], Tuple[float, float, Any]] = {}

# ---------------------------------------------------------------------------
# Error suppression (avoid spamming logs for transient errors)
# ---------------------------------------------------------------------------
_API_ERROR_LOG_SUPPRESS: Dict[str, float] = {}

_TRANSIENT_ERROR_PATTERNS = (
    "rate limit", "timeout", "temporarily unavailable", "saldo_error",
    "name resolution", "getaddrinfo failed", "failed to resolve",
    "connection aborted", "connection reset", "connection refused",
    "connection closed", "network is unreachable", "temporarily down",
)
_NAME_RESOLUTION_PATTERNS = (
    "name resolution", "getaddrinfo failed", "failed to resolve",
    "temporary failure in name resolution",
)

# ---------------------------------------------------------------------------
# Price cache (in-memory + disk fallback)
# ---------------------------------------------------------------------------
_price_cache: Dict[str, dict] = {}

# ---------------------------------------------------------------------------
# EUR balance cache
# ---------------------------------------------------------------------------
_EUR_BALANCE_CACHE: Dict[str, Any] = {'value': None, 'timestamp': 0}
_EUR_BALANCE_CACHE_TTL = 300

# ---------------------------------------------------------------------------
# Market info / precision cache
# ---------------------------------------------------------------------------
_MARKET_INFO_CACHE: Dict[str, dict] = {}
_MARKET_INFO_TTL_SEC = 600


# ===================================================================
# INIT
# ===================================================================

def init(bitvavo_client: Any, config: dict, *, risk_mgr: Any = None) -> None:
    """Bind shared references.  Call once at startup (e.g. in ``initialize_managers``)."""
    global _bv, _cfg, _risk_mgr
    _bv = bitvavo_client
    _cfg = config
    _risk_mgr = risk_mgr


# ===================================================================
# RATE LIMITING
# ===================================================================

def _endpoint_limit(endpoint: str) -> Tuple[int, float]:
    ep_limits = _cfg.get('BITVAVO_ENDPOINT_LIMITS', {})
    default_calls = as_int(_cfg.get('BITVAVO_RATE_LIMIT_CALLS', 950), 950)
    default_window = as_float(_cfg.get('BITVAVO_RATE_LIMIT_WINDOW', 1.0), 1.0)
    cfg = ep_limits.get(endpoint)
    if isinstance(cfg, dict):
        limit = as_int(cfg.get('calls'), default_calls)
        window = as_float(cfg.get('window'), default_window)
    elif isinstance(cfg, (int, float)):
        limit = int(cfg)
        window = default_window
    else:
        limit = default_calls
        window = default_window
    limit = max(0, limit)
    window = default_window if window is None else float(window)
    if window <= 0:
        window = default_window
    return limit, max(0.1, window)


def _acquire_rate_slot(endpoint: str) -> None:
    rate_enabled = as_bool(_cfg.get('BITVAVO_RATE_LIMIT_ENABLED', True), True)
    if not rate_enabled:
        return
    default_calls = as_int(_cfg.get('BITVAVO_RATE_LIMIT_CALLS', 950), 950)
    default_window = as_float(_cfg.get('BITVAVO_RATE_LIMIT_WINDOW', 1.0), 1.0)
    log_threshold = as_float(_cfg.get('BITVAVO_RATE_LIMIT_LOG_THRESHOLD', 0.5), 0.5)
    total_wait = 0.0
    while True:
        now = time.time()
        wait_for = 0.0
        dq_global = None
        dq_endpoint = None
        endpoint_limit = 0
        endpoint_window = default_window
        with _rate_limit_lock:
            if default_calls > 0 and default_window > 0:
                dq_global = _rate_buckets.setdefault('__global__', deque())
                while dq_global and now - dq_global[0] >= default_window:
                    dq_global.popleft()
                if len(dq_global) >= default_calls:
                    wait_for = max(wait_for, default_window - (now - dq_global[0]))
            endpoint_limit, endpoint_window = _endpoint_limit(endpoint)
            if endpoint_limit > 0:
                dq_endpoint = _rate_buckets.setdefault(endpoint, deque())
                while dq_endpoint and now - dq_endpoint[0] >= endpoint_window:
                    dq_endpoint.popleft()
                if len(dq_endpoint) >= endpoint_limit:
                    wait_for = max(wait_for, endpoint_window - (now - dq_endpoint[0]))
            if wait_for <= 0:
                if dq_global is not None and default_calls > 0:
                    dq_global.append(now)
                if dq_endpoint is not None and endpoint_limit > 0:
                    dq_endpoint.append(now)
                if total_wait > 0 and log_threshold > 0 and total_wait >= log_threshold:
                    log(f"Rate limiter wachtte {total_wait:.2f}s voor {endpoint}", level='debug')
                return
        sleep_for = max(wait_for, 0.01)
        time.sleep(min(sleep_for, 0.5))
        total_wait += sleep_for


# ===================================================================
# CACHE
# ===================================================================

def _build_cache_key(name: str, args: Tuple[Any, ...], kwargs: Dict[str, Any]) -> Tuple[str, str, str]:
    try:
        args_repr = json.dumps(args, sort_keys=True, default=str)
    except Exception:
        args_repr = repr(args)
    try:
        kwargs_repr = json.dumps(kwargs, sort_keys=True, default=str)
    except Exception:
        try:
            kwargs_repr = repr(sorted(kwargs.items()))
        except Exception:
            kwargs_repr = repr(kwargs)
    return name, args_repr, kwargs_repr


def _cache_get(cache_key: Tuple[str, str, str]) -> Any:
    now = time.time()
    with _cache_lock:
        entry = _cache_store.get(cache_key)
        if not entry:
            return None
        ts, ttl, payload = entry
        if ttl <= 0 or (now - ts) > ttl:
            _cache_store.pop(cache_key, None)
            return None
        return copy.deepcopy(payload)


def _cache_set(cache_key: Tuple[str, str, str], ttl: float, payload: Any) -> None:
    if ttl <= 0:
        return
    with _cache_lock:
        _cache_store[cache_key] = (time.time(), float(ttl), copy.deepcopy(payload))


def _cache_invalidate(cache_key: Tuple[str, str, str]) -> None:
    with _cache_lock:
        _cache_store.pop(cache_key, None)


# ===================================================================
# ERROR TRACKING / METRICS
# ===================================================================

def _should_log_api_error(signature: str, cooldown: float) -> bool:
    now = time.time()
    last = _API_ERROR_LOG_SUPPRESS.get(signature, 0.0)
    if (now - last) < cooldown:
        return False
    _API_ERROR_LOG_SUPPRESS[signature] = now
    return True


def _emit_api_metric(api_name: str, duration_ms: float, result: str, code: str | None = None) -> None:
    try:
        mc = get_metrics_collector()
    except Exception:
        mc = None
    if not mc:
        return
    try:
        labels: dict = {"api": api_name, "result": result}
        if code:
            labels["code"] = str(code)
        mc.publish({"api_latency_ms": float(duration_ms)}, labels=labels)
    except Exception:
        pass  # metrics must never break trading flow


# ===================================================================
# safe_call — core API call with retry + circuit breaker
# ===================================================================

# Circuit-breaker state lives here (module-level dict, not in trailing_bot globals)
_CB_STATE: Dict[str, dict] = {}
_CB_LOCK = threading.Lock()  # Beschermt _CB_STATE tegen race conditions tussen threads


def safe_call(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Bitvavo API wrapper met retry, circuit breaker, rate limiting en optionele caching."""
    try:
        key = getattr(func, '__name__', str(func))
    except Exception:
        key = 'unknown'

    # --- optional caching ------------------------------------------------
    cache_key: Optional[Tuple[str, str, str]] = None
    cache_ttl = 0.0
    cache_ttls = _cfg.get('BITVAVO_CACHE_TTLS', {})
    if cache_ttls:
        try:
            cache_ttl = max(0.0, as_float(cache_ttls.get(key), 0.0))
        except Exception:
            cache_ttl = 0.0
        if cache_ttl > 0:
            cache_key = _build_cache_key(key, args, kwargs)
            cached = _cache_get(cache_key)
            if cached is not None:
                return cached

    # --- circuit breaker check -------------------------------------------
    with _CB_LOCK:
        st = _CB_STATE.get(key, {'failures': 0, 'state': 'closed', 'opened_ts': 0}).copy()
    now = time.time()
    open_secs = _cfg.get('SAFE_CALL_OPEN_SECONDS', 30)
    fail_thresh = _cfg.get('SAFE_CALL_FAIL_THRESHOLD', 5)
    cb_enabled = _cfg.get('SAFE_CALL_CIRCUIT_ENABLED', True)

    if cb_enabled and st.get('state') == 'open' and (now - st.get('opened_ts', 0) < open_secs):
        if (now - st.get('opened_ts', 0)) < 1:
            log(f"Circuit OPEN for {key}, skipping API call for {open_secs}s", level='warning')
        return None
    if cb_enabled and st.get('state') == 'open' and (now - st.get('opened_ts', 0) >= open_secs):
        st['state'] = 'half'
        with _CB_LOCK:
            _CB_STATE[key] = st

    max_retries = max(1, int(_cfg.get('SAFE_CALL_MAX_RETRIES', 5)))
    base_delay = max(0.25, float(_cfg.get('SAFE_CALL_BASE_DELAY_SECONDS', 0.5)))
    max_delay = max(base_delay, float(_cfg.get('SAFE_CALL_MAX_DELAY_SECONDS', 10.0)))
    suppress_window = max(5.0, float(_cfg.get('SAFE_CALL_ERROR_SUPPRESS_SECONDS', 60.0)))

    overall_start = time.perf_counter()
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            attempt_start = time.perf_counter()
            _acquire_rate_slot(key)

            # Hard timeout: 10 s per API call (Windows-compatible thread approach)
            result_holder: Dict[str, Any] = {'resp': None, 'error': None, 'completed': False}

            def _api_call_with_timeout() -> None:
                try:
                    result_holder['resp'] = func(*args, **kwargs)
                    result_holder['completed'] = True
                except Exception as exc:
                    result_holder['error'] = exc
                    result_holder['completed'] = True

            thread = threading.Thread(target=_api_call_with_timeout, daemon=True)
            thread.start()
            thread.join(timeout=10.0)

            if not result_holder['completed']:
                raise TimeoutError(f"API call {key} exceeded 10s timeout")
            if result_holder['error']:
                raise result_holder['error']

            resp = result_holder['resp']
            if cb_enabled:
                with _CB_LOCK:
                    _CB_STATE[key] = {'failures': 0, 'state': 'closed', 'opened_ts': 0}
            if cache_key is not None and cache_ttl > 0 and resp is not None:
                _cache_set(cache_key, cache_ttl, resp)
            try:
                duration_ms = (time.perf_counter() - attempt_start) * 1000.0
            except Exception:
                duration_ms = 0.0
            _emit_api_metric(key, duration_ms, 'success')
            return resp
        except Exception as e:
            last_exc = e
            msg = str(e).lower()
            transient = any(p in msg for p in _TRANSIENT_ERROR_PATTERNS)
            if not transient:
                transient_types: Tuple[type, ...] = (TimeoutError, ConnectionError, socket.timeout, socket.gaierror)
                transient = isinstance(e, transient_types + _REQUESTS_EXC)
            if transient:
                is_name_res = any(p in msg for p in _NAME_RESOLUTION_PATTERNS)
                should_log = True
                if is_name_res:
                    should_log = _should_log_api_error(f"name_resolution:{key}", suppress_window)
                if should_log:
                    log(f"API error (retry {attempt+1}/{max_retries}): {e}", level='warning')
                sleep_cap = min(max_delay, base_delay * (2 ** attempt))
                time.sleep(random.uniform(base_delay, sleep_cap))
                if cb_enabled:
                    with _CB_LOCK:
                        st = _CB_STATE.get(key, {'failures': 0, 'state': 'closed', 'opened_ts': 0}).copy()
                    st['failures'] = st.get('failures', 0) + 1
                    if st['failures'] >= fail_thresh:
                        st['state'] = 'open'
                        st['opened_ts'] = time.time()
                        log(f"Circuit OPEN for {key} after {st['failures']} failures", level='error')
                    with _CB_LOCK:
                        _CB_STATE[key] = st
                continue
            log(f"API error: {e}", level='error')
            try:
                if _risk_mgr:
                    _risk_mgr.record_api_error()
            except Exception as re:
                log(f"[ERROR] risk_manager.record_api_error failed: {re}", level='error')
            if "saldo_error" in msg:
                log(f"[saldo_error] Extra details: args={args}, kwargs={kwargs}", level='error')
            return None

    # max retries exceeded
    log(f"API error: {last_exc} (max retries reached)", level='error')
    try:
        if _risk_mgr:
            _risk_mgr.record_api_error()
    except Exception as re:
        log(f"[ERROR] risk_manager.record_api_error failed: {re}", level='error')
    try:
        duration_ms = (time.perf_counter() - overall_start) * 1000.0
    except Exception:
        duration_ms = 0.0
    _emit_api_metric(key, duration_ms, 'failure')
    return None


# ===================================================================
# BALANCE
# ===================================================================

def sanitize_balance_payload(payload: Any, *, source: str = 'bitvavo.balance') -> List[Dict[str, Any]]:
    """Return een lijst met geldige balance dicts en log alles wat onjuist is."""
    if payload is None:
        return []
    data = payload
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except Exception:
            log(f"{source}: onverwachte string response, kan niet ontleden", level='error')
            return []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        log(f"{source}: verwacht lijst met balances maar kreeg {type(data).__name__}", level='error')
        return []
    cleaned: List[Dict[str, Any]] = []
    for idx, entry in enumerate(data):
        if isinstance(entry, dict):
            cleaned.append(entry)
            continue
        if isinstance(entry, str):
            try:
                parsed = json.loads(entry)
                if isinstance(parsed, dict):
                    cleaned.append(parsed)
                    continue
            except Exception:
                pass
        log(f"{source}: skip invalid balance entry at index {idx}: {type(entry).__name__}", level='warning')
    return cleaned


def get_eur_balance(force_refresh: bool = False) -> float:
    """EUR balance with 5-min TTL cache."""
    now = time.time()
    if not force_refresh and _EUR_BALANCE_CACHE['value'] is not None:
        age = now - _EUR_BALANCE_CACHE['timestamp']
        if age < _EUR_BALANCE_CACHE_TTL:
            log(f"[PERF] EUR balance from cache (age: {age:.1f}s): {_EUR_BALANCE_CACHE['value']}", level='debug')
            return _EUR_BALANCE_CACHE['value']
    try:
        balances = sanitize_balance_payload(safe_call(_bv.balance, {}), source='get_eur_balance')
        bal = 0.0
        for entry in balances:
            if isinstance(entry, dict) and entry.get('symbol') == 'EUR':
                try:
                    bal = float(entry.get('available', 0.0))
                except Exception:
                    bal = 0.0
                break
        _EUR_BALANCE_CACHE['value'] = bal
        _EUR_BALANCE_CACHE['timestamp'] = now
        log(f"[PERF] EUR balance refreshed: {bal}", level='debug')
        return bal
    except Exception as e:
        log(f"[ERROR] Failed to fetch EUR balance: {e}", level='error')
        return _EUR_BALANCE_CACHE.get('value', 0.0)


# ===================================================================
# CANDLES / PRICE
# ===================================================================

def _iso_to_ms(val: Any) -> Optional[int]:
    try:
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return int(float(val) * 1000)
        if isinstance(val, str):
            try:
                from datetime import datetime, timezone
                dt = datetime.strptime(val, "%Y-%m-%dT%H:%M:%SZ")
                dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except Exception:
                try:
                    return int(float(val) * 1000)
                except Exception:
                    return None
    except Exception:
        return None


def get_candles(market: str, interval: str = '1m', limit: int = 120,
                start: Any = None, end: Any = None) -> list:
    params: dict = {'limit': limit}
    s_ms = _iso_to_ms(start)
    e_ms = _iso_to_ms(end)
    if s_ms is not None:
        params['start'] = s_ms
    if e_ms is not None:
        params['end'] = e_ms
    return safe_call(_bv.candles, market, interval, params) or []


def _fetch_price_once(market: str) -> Optional[float]:
    t = safe_call(_bv.tickerPrice, {'market': market})
    if not t or 'price' not in t:
        return None
    try:
        return float(t['price'])
    except Exception:
        return None


def get_current_price(market: str, force_refresh: bool = False) -> Optional[float]:
    now = time.time()
    price_ttl = _cfg.get('PRICE_CACHE_TTL', 5)
    if not force_refresh:
        entry = _price_cache.get(market)
        if entry and now - entry['ts'] <= price_ttl:
            return entry['price']
    max_retries = _cfg.get('PRICE_FETCH_RETRIES', 2)
    price = None
    for attempt in range(max_retries + 1):
        price = _fetch_price_once(market)
        if price is not None:
            break
        time.sleep(0.5 * (attempt + 1))
    _price_cache[market] = {'price': price, 'ts': now}
    price_cache_file = _cfg.get('PRICE_CACHE_FILE', 'data/price_cache.json')
    try:
        disk: dict = {}
        if os.path.exists(price_cache_file):
            try:
                with open(price_cache_file, 'r', encoding='utf-8') as fh:
                    disk = json.load(fh)
                if not isinstance(disk, dict):
                    disk = {}
            except (json.JSONDecodeError, ValueError):
                # Corrupt file (OneDrive sync race) → rebuild from memory cache
                disk = {k: v for k, v in _price_cache.items() if v.get('price') is not None}
        disk[market] = {'price': price, 'ts': now}
        write_json_compat(price_cache_file, disk)
    except Exception as e:
        log(f"disk failed: {e}", level='error')
    if price is None:
        try:
            if os.path.exists(price_cache_file):
                with open(price_cache_file, 'r', encoding='utf-8') as fh:
                    disk = json.load(fh)
                entry = disk.get(market)
                if entry and entry.get('price') is not None:
                    return float(entry['price'])
        except Exception as e:
            log(f"exists failed: {e}", level='error')
    return price


# ===================================================================
# ORDER BOOK / SPREAD / SLIPPAGE
# ===================================================================

def get_ticker_best_bid_ask(m: str) -> Optional[Dict[str, float]]:
    b = safe_call(_bv.book, m, {'depth': 1})
    if not b:
        return None
    try:
        return {'ask': float(b['asks'][0][0]), 'bid': float(b['bids'][0][0])}
    except Exception:
        return None


def spread_ok(m: str) -> bool:
    max_spread = as_float(_cfg.get('MAX_SPREAD_PCT', 0.02), 0.02)
    t = get_ticker_best_bid_ask(m)
    if not t:
        return False
    ask, bid = t['ask'], t['bid']
    return (ask - bid) / ((ask + bid) / 2) <= max_spread


def get_expected_slippage(market: str, amount_eur: float, entry_price: float) -> Optional[float]:
    """Estimate buy-side slippage using shallow orderbook depth."""
    try:
        book = safe_call(_bv.book, market, {'depth': 10})
    except Exception:
        book = None
    if not book or 'asks' not in book:
        return None
    try:
        asks = [(float(px), float(sz)) for px, sz, *_ in book.get('asks', [])
                if px is not None and sz is not None]
        if not asks:
            return None
        base_needed = float(amount_eur) / float(entry_price)
        remaining = base_needed
        cost = 0.0
        for px, sz in asks:
            take = min(remaining, sz)
            cost += take * px
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return None
        vwap = cost / base_needed
        return (vwap - float(entry_price)) / float(entry_price)
    except Exception:
        return None


def get_expected_slippage_sell(market: str, amount_base: float, ref_price: float) -> Optional[float]:
    """Estimate sell-side slippage using bids."""
    try:
        book = safe_call(_bv.book, market, {'depth': 10})
    except Exception:
        book = None
    if not book or 'bids' not in book:
        return None
    try:
        bids = [(float(px), float(sz)) for px, sz, *_ in book.get('bids', [])
                if px is not None and sz is not None]
        if not bids:
            return None
        remaining = float(amount_base)
        proceeds = 0.0
        for px, sz in bids:
            take = min(remaining, sz)
            proceeds += take * px
            remaining -= take
            if remaining <= 0:
                break
        if remaining > 0:
            return None
        vwap = proceeds / float(amount_base)
        return (float(ref_price) - vwap) / float(ref_price) if ref_price else 0.0
    except Exception:
        return None


# ===================================================================
# MARKET INFO / PRECISION
# ===================================================================

def _now_ts() -> float:
    try:
        return time.time()
    except Exception:
        return 0.0


def get_market_info(market: str) -> Optional[dict]:
    info_rec = _MARKET_INFO_CACHE.get(market)
    ts = _now_ts()
    if info_rec and ts - info_rec.get('ts', 0) < _MARKET_INFO_TTL_SEC:
        return info_rec.get('info')
    info = safe_call(_bv.markets, {"market": market})
    if info:
        if isinstance(info, list) and len(info) > 0:
            _MARKET_INFO_CACHE[market] = {'info': info[0], 'ts': ts}
            return info[0]
        elif isinstance(info, dict) and not info.get('errorCode'):
            _MARKET_INFO_CACHE[market] = {'info': info, 'ts': ts}
            return info
    return None


def _decimals_from_str_num(s: Any) -> Optional[int]:
    try:
        if s is None:
            return None
        s = str(s)
        if '.' in s:
            return len(s.split('.', 1)[1].rstrip('0'))
        return 0
    except Exception:
        return None


def get_min_order_size(market: str) -> float:
    info = get_market_info(market)
    if info:
        min_size = info.get("minOrderSize")
        min_amount = info.get("minOrderAmount")
        return float(min_size or min_amount or 0)
    return 0.0


def get_amount_precision(market: str) -> int:
    info = get_market_info(market)
    if info:
        prec = info.get("amountPrecision")
        if prec is not None:
            try:
                return int(prec)
            except Exception as e:
                log(f"return int(prec) failed: {e}", level='debug')
        d = _decimals_from_str_num(info.get('minOrderAmount'))
        if d is not None:
            return max(0, min(8, d))
    return 8


def get_price_precision(market: str) -> int:
    info = get_market_info(market)
    if info:
        prec = info.get('pricePrecision')
        if prec is not None:
            try:
                return int(prec)
            except Exception as e:
                log(f"return int(prec) failed: {e}", level='debug')
        d = _decimals_from_str_num(info.get('tickSize'))
        if d is not None:
            return max(0, min(8, d))
    return 2


def get_amount_step(market: str) -> float:
    info = get_market_info(market)
    if info:
        step = info.get('minOrderAmount')
        if step is not None:
            try:
                return float(step)
            except Exception as e:
                log(f"return float(step) failed: {e}", level='debug')
    prec = get_amount_precision(market)
    return float(10 ** (-prec))


def get_price_step(market: str) -> float:
    info = get_market_info(market)
    if info:
        step = info.get('tickSize')
        if step is not None:
            try:
                return float(step)
            except Exception as e:
                log(f"return float(step) failed: {e}", level='debug')
    prec = get_price_precision(market)
    return float(10 ** (-prec))


def normalize_amount(market: str, amount: float) -> float:
    try:
        step = get_amount_step(market)
        prec = get_amount_precision(market)
        if not step or step <= 0:
            return float(Decimal(str(amount)).quantize(
                Decimal('1.' + '0' * prec), rounding=ROUND_DOWN))
        d_amt = Decimal(str(amount))
        d_step = Decimal(str(step))
        units = (d_amt / d_step).to_integral_value(rounding=ROUND_DOWN)
        norm = units * d_step
        norm = norm.quantize(d_step, rounding=ROUND_DOWN)
        if prec is not None and prec >= 0:
            norm = norm.quantize(Decimal('1.' + '0' * prec), rounding=ROUND_DOWN)
        return float(norm)
    except Exception as e:
        log(f"[normalize_amount] Error for {market}, amount={amount}: {e}", level='warning')
        return max(0.0, float(amount))


def normalize_price(market: str, price: float) -> float:
    try:
        step = get_price_step(market)
        if not step or step <= 0:
            prec = get_price_precision(market)
            return float(Decimal(str(price)).quantize(
                Decimal('1.' + '0' * prec), rounding=ROUND_DOWN))
        d_px = Decimal(str(price))
        d_step = Decimal(str(step))
        units = (d_px / d_step).to_integral_value(rounding=ROUND_DOWN)
        norm = units * d_step
        return float(norm.quantize(d_step, rounding=ROUND_DOWN))
    except Exception:
        return float(price)


# ===================================================================
# OTHER API CALLS
# ===================================================================

def get_supported_markets() -> List[str]:
    markets = safe_call(_bv.markets, {})
    if not isinstance(markets, list):
        log(f"get_supported_markets: invalid response type {type(markets)}, using empty list", level='warning')
        return []
    return [m['market'] for m in markets if isinstance(m, dict) and m.get('status') == 'trading']


def get_24h_volume_eur(market: str) -> Optional[float]:
    try:
        ticker = safe_call(_bv.ticker24h, {'market': market})
        if isinstance(ticker, list):
            ticker = ticker[0] if ticker else None
        if not isinstance(ticker, dict):
            return None
        volume_quote = ticker.get('volumeQuote')
        if volume_quote is not None:
            return float(volume_quote)
        volume_base = ticker.get('volume')
        last_price = ticker.get('last') or ticker.get('price') or ticker.get('open')
        if volume_base is None or last_price is None:
            return None
        return float(volume_base) * float(last_price)
    except Exception as exc:
        log(f"Kon 24h-volume niet ophalen voor {market}: {exc}", level='warning')
        return None
