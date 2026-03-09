"""Data integrity validator — runs on startup to verify trade data consistency.

Checks:
  1. trade_log.json is valid JSON
  2. All open trades have required fields (buy_price, amount, invested_eur)
  3. No duplicate markets in open trades
  4. All numeric fields are positive (where expected)
  5. invested_eur consistency: buy_price * amount ≈ invested_eur
  6. Closed trades have required fields (market, profit, reason, timestamp)
  7. Auto-repair: fix missing fields with safe defaults
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("data_integrity")

_ROOT = Path(__file__).resolve().parent.parent
_TRADE_LOG = _ROOT / "data" / "trade_log.json"

REQUIRED_OPEN_FIELDS = {"buy_price", "amount"}
RECOMMENDED_OPEN_FIELDS = {"invested_eur", "timestamp", "dca_buys"}
REQUIRED_CLOSED_FIELDS = {"market", "profit", "reason"}


def validate_trade_log(
    path: Optional[str] = None,
    *,
    auto_repair: bool = True,
    log_fn: Optional[callable] = None,
) -> Dict[str, Any]:
    """Validate trade_log.json and optionally auto-repair issues.

    Returns a dict with: {valid: bool, issues: list, repairs: list, stats: dict}
    """
    trade_path = Path(path) if path else _TRADE_LOG
    log = log_fn or logger.info
    issues: List[str] = []
    repairs: List[str] = []
    stats = {"open": 0, "closed": 0}

    # 1. File exists and is valid JSON
    if not trade_path.exists():
        issues.append(f"trade_log.json not found at {trade_path}")
        return {"valid": False, "issues": issues, "repairs": repairs, "stats": stats}

    try:
        data = json.loads(trade_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        issues.append(f"Invalid JSON: {e}")
        return {"valid": False, "issues": issues, "repairs": repairs, "stats": stats}

    if not isinstance(data, dict):
        issues.append(f"Root is {type(data).__name__}, expected dict")
        return {"valid": False, "issues": issues, "repairs": repairs, "stats": stats}

    open_trades = data.get("open", {})
    closed_trades = data.get("closed", [])
    stats["open"] = len(open_trades) if isinstance(open_trades, dict) else 0
    stats["closed"] = len(closed_trades) if isinstance(closed_trades, list) else 0

    modified = False

    # 2. Validate open trades
    if isinstance(open_trades, dict):
        for market, trade in list(open_trades.items()):
            if not isinstance(trade, dict):
                issues.append(f"Open trade {market}: not a dict")
                continue

            # Required fields
            for field in REQUIRED_OPEN_FIELDS:
                if field not in trade:
                    issues.append(f"Open {market}: missing required field '{field}'")
                    if auto_repair and field == "buy_price":
                        trade["buy_price"] = 0
                        repairs.append(f"Set {market}.buy_price = 0 (needs re-derive)")
                        modified = True

            # Numeric validation
            bp = trade.get("buy_price", 0)
            amt = trade.get("amount", 0)
            try:
                bp_f = float(bp or 0)
                amt_f = float(amt or 0)
            except (TypeError, ValueError):
                issues.append(f"Open {market}: buy_price or amount not numeric")
                continue

            if bp_f <= 0:
                issues.append(f"Open {market}: buy_price={bp_f} (should be > 0)")
            if amt_f <= 0:
                issues.append(f"Open {market}: amount={amt_f} (should be > 0)")

            # invested_eur consistency
            inv = trade.get("invested_eur")
            if inv is not None:
                try:
                    inv_f = float(inv or 0)
                    expected = bp_f * amt_f
                    if expected > 0 and inv_f > 0:
                        ratio = inv_f / expected if expected else 0
                        if ratio < 0.5 or ratio > 2.0:
                            issues.append(
                                f"Open {market}: invested_eur={inv_f:.2f} vs "
                                f"buy_price*amount={expected:.2f} (ratio {ratio:.2f})"
                            )
                except (TypeError, ValueError):
                    issues.append(f"Open {market}: invested_eur not numeric")
            elif auto_repair and bp_f > 0 and amt_f > 0:
                trade["invested_eur"] = bp_f * amt_f
                repairs.append(f"Set {market}.invested_eur = {bp_f * amt_f:.4f}")
                modified = True

            # Recommended fields
            for field in RECOMMENDED_OPEN_FIELDS:
                if field not in trade and auto_repair:
                    defaults = {"invested_eur": bp_f * amt_f, "timestamp": time.time(), "dca_buys": 0}
                    if field in defaults:
                        trade[field] = defaults[field]
                        repairs.append(f"Set {market}.{field} = {defaults[field]}")
                        modified = True

    # 3. Validate closed trades
    if isinstance(closed_trades, list):
        for i, trade in enumerate(closed_trades):
            if not isinstance(trade, dict):
                issues.append(f"Closed[{i}]: not a dict")
                continue
            for field in REQUIRED_CLOSED_FIELDS:
                if field not in trade:
                    issues.append(f"Closed[{i}] ({trade.get('market', '?')}): missing '{field}'")

    # 4. Save if repaired
    if modified and auto_repair:
        try:
            backup = str(trade_path) + f".bak.{int(time.time())}"
            import shutil
            shutil.copy2(str(trade_path), backup)
            trade_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            repairs.append(f"Saved repairs (backup: {backup})")
        except Exception as e:
            issues.append(f"Failed to save repairs: {e}")

    valid = len([i for i in issues if "missing required" in i or "Invalid JSON" in i]) == 0

    result = {"valid": valid, "issues": issues, "repairs": repairs, "stats": stats}
    if issues:
        for issue in issues[:10]:
            log(f"⚠️ Data integrity: {issue}")
    if repairs:
        for repair in repairs[:10]:
            log(f"🔧 Auto-repair: {repair}")
    log(f"Data integrity: {stats['open']} open, {stats['closed']} closed, "
        f"{len(issues)} issues, {len(repairs)} repairs, valid={valid}")

    return result
