r"""
Prefetch market icons for key markets (whitelist/quarantine/watchlist/open trades) and save
them to `data/icons/{symbol}.png`.

Usage:
    .\.venv\Scripts\python.exe tools\prefetch_icons.py

This script tries the URL returned by `modules.dashboard_render.logo_url_for_market` first and
falls back to other public icon sources when necessary.
"""
import sys
from pathlib import Path
import json
import requests
import time

# ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

import modules.dashboard_render as dashboard_render

logo_url_for_market = dashboard_render.logo_url_for_market
_logo_url_candidates = getattr(dashboard_render, "logo_url_candidates", None)

if _logo_url_candidates is not None:
    logo_url_candidates = _logo_url_candidates
else:
    # Backwards-compatible default for environments missing the helper.
    def logo_url_candidates(market: str) -> list[str]:
        url = logo_url_for_market(market)
        return [url] if url else []

CONFIG_PATH = project_root / 'config' / 'bot_config.json'
TRADE_LOG_PATH = project_root / 'data' / 'trade_log.json'
ICONS_DIR = project_root / 'data' / 'icons'
ICONS_DIR.mkdir(parents=True, exist_ok=True)

COINGECKO_FALLBACKS = {
    'btc': 'https://assets.coingecko.com/coins/images/1/large/bitcoin.png?1547033579',
    'eth': 'https://assets.coingecko.com/coins/images/279/large/ethereum.png?1696501628',
    'sol': 'https://assets.coingecko.com/coins/images/4128/large/solana.png?1696510934',
    'xrp': 'https://assets.coingecko.com/coins/images/44/large/xrp-symbol-white-128.png?1696501442',
    'link': 'https://assets.coingecko.com/coins/images/877/large/chainlink-new-logo.png?1696510280',
    'atom': 'https://assets.coingecko.com/coins/images/1481/large/cosmos_hub.png?1696512633',
    'dot': 'https://assets.coingecko.com/coins/images/12171/large/polkadot.png?1696512240',
    'near': 'https://assets.coingecko.com/coins/images/10365/large/near_icon.png?1696512480',
    'algo': 'https://assets.coingecko.com/coins/images/4380/large/download.png?1696511097',
    'aave': 'https://assets.coingecko.com/coins/images/12645/large/AAVE.png?1696512452',
    'ltc': 'https://assets.coingecko.com/coins/images/2/large/litecoin.png?1547033580',
}


def _append_unique(items, *, dest: list[str], seen: set[str]) -> None:
    for entry in items or []:
        if isinstance(entry, str):
            norm = entry.strip()
            key = norm.upper()
            if norm and key not in seen:
                seen.add(key)
                dest.append(norm)


def load_market_list() -> list[str]:
    markets: list[str] = []
    seen: set[str] = set()
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as fh:
                cfg = json.load(fh)
            _append_unique(cfg.get('WHITELIST_MARKETS') or cfg.get('WHITELIST'), dest=markets, seen=seen)
            _append_unique(cfg.get('QUARANTINE_MARKETS'), dest=markets, seen=seen)
            _append_unique(cfg.get('WATCHLIST_MARKETS'), dest=markets, seen=seen)
    except Exception:
        pass

    try:
        if TRADE_LOG_PATH.exists():
            with open(TRADE_LOG_PATH, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            open_trades = data.get('open', {}) if isinstance(data, dict) else {}
            _append_unique(open_trades.keys(), dest=markets, seen=seen)
    except Exception:
        pass

    return markets


def try_fetch_and_save(market: str) -> bool:
    symbol = (market.split('-')[0] or '').lower()
    if not symbol:
        return False
    out_path = ICONS_DIR / f"{symbol}.png"
    # if already exists and non-empty, skip
    try:
        if out_path.exists() and out_path.stat().st_size > 0:
            print(f"SKIP cached: {symbol}")
            return True
    except Exception:
        pass
    tried: list[str] = []
    try:
        for candidate in logo_url_candidates(market):
            if candidate not in tried:
                tried.append(candidate)
    except Exception:
        pass
    if not tried:
        try:
            tried.append(logo_url_for_market(market))
        except Exception:
            pass
    # Ensure old cryptoicons fallback remains available (idempotent)
    fallback_ci = f"https://cryptoicons.org/api/icon/{symbol}/64"
    if fallback_ci not in tried:
        tried.append(fallback_ci)
    # CoinGecko curated fallback
    if symbol in COINGECKO_FALLBACKS:
        tried.append(COINGECKO_FALLBACKS[symbol])

    for u in tried:
        try:
            print(f"GET {u}")
            r = requests.get(u, timeout=8)
            if r.status_code == 200 and r.content:
                ctype = r.headers.get('Content-Type','')
                if 'image' in ctype or u.lower().endswith(('.png','.jpg','.svg')):
                    try:
                        out_path.write_bytes(r.content)
                        print(f"SAVED {out_path} ({len(r.content)} bytes)")
                        return True
                    except Exception as e:
                        print(f"ERR write {out_path}: {e}")
                        return False
                else:
                    print(f"SKIP non-image {u} -> {ctype}")
            else:
                print(f"NOTFOUND {u} -> {r.status_code}")
        except Exception as e:
            print(f"ERR {u} -> {e}")
    return False


def main():
    markets = load_market_list()
    if not markets:
        print("No markets found to prefetch.")
        return
    print(f"Prefetching {len(markets)} icons...")
    for m in markets:
        try:
            try_fetch_and_save(m)
        except Exception as e:
            print(f"Error for {m}: {e}")
        # small delay to be polite
        time.sleep(0.2)

if __name__ == '__main__':
    main()
