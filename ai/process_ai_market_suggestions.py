"""Process AI market suggestions and apply guardrail checks.

Reads `ai/ai_market_suggestions.json` which should contain a list under key
`suggestions` with items like `{"market": "LINK-EUR", "reason": "modelX", "ts": 12345}`.

If a suggestion passes guardrails and config allows auto-apply, the script
adds the market to the whitelist in `config/bot_config.json`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SUG_FILE = PROJECT_ROOT / "ai" / "ai_market_suggestions.json"
PROCESSED_FILE = PROJECT_ROOT / "ai" / "ai_market_suggestions_processed.json"

from modules.ai_markets import add_market_to_whitelist, market_allowed_to_auto_apply
from modules.logging_utils import log
from modules.watchlist_manager import get_watchlist_settings, queue_market_for_watchlist


def load_suggestions():
    if not SUG_FILE.exists():
        return []
    try:
        with SUG_FILE.open("r", encoding="utf-8") as fh:
            doc = json.load(fh)
        return doc.get("suggestions", []) if isinstance(doc, dict) else []
    except Exception:
        return []


def save_processed(records):
    try:
        with PROCESSED_FILE.open("w", encoding="utf-8") as fh:
            json.dump({"processed": records, "ts": int(time.time())}, fh, indent=2)
    except Exception:
        pass


def main():
    return process_pending_suggestions()


def process_pending_suggestions() -> list:
    """Process pending suggestions from disk.

    Returns a list of processed records (same format as written to the processed file).
    """
    suggestions = load_suggestions()
    processed = []
    cfg = None
    watch_settings = None
    for s in suggestions:
        market = s.get("market") if isinstance(s, dict) else None
        if not market:
            continue
        ok = market_allowed_to_auto_apply(market, cfg)
        if ok:
            watch_settings = watch_settings or get_watchlist_settings()
            if watch_settings.get("enabled", True):
                queued = queue_market_for_watchlist(
                    market,
                    reason=s.get("reason", "ai-scan"),
                    source="ai-supervisor",
                    cfg=None,
                )
                status = "watchlisted" if queued else "failed"
                log(f"process_ai_market_suggestions: {market} -> {status}")
            else:
                ok2 = add_market_to_whitelist(market)
                status = "applied" if ok2 else "failed"
                log(f"process_ai_market_suggestions: {market} -> {status}")
        else:
            status = "rejected"
            log(f"process_ai_market_suggestions: {market} -> rejected by guardrails")
        processed.append({"market": market, "status": status, "reason": s.get("reason"), "ts": s.get("ts")})
    save_processed(processed)
    return processed


if __name__ == "__main__":
    main()
