"""Helper utilities for Streamlit dashboard rendering.

These helpers are kept free of Streamlit dependencies so they can be unit-tested
independently.
"""

from __future__ import annotations

import math
import re
from typing import Dict, Iterable, Tuple, List
import json
from pathlib import Path

# Local overrides (optional). File `data/icon_overrides.json` may contain a mapping
# of market/base symbol -> direct icon URL (useful when official asset URLs are known).
_OVERRIDES_PATH = Path("data") / "icon_overrides.json"

# Friendly symbol names to construct vendor-specific slugs (cryptologos, etc.).
_SYMBOL_NAME_OVERRIDES: Dict[str, str] = {
    'btc': 'bitcoin',
    'eth': 'ethereum',
    'sol': 'solana',
    'xrp': 'xrp',
    'link': 'chainlink',
    'atom': 'cosmos',
    'dot': 'polkadot',
    'near': 'near-protocol',
    'algo': 'algorand',
    'aave': 'aave',
    'ltc': 'litecoin',
    'inj': 'injective',
    'mira': 'mira',
    'om': 'mantra',
    'vet': 'vechain',
    'cake': 'pancakeswap',
    'uni': 'uniswap',
    'snx': 'synthetix',
    'mana': 'decentraland',
    'arb': 'arbitrum',
    'op': 'optimism',
    'bnb': 'binance-coin',
    'avax': 'avalanche',
    'matic': 'polygon',
    'ftm': 'fantom',
    'ada': 'cardano',
    'doge': 'dogecoin',
    'shib': 'shiba-inu',
    'xlm': 'stellar',
    'etc': 'ethereum-classic',
    'sand': 'the-sandbox',
    'ape': 'apecoin',
    'rune': 'thorchain',
    'ldo': 'lido-dao',
    'pyth': 'pyth-network',
    'sei': 'sei',
    'sui': 'sui',
    'pepe': 'pepe',
    'bonk': 'bonk',
    'grt': 'the-graph',
    'ens': 'ethereum-name-service',
    'fil': 'filecoin',
    'hnt': 'helium',
    'rose': 'oasis-network',
    'kas': 'kaspa',
}

# CoinMarketCap numeric IDs for stable icon URLs (`https://s2.coinmarketcap.com/...`).
_COINMARKETCAP_IDS: Dict[str, int] = {
    'btc': 1,
    'eth': 1027,
    'sol': 5426,
    'xrp': 52,
    'link': 1975,
    'atom': 3794,
    'dot': 6636,
    'near': 6535,
    'algo': 4030,
    'aave': 7278,
    'ltc': 2,
    'inj': 7226,
    'om': 6536,
    'vet': 3077,
    'cake': 7186,
    'uni': 7083,
    'snx': 2586,
    'mana': 1966,
    'arb': 11841,
    'op': 11840,
    'bnb': 1839,
    'avax': 5805,
    'matic': 3890,
    'ftm': 3513,
    'ada': 2010,
    'doge': 74,
    'shib': 5994,
    'xlm': 512,
    'etc': 1321,
    'sand': 6210,
    'ape': 18876,
    'rune': 4157,
    'ldo': 8000,
    'grt': 6719,
    'ens': 13855,
    'fil': 2280,
    'hnt': 5665,
    'rose': 7653,
    'kas': 20396,
}

_CRYPTOLOGOS_VERSION = "032"


def calculate_trade_financials(
    buy_price: float | None,
    amount: float | None,
    live_price: float | None,
    invested_override: float | None = None,
) -> Tuple[float, float, float, float]:
    """Return invested EUR, current EUR value, P/L EUR, P/L %."""
    buy = float(buy_price or 0.0)
    amt = float(amount or 0.0)
    if invested_override is not None:
        invested = float(invested_override)
    else:
        invested = buy * amt

    if live_price is None:
        current_value = math.nan
    else:
        current_value = float(live_price) * amt

    pnl_eur = math.nan
    pnl_pct = math.nan
    if invested > 0 and not math.isnan(current_value):
        pnl_eur = current_value - invested
        pnl_pct = (pnl_eur / invested) * 100.0
    elif not math.isnan(current_value):
        pnl_eur = current_value
        pnl_pct = math.nan

    return invested, current_value, pnl_eur, pnl_pct


