"""
Trade Block Reasons Collector
Centralized module for collecting and reporting why trades are blocked.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Block reason codes (machine-readable)
REASON_NO_SIGNAL = "no_signal"
REASON_LOW_SCORE = "low_score"
REASON_RSI_BLOCK = "rsi_block"
REASON_BALANCE_LOW = "balance_low"
REASON_MIN_ORDER_SIZE = "min_order_size"
REASON_OPERATOR_MISSING = "operator_missing"
REASON_API_DECIMAL_ERROR = "api_decimal_error"
REASON_FLOODGUARD_TRIGGERED = "floodguard_triggered"
REASON_PERFORMANCE_FILTER = "performance_filter"
REASON_CIRCUIT_BREAKER = "circuit_breaker"
REASON_MAX_TRADES = "max_trades"
REASON_SPREAD_TOO_WIDE = "spread_too_wide"
REASON_VOLUME_LOW = "volume_low"
REASON_EXTERNAL_TRADE = "external_trade"
REASON_WATCHLIST_DISABLED = "watchlist_disabled"
REASON_DCA_ONLY = "dca_only"
REASON_HEADROOM_LIMIT = "headroom_limit"
REASON_AI_VETO = "ai_veto"
REASON_MARKET_QUARANTINE = "market_quarantine"
REASON_TEST_MODE = "test_mode"

# Human-friendly messages
REASON_MESSAGES = {
    REASON_NO_SIGNAL: "No buy signal generated",
    REASON_LOW_SCORE: "Signal score below threshold",
    REASON_RSI_BLOCK: "RSI outside buy range",
    REASON_BALANCE_LOW: "Insufficient balance",
    REASON_MIN_ORDER_SIZE: "Order below minimum size",
    REASON_OPERATOR_MISSING: "Operator ID missing",
    REASON_API_DECIMAL_ERROR: "API decimal validation failed",
    REASON_FLOODGUARD_TRIGGERED: "Flood guard active",
    REASON_PERFORMANCE_FILTER: "Market performance filter blocked",
    REASON_CIRCUIT_BREAKER: "Circuit breaker active",
    REASON_MAX_TRADES: "Maximum open trades reached",
    REASON_SPREAD_TOO_WIDE: "Spread exceeds maximum",
    REASON_VOLUME_LOW: "Trading volume too low",
    REASON_EXTERNAL_TRADE: "Market claimed by external source",
    REASON_WATCHLIST_DISABLED: "Watchlist trading disabled",
    REASON_DCA_ONLY: "DCA-only mode active",
    REASON_HEADROOM_LIMIT: "Exposure headroom exceeded",
    REASON_AI_VETO: "AI model vetoed entry",
    REASON_MARKET_QUARANTINE: "Market in quarantine",
    REASON_TEST_MODE: "Running in test mode",
}


class TradeBlockCollector:
    """Collects and reports trade blocking reasons."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.data_file = data_dir / "trade_block_reasons.json"
        self.max_entries = 1000  # Keep last 1000 entries
        self._ensure_data_dir()

    def _ensure_data_dir(self):
        """Ensure data directory exists."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def collect_reasons(self, market: str, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Collect all blocking reasons for a market based on context.

        Args:
            market: Market symbol (e.g., 'BTC-EUR')
            context: Dictionary containing all relevant state:
                - signal_score: float
                - min_score_threshold: float
                - rsi: float
                - rsi_min: float
                - rsi_max: float
                - balance_eur: float
                - order_amount: float
                - min_order_size: float
                - has_operator_id: bool
                - performance_filter_blocked: bool
                - circuit_breaker_active: bool
                - max_trades_reached: bool
                - spread_pct: float
                - max_spread_pct: float
                - volume_24h: float
                - min_volume: float
                - is_external_trade: bool
                - is_watchlist: bool
                - watchlist_enabled: bool
                - headroom_exceeded: bool
                - ai_vetoed: bool
                - in_quarantine: bool
                - test_mode: bool

        Returns:
            List of reason dictionaries with 'code', 'message', and 'details'
        """
        reasons = []

        # Check signal score
        signal_score = context.get("signal_score", 0)
        min_score = context.get("min_score_threshold", 0)
        if signal_score < min_score:
            reasons.append(
                {
                    "code": REASON_LOW_SCORE,
                    "message": REASON_MESSAGES[REASON_LOW_SCORE],
                    "details": f"Score {signal_score:.2f} < {min_score:.2f}",
                }
            )

        # Check RSI
        rsi = context.get("rsi")
        rsi_min = context.get("rsi_min")
        rsi_max = context.get("rsi_max")
        if rsi is not None and rsi_min is not None and rsi_max is not None:
            if rsi < rsi_min or rsi > rsi_max:
                reasons.append(
                    {
                        "code": REASON_RSI_BLOCK,
                        "message": REASON_MESSAGES[REASON_RSI_BLOCK],
                        "details": f"RSI {rsi:.1f} outside range [{rsi_min:.1f}, {rsi_max:.1f}]",
                    }
                )

        # Check balance
        balance = context.get("balance_eur", 0)
        order_amount = context.get("order_amount", 0)
        if balance < order_amount:
            reasons.append(
                {
                    "code": REASON_BALANCE_LOW,
                    "message": REASON_MESSAGES[REASON_BALANCE_LOW],
                    "details": f"Balance €{balance:.2f} < order €{order_amount:.2f}",
                }
            )

        # Check minimum order size
        min_order = context.get("min_order_size", 0)
        if order_amount > 0 and order_amount < min_order:
            reasons.append(
                {
                    "code": REASON_MIN_ORDER_SIZE,
                    "message": REASON_MESSAGES[REASON_MIN_ORDER_SIZE],
                    "details": f"Order €{order_amount:.2f} < min €{min_order:.2f}",
                }
            )

        # Check operator ID
        if not context.get("has_operator_id", True):
            reasons.append(
                {
                    "code": REASON_OPERATOR_MISSING,
                    "message": REASON_MESSAGES[REASON_OPERATOR_MISSING],
                    "details": "OPERATOR_ID not configured",
                }
            )

        # Check performance filter
        if context.get("performance_filter_blocked", False):
            reasons.append(
                {
                    "code": REASON_PERFORMANCE_FILTER,
                    "message": REASON_MESSAGES[REASON_PERFORMANCE_FILTER],
                    "details": "Market filtered due to poor historical performance",
                }
            )

        # Check circuit breaker
        if context.get("circuit_breaker_active", False):
            reasons.append(
                {
                    "code": REASON_CIRCUIT_BREAKER,
                    "message": REASON_MESSAGES[REASON_CIRCUIT_BREAKER],
                    "details": "Recent performance below threshold",
                }
            )

        # Check max trades
        if context.get("max_trades_reached", False):
            reasons.append(
                {
                    "code": REASON_MAX_TRADES,
                    "message": REASON_MESSAGES[REASON_MAX_TRADES],
                    "details": "Maximum concurrent positions limit reached",
                }
            )

        # Check spread
        spread = context.get("spread_pct")
        max_spread = context.get("max_spread_pct")
        if spread is not None and max_spread is not None and spread > max_spread:
            reasons.append(
                {
                    "code": REASON_SPREAD_TOO_WIDE,
                    "message": REASON_MESSAGES[REASON_SPREAD_TOO_WIDE],
                    "details": f"Spread {spread * 100:.3f}% > max {max_spread * 100:.3f}%",
                }
            )

        # Check volume
        volume = context.get("volume_24h", 0)
        min_vol = context.get("min_volume", 0)
        if volume < min_vol:
            reasons.append(
                {
                    "code": REASON_VOLUME_LOW,
                    "message": REASON_MESSAGES[REASON_VOLUME_LOW],
                    "details": f"Volume {volume:.0f} < min {min_vol:.0f}",
                }
            )

        # Check external trade
        if context.get("is_external_trade", False):
            reasons.append(
                {
                    "code": REASON_EXTERNAL_TRADE,
                    "message": REASON_MESSAGES[REASON_EXTERNAL_TRADE],
                    "details": "Market reserved by grid/manual trading",
                }
            )

        # Check watchlist
        if context.get("is_watchlist", False) and not context.get("watchlist_enabled", True):
            reasons.append(
                {
                    "code": REASON_WATCHLIST_DISABLED,
                    "message": REASON_MESSAGES[REASON_WATCHLIST_DISABLED],
                    "details": "Watchlist market with trading disabled",
                }
            )

        # Check headroom
        if context.get("headroom_exceeded", False):
            reasons.append(
                {
                    "code": REASON_HEADROOM_LIMIT,
                    "message": REASON_MESSAGES[REASON_HEADROOM_LIMIT],
                    "details": "Maximum exposure headroom reached",
                }
            )

        # Check AI/ML veto
        if context.get("ml_veto", False) or context.get("ai_vetoed", False):
            ml_signal = context.get("ml_signal", 0)
            ml_conf = context.get("ml_confidence", 0.0)
            score_before_ml = context.get("score_before_ml", 0.0)
            details = f"ML signal={ml_signal}, confidence={ml_conf:.2f}, score_before_ml={score_before_ml:.2f}"
            reasons.append({"code": REASON_AI_VETO, "message": REASON_MESSAGES[REASON_AI_VETO], "details": details})

        # Check quarantine
        if context.get("in_quarantine", False):
            reasons.append(
                {
                    "code": REASON_MARKET_QUARANTINE,
                    "message": REASON_MESSAGES[REASON_MARKET_QUARANTINE],
                    "details": "Market temporarily quarantined",
                }
            )

        # Check test mode
        if context.get("test_mode", False):
            reasons.append(
                {
                    "code": REASON_TEST_MODE,
                    "message": REASON_MESSAGES[REASON_TEST_MODE],
                    "details": "Bot in test/dry-run mode",
                }
            )

        return reasons

    def record_block(self, market: str, reasons: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None):
        """
        Record blocking reasons to persistent storage.

        Args:
            market: Market symbol
            reasons: List of reason dictionaries from collect_reasons()
            metadata: Optional additional context
        """
        timestamp = datetime.now(timezone.utc).isoformat()

        entry = {
            "timestamp": timestamp,
            "market": market,
            "reasons": reasons,
            "reason_count": len(reasons),
            "metadata": metadata or {},
        }

        # Load existing data
        try:
            if self.data_file.exists():
                with open(self.data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            else:
                data = {"entries": [], "last_updated": timestamp}
        except Exception:
            data = {"entries": [], "last_updated": timestamp}

        # Append and trim
        entries = data.get("entries", [])
        entries.append(entry)

        # Keep only last N entries
        if len(entries) > self.max_entries:
            entries = entries[-self.max_entries :]

        data["entries"] = entries
        data["last_updated"] = timestamp

        # Write atomically
        try:
            temp_file = self.data_file.with_suffix(".tmp")
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.data_file)
        except Exception as e:
            print(f"Error recording trade block reasons: {e}")

    def get_latest_reasons(self, market: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get latest blocking reasons.

        Args:
            market: Optional filter by market
            limit: Maximum number of entries to return

        Returns:
            List of recent block entries
        """
        try:
            if not self.data_file.exists():
                return []

            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            entries = data.get("entries", [])

            # Filter by market if specified
            if market:
                entries = [e for e in entries if e.get("market") == market]

            # Return latest N
            return entries[-limit:]

        except Exception as e:
            print(f"Error reading trade block reasons: {e}")
            return []

    def get_summary_by_market(self) -> Dict[str, Dict[str, Any]]:
        """
        Get summary of latest blocking reasons grouped by market.

        Returns:
            Dictionary mapping market -> latest block info
        """
        try:
            entries = self.get_latest_reasons(limit=200)

            summary = {}
            for entry in reversed(entries):  # Process newest first
                market = entry.get("market")
                if not market or market in summary:
                    continue

                reasons = entry.get("reasons", [])
                summary[market] = {
                    "timestamp": entry.get("timestamp"),
                    "reason_count": len(reasons),
                    "primary_reason": reasons[0] if reasons else None,
                    "all_reasons": reasons,
                }

            return summary

        except Exception as e:
            print(f"Error getting block summary: {e}")
            return {}


# Global instance
_collector: Optional[TradeBlockCollector] = None


def get_collector(data_dir: Optional[Path] = None) -> TradeBlockCollector:
    """Get or create global collector instance."""
    global _collector
    if _collector is None:
        if data_dir is None:
            from pathlib import Path

            data_dir = Path(__file__).resolve().parent.parent / "data"
        _collector = TradeBlockCollector(data_dir)
    return _collector


def collect_and_record(
    market: str, context: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to collect and record reasons in one call.

    Args:
        market: Market symbol
        context: Context dictionary for collect_reasons()
        metadata: Optional metadata for record_block()

    Returns:
        List of reason dictionaries
    """
    collector = get_collector()
    reasons = collector.collect_reasons(market, context)

    if reasons:  # Only record if there are blocking reasons
        collector.record_block(market, reasons, metadata)

    return reasons
