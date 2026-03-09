"""Prefetch coin icons from CoinMarketCap.

This script attempts to fetch the coin page at `https://coinmarketcap.com/currencies/{slug}/`
and extracts the `og:image` meta tag to find the official logo URL. It saves the
image into `data/icons/{symbol}.png` so the dashboard can embed or serve it.

Usage:
  ./.venv/Scripts/python.exe tools/prefetch_icons_cmc.py

By default the script will read `data/trade_log.json` (open trades) to derive symbols.
You can also provide a JSON file `data/cmc_slug_overrides.json` mapping symbols
to explicit CMC slugs when the symbol does not equal the slug (e.g. LINK -> chainlink).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Dict, Iterable

try:
    import requests
except Exception as exc:
    print("Error: requests library required. Install with: pip install requests")
    raise

# Bitvavo API endpoint for markets
BITVAVO_MARKETS_URL = "https://api.bitvavo.com/v2/markets"


DATA_DIR = Path("data")
CONFIG_DIR = Path("config")
ICONS_DIR = DATA_DIR / "icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

TRADE_LOG = DATA_DIR / "trade_log.json"
BOT_CONFIG = CONFIG_DIR / "bot_config.json"
OVERRIDES_PATH = DATA_DIR / "cmc_slug_overrides.json"


def load_whitelist_markets() -> list[str]:
    """Load WHITELIST_MARKETS from bot_config.json."""
    if not BOT_CONFIG.exists():
        return []
    try:
        with BOT_CONFIG.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        whitelist = data.get("WHITELIST_MARKETS") or []
        return [m for m in whitelist if isinstance(m, str)]
    except Exception:
        return []


def load_open_markets() -> Iterable[str]:
    if not TRADE_LOG.exists():
        return []
    try:
        with TRADE_LOG.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return []
    # Expect format: {"open": [ {"market": "XRP-EUR"}, ... ], ... }
    open_list = data.get("open") or []
    markets = []
    for it in open_list:
        m = it.get("market") if isinstance(it, dict) else None
        if m:
            markets.append(m)
    return markets


def load_overrides() -> Dict[str, str]:
    if not OVERRIDES_PATH.exists():
        return {}
    try:
        with OVERRIDES_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


_OG_IMAGE_RE = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"', re.I)


def guess_candidate_slugs(symbol: str, overrides: Dict[str, str]) -> Iterable[str]:
    # If overrides contains the symbol -> slug mapping, use it first.
    if symbol in overrides:
        yield overrides[symbol]
    # common heuristics: symbol lowercased
    yield symbol.lower()
    # try with full name patterns: for example 'xrp' -> 'ripple' is ambiguous so user should override
    # try symbol as lowercase again, and symbol prefixed/suffixed patterns (best-effort)
    yield f"{symbol.lower()}"


def extract_og_image(html: str) -> str | None:
    m = _OG_IMAGE_RE.search(html)
    if m:
        return m.group(1)
    return None


def fetch_and_save(url: str, target: Path) -> bool:
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200 and resp.content:
            target.write_bytes(resp.content)
            return True
    except Exception:
        return False
    return False


def run_for_markets(markets: Iterable[str]) -> None:
    overrides = load_overrides()
    seen = set()
    for market in markets:
        try:
            symbol = (market.split("-")[0] or "").upper()
        except Exception:
            continue
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        print(f"Processing symbol: {symbol}")
        target = ICONS_DIR / f"{symbol.lower()}.png"
        # skip if exists
        if target.exists() and target.stat().st_size > 0:
            print(f" - Already cached: {target}")
            continue
        candidates = list(guess_candidate_slugs(symbol, overrides))
        found = False
        for slug in candidates:
            page_url = f"https://coinmarketcap.com/currencies/{slug}/"
            print(f" - trying slug: {slug} -> {page_url}")
            try:
                r = requests.get(page_url, timeout=12)
                if r.status_code != 200:
                    print(f"   status {r.status_code}")
                    continue
                img_url = extract_og_image(r.text)
                if not img_url:
                    print("   no og:image found")
                    continue
                print(f"   found img: {img_url}")
                # Some OG URLs are relative protocol-less or end with .svg/.png/.webp
                if img_url.startswith("//"):
                    img_url = "https:" + img_url
                if fetch_and_save(img_url, target):
                    print(f"   saved to {target}")
                    found = True
                    break
                else:
                    print("   failed to download image")
            except Exception as exc:
                print(f"   error: {exc}")
        if not found:
            print(f" - No icon found for {symbol}. Consider adding mapping in {OVERRIDES_PATH}")


def load_bitvavo_markets() -> list[str]:
    """Load all Bitvavo markets via public API."""
    try:
        resp = requests.get(BITVAVO_MARKETS_URL, timeout=15)
        if resp.status_code != 200:
            print(f"Bitvavo API error: {resp.status_code}")
            return []
        data = resp.json()
        # Expect format: [{"market": "BTC-EUR", ...}, ...]
        return [m.get("market") for m in data if m.get("market")]
    except Exception as exc:
        print(f"Bitvavo API error: {exc}")
        return []


def main() -> int:
    # Probeer eerst alle Bitvavo markets te laden
    all_markets = load_bitvavo_markets()
    if all_markets:
        print(f"Prefetching icons voor {len(all_markets)} Bitvavo coins...")
        run_for_markets(all_markets)
        return 0
    # First, load whitelist markets from bot_config.json
    whitelist = load_whitelist_markets()
    if whitelist:
        print(f"Found {len(whitelist)} markets in WHITELIST_MARKETS from bot_config.json")
        run_for_markets(whitelist)
        return 0
    # Fallback to open markets from trade_log.json
    markets = load_open_markets()
    if not markets:
        print("No whitelist or open markets found. You can provide a custom list on the command line.")
        # allow manual symbols via args
        args = [a.upper() for a in sys.argv[1:]]
        if not args:
            return 0
        markets = [f"{a}-EUR" for a in args]
    run_for_markets(markets)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