def determine_status_badge(
    pnl_eur: float | None,
    trailing_active: bool,
) -> Tuple[str, str]:
    """Return (label, css_class) for the status badge."""
    if trailing_active:
        return "Trailing actief", "badge-trailing"
    if pnl_eur is None or math.isnan(pnl_eur):
        return "Neutraal", "badge-neutral"
    if pnl_eur > 0:
        return "Winst", "badge-profit"
    if pnl_eur < 0:
        return "Verlies", "badge-loss"
    return "Break-even", "badge-neutral"


def summarize_totals(trade_contexts: Iterable[Dict[str, float]]) -> Dict[str, float]:
    """Aggregate invested/current/pnl totals for summary metrics."""
    invested_total = 0.0
    current_total = 0.0
    pnl_total = 0.0
    for ctx in trade_contexts:
        invested = float(ctx.get("invested_eur") or 0.0)
        current_value = ctx.get("current_value_eur")
        pnl_eur = ctx.get("pnl_eur")
        invested_total += invested
        if current_value is not None and not math.isnan(current_value):
            current_total += float(current_value)
        if pnl_eur is not None and not math.isnan(pnl_eur):
            pnl_total += float(pnl_eur)
    return {
        "invested_total": invested_total,
        "current_total": current_total,
        "pnl_total": pnl_total,
        "pnl_pct": (pnl_total / invested_total * 100.0) if invested_total else math.nan,
    }


_CARD_ID_PATTERN = re.compile(r"[^a-z0-9]+")


def _normalize_symbol(market: str) -> str:
    try:
        return (market.split('-')[0] or '').lower()
    except Exception:
        return str(market or '').lower()


def _slugify_name(text: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(text or '').lower()).strip('-') or 'unknown'


def _cryptologos_slug(symbol: str) -> str | None:
    sym = symbol.lower()
    name = _SYMBOL_NAME_OVERRIDES.get(sym)
    if not name:
        return None
    return f"{_slugify_name(name)}-{sym}"


def logo_url_candidates(market: str) -> List[str]:
    """Return preferred icon URL candidates ordered by quality."""
    symbol = _normalize_symbol(market)
    candidates: List[str] = []

    cmc_id = _COINMARKETCAP_IDS.get(symbol)
    if cmc_id:
        candidates.append(f"https://s2.coinmarketcap.com/static/img/coins/64x64/{cmc_id}.png")

    slug = _cryptologos_slug(symbol)
    if slug:
        base = f"https://cryptologos.cc/logos/{slug}-logo"
        candidates.append(f"{base}.png?v={_CRYPTOLOGOS_VERSION}")
        candidates.append(f"{base}.svg?v={_CRYPTOLOGOS_VERSION}")

    candidates.append(f"https://static.bitvavo.com/images/markets/{symbol}.png")
    candidates.append(f"https://static.bitvavo.com/images/markets/{symbol}-eur.png")
    candidates.append(f"https://cryptoicons.org/api/icon/{symbol}/64")

    uniq: List[str] = []
    for url in candidates:
        if url and url not in uniq:
            uniq.append(url)
    return uniq


def make_card_identifier(market: str) -> str:
    """Return a stable, DOM-safe identifier for a market card."""
    slug = _CARD_ID_PATTERN.sub("-", market.lower()).strip("-")
    if not slug:
        slug = "unknown-market"
    return f"trade-card-{slug}"


def logo_url_for_market(market: str) -> str:
    """Return a reasonable logo URL for a Bitvavo market."""
    base_symbol = _normalize_symbol(market) or "unknown"
    # Try local overrides first (exact market, then base symbol).
    try:
        if _OVERRIDES_PATH.exists():
            with _OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
                overrides = json.load(fh)
            lookup_keys = [
                market,
                market.upper() if isinstance(market, str) else market,
                market.lower() if isinstance(market, str) else market,
                base_symbol,
                base_symbol.upper(),
            ]
            for key in lookup_keys:
                if isinstance(key, str) and key in overrides:
                    return overrides[key]
    except Exception:
        pass

    candidates = logo_url_candidates(market)
    if candidates:
        return candidates[0]
    return f"https://cryptoicons.org/api/icon/{base_symbol}/64"
