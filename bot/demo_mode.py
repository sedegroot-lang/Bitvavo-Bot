"""Demo mode — replay deterministic Bitvavo API responses from fixtures.

Activated by env var ``BOT_DEMO_MODE=1`` (and optional ``BOT_DEMO_FIXTURES_DIR``).
Useful for:
  - Onboarding/tutorial without exchange credentials.
  - Reproducible CI smoke tests.
  - Demos / screenshots without exposing real PnL.

When demo mode is active, ``bot.api.safe_call`` short-circuits to canned
responses based on the wrapped function's name. Unknown calls raise so missing
fixtures are obvious.

This module is intentionally tiny and dependency-free.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures" / "demo"

_FIXTURES_CACHE: Dict[str, Any] = {}


def is_active() -> bool:
    return os.environ.get("BOT_DEMO_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def fixtures_dir() -> Path:
    override = os.environ.get("BOT_DEMO_FIXTURES_DIR")
    return Path(override) if override else DEFAULT_FIXTURES_DIR


def get_fixture(name: str) -> Optional[Any]:
    """Load `<fixtures>/<name>.json`. Cached. Returns None if missing."""
    if name in _FIXTURES_CACHE:
        return _FIXTURES_CACHE[name]
    path = fixtures_dir() / f"{name}.json"
    if not path.exists():
        _FIXTURES_CACHE[name] = None
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        _FIXTURES_CACHE[name] = data
        return data
    except Exception:
        _FIXTURES_CACHE[name] = None
        return None


def maybe_intercept(func_name: str) -> Optional[Any]:
    """Return a canned response for a known endpoint, else None."""
    if not is_active():
        return None
    # Map common Bitvavo API method names to fixture file basenames.
    mapping = {
        "balance": "balance",
        "ticker24h": "ticker24h",
        "ticker_24h": "ticker24h",
        "candles": "candles_btc",
        "book": "book_btc",
        "tickerPrice": "ticker_price",
        "markets": "markets",
        "ticker_price": "ticker_price",
    }
    fixture_name = mapping.get(func_name)
    if not fixture_name:
        return None
    return get_fixture(fixture_name)


__all__ = ["is_active", "fixtures_dir", "get_fixture", "maybe_intercept"]
