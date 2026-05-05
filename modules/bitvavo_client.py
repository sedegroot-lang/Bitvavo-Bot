import logging
import os
import time
from typing import Dict, Optional

from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

# Load .env by default
load_dotenv()

logger = logging.getLogger(__name__)

_cached_client: Optional[Bitvavo] = None

# FAANG-level retry configuration
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds
RETRY_BACKOFF_MAX = 10.0  # seconds


def _should_retry(error: Exception) -> bool:
    """Determine if error is retryable (network/timeout/rate-limit)."""
    error_str = str(error).lower()
    retryable_patterns = [
        "timeout",
        "connection",
        "network",
        "rate limit",
        "too many requests",
        "service unavailable",
        "503",
        "502",
        "504",
        "reset by peer",
        "temporary",
        "retry",
        "busy",
    ]
    return any(pattern in error_str for pattern in retryable_patterns)


def _retry_with_backoff(func, *args, max_retries: int = MAX_RETRIES, **kwargs):
    """Execute function with exponential backoff retry on transient errors."""
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            if attempt < max_retries and _should_retry(e):
                delay = min(RETRY_BACKOFF_BASE * (2**attempt), RETRY_BACKOFF_MAX)
                logger.warning(
                    f"Retryable error on attempt {attempt + 1}/{max_retries + 1}: {e}. Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                break
    raise last_error


def get_bitvavo(config: Dict = None, require_operator: bool = False) -> Optional[Bitvavo]:
    """Return a cached Bitvavo client configured from environment and optional config dict.

    - config: optional dict with keys like 'API_KEY', 'API_SECRET', 'BITVAVO_OPERATOR_ID'
    - require_operator: if True, raises ValueError when OPERATORID not present

    The function caches the created Bitvavo client so multiple imports reuse the same instance.
    """
    global _cached_client
    if _cached_client is not None:
        return _cached_client

    cfg = config or {}
    api_key = os.getenv("BITVAVO_API_KEY") or cfg.get("API_KEY") or cfg.get("BITVAVO_API_KEY")
    api_secret = os.getenv("BITVAVO_API_SECRET") or cfg.get("API_SECRET") or cfg.get("BITVAVO_API_SECRET")
    operator_id = os.getenv("BITVAVO_OPERATOR_ID") or cfg.get("BITVAVO_OPERATOR_ID")

    if not api_key or not api_secret:
        # No credentials available
        return None

    params = {
        "APIKEY": api_key,
        "APISECRET": api_secret,
        "ACCESSWINDOW": int(cfg.get("ACCESSWINDOW", 10000)),
        "RESTURL": cfg.get("RESTURL", "https://api.bitvavo.com/v2"),
    }
    if operator_id:
        params["OPERATORID"] = operator_id
    else:
        if require_operator:
            raise ValueError("BITVAVO_OPERATOR_ID not provided but is required")

    _cached_client = Bitvavo(params)
    return _cached_client


def place_market_order(market: str, amount: object, side: str = "sell", bv: Optional[Bitvavo] = None) -> object:
    """Place a market order using the Bitvavo client with retry logic and multiple fallbacks.

    FAANG-level: Implements exponential backoff retry for transient errors.
    Returns the raw response on success or a dict with 'error' on failure.
    """
    try:
        if bv is None:
            bv = get_bitvavo()
        if not bv:
            return {"error": "Bitvavo client niet geconfigureerd"}

        amt_str = str(amount)
        attempts = []

        # Define order placement with retry wrapper
        def _place_order():
            # Try common method signatures in order
            if hasattr(bv, "order"):
                return bv.order(market, {"amount": amt_str, "side": side, "orderType": "market"})
            elif hasattr(bv, "placeOrder"):
                return bv.placeOrder(market, side, "market", {"amount": amt_str})
            else:
                raise RuntimeError("No compatible order method found on Bitvavo client")

        # Execute with retry
        try:
            return _retry_with_backoff(_place_order, max_retries=MAX_RETRIES)
        except Exception as e:
            attempts.append(("primary_order", str(e)))
            logger.error(f"Order placement failed after {MAX_RETRIES} retries: {e}")

        # Fallback methods (without retry for compatibility attempts)
        try:
            if hasattr(bv, "order"):
                # some clients accept a single dict
                return bv.order({"market": market, "amount": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("order(dict)", str(e)))

        try:
            if hasattr(bv, "createOrder"):
                return bv.createOrder({"market": market, "amount": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("createOrder", str(e)))

        try:
            if hasattr(bv, "create_order"):
                return bv.create_order({"market": market, "amount": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("create_order", str(e)))

        try:
            if hasattr(bv, "market"):
                return bv.market({"market": market, "amount": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("market", str(e)))

        # try alternative param name 'size'
        try:
            if hasattr(bv, "order"):
                return bv.order(market, {"size": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("order(market, {size})", str(e)))

        # Generic HTTP-style post if exposed by client
        try:
            if hasattr(bv, "post"):
                return bv.post("/v2/orders", {"market": market, "amount": amt_str, "side": side, "orderType": "market"})
        except Exception as e:
            attempts.append(("post(/v2/orders)", str(e)))

        # If we reach here, no method worked
        return {"error": "Onbekende Bitvavo client interface", "attempts": attempts}
    except Exception as e:
        return {"error": f"Plaatsen order mislukt: {e}"}


def inspect_client_methods(bv: Optional[Bitvavo] = None) -> dict:
    """Return a dict with basic introspection of the Bitvavo client for debugging.

    Keys: 'has_client' (bool), 'attrs' (list of attribute names), 'methods' (subset that are callables).
    """
    out = {"has_client": False, "attrs": [], "methods": []}
    try:
        if bv is None:
            bv = _cached_client or get_bitvavo()
        if not bv:
            return out
        out["has_client"] = True
        attrs = dir(bv)
        out["attrs"] = [a for a in attrs]
        out["methods"] = [a for a in attrs if callable(getattr(bv, a, None))]
        return out
    except Exception:
        return out
