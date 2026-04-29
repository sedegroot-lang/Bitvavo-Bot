"""bot.ws_price_feed — WebSocket price feed scaffold.

Roadmap fase 5: replace 25s polling with sub-second push updates from the
Bitvavo WebSocket ticker stream. This is a scaffold/skeleton — gracefully
no-ops when the optional `python_bitvavo_api` websocket layer is unavailable
or when `WS_PRICE_FEED_ENABLED=false` (the default).

Design:
    feed = WSPriceFeed(markets=['BTC-EUR', 'ETH-EUR'])
    feed.start()                                 # connects in background thread
    last = feed.get_last_price('BTC-EUR')        # cached most-recent ticker
    feed.stop()

Cached prices are also exposed via a module-level snapshot so consumers (e.g.
the trailing engine) can call `latest_price(market)` without holding a feed
reference. When the feed is disabled, callers fall back to the regular REST
poll path (existing behaviour).
"""

from __future__ import annotations

import threading
import time
from typing import Dict, Iterable, Optional

from bot.shared import state

_LOCK = threading.RLock()
_LATEST: Dict[str, Dict[str, float]] = {}  # market -> {price, ts, bid, ask}
_FEED_REF: Optional['WSPriceFeed'] = None


def latest_price(market: str, max_age_s: float = 5.0) -> Optional[float]:
    """Return cached WS price if fresher than `max_age_s`, else None."""
    with _LOCK:
        snap = _LATEST.get(market)
    if not snap:
        return None
    if (time.time() - float(snap.get('ts', 0))) > max_age_s:
        return None
    p = snap.get('price')
    return float(p) if p is not None else None


def latest_book(market: str) -> Optional[Dict[str, float]]:
    with _LOCK:
        snap = _LATEST.get(market)
    if not snap:
        return None
    return {'bid': float(snap.get('bid', 0)), 'ask': float(snap.get('ask', 0))}


class WSPriceFeed:
    """Minimal WebSocket price feed — best-effort, never crashes the bot."""

    def __init__(self, markets: Iterable[str]):
        self._markets = list(markets)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws_handle = None  # underlying ws client when available

    def start(self) -> bool:
        if not bool(state.CONFIG.get('WS_PRICE_FEED_ENABLED', False)):
            state.log("WS price feed disabled (WS_PRICE_FEED_ENABLED=false)", level='debug')
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='ws-price-feed', daemon=True)
        self._thread.start()
        global _FEED_REF
        _FEED_REF = self
        return True

    def stop(self) -> None:
        self._stop.set()
        try:
            if self._ws_handle is not None and hasattr(self._ws_handle, 'closeSocket'):
                self._ws_handle.closeSocket()
        except Exception:
            pass

    def get_last_price(self, market: str) -> Optional[float]:
        return latest_price(market)

    def _on_ticker(self, message: dict) -> None:
        """Callback for each ticker tick."""
        try:
            market = message.get('market') or message.get('symbol')
            if not market:
                return
            price = message.get('lastPrice') or message.get('price')
            bid = message.get('bestBid') or message.get('bid') or 0.0
            ask = message.get('bestAsk') or message.get('ask') or 0.0
            if price is None:
                return
            with _LOCK:
                _LATEST[market] = {
                    'price': float(price),
                    'bid': float(bid or 0.0),
                    'ask': float(ask or 0.0),
                    'ts': time.time(),
                }
        except Exception as exc:
            state.log(f"WS ticker parse failed: {exc}", level='debug')

    def _run(self) -> None:
        bv = state.bitvavo
        if bv is None:
            state.log("WS feed: state.bitvavo missing, falling back to REST polling", level='warning')
            return
        try:
            ws_factory = getattr(bv, 'newWebsocket', None)
            if ws_factory is None:
                state.log("WS feed: python_bitvavo_api lacks newWebsocket(); REST polling stays in effect", level='info')
                return
            self._ws_handle = ws_factory()
            for m in self._markets:
                try:
                    self._ws_handle.subscriptionTicker(m, self._on_ticker)
                except Exception as exc:
                    state.log(f"WS feed subscribe {m} failed: {exc}", level='warning')
            state.log(f"WS price feed started for {len(self._markets)} markets", level='info')
            while not self._stop.is_set():
                self._stop.wait(1.0)
        except Exception as exc:
            state.log(f"WS feed crashed: {exc}", level='error')
