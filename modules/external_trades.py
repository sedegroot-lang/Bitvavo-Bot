"""
External Trades Management
Provides market claim/release mechanism to prevent conflicts between trading strategies.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class ExternalTradesManager:
    """Manages external trade claims to prevent strategy conflicts."""

    def __init__(self, data_file: Path):
        self.data_file = data_file
        self.lock = threading.RLock()
        self._ensure_file()

    def _ensure_file(self):
        """Ensure data file exists."""
        if not self.data_file.exists():
            self.data_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump({"claims": {}, "last_updated": datetime.now(timezone.utc).isoformat()}, f)

    def _load(self) -> Dict[str, Any]:
        """Load claims from file."""
        try:
            with open(self.data_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {"claims": {}}
        except Exception:
            return {"claims": {}}

    def _save(self, data: Dict[str, Any]):
        """Save claims to file atomically."""
        data["last_updated"] = datetime.now(timezone.utc).isoformat()

        temp_file = self.data_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.data_file)
        except Exception as e:
            if temp_file.exists():
                temp_file.unlink()
            raise e

    def claim_market(self, market: str, source: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """
        Claim a market for exclusive trading.

        Args:
            market: Market symbol (e.g., 'BTC-EUR')
            source: Source claiming the market (e.g., 'grid', '3commas', 'manual')
            metadata: Optional metadata about the claim

        Returns:
            True if claim successful, False if already claimed
        """
        with self.lock:
            data = self._load()
            claims = data.get("claims", {})

            if market in claims:
                return False  # Already claimed

            claims[market] = {
                "source": source,
                "claimed_at": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            }

            data["claims"] = claims
            self._save(data)

            return True

    def release_market(self, market: str) -> bool:
        """
        Release a market claim.

        Args:
            market: Market symbol

        Returns:
            True if released, False if not claimed
        """
        with self.lock:
            data = self._load()
            claims = data.get("claims", {})

            if market not in claims:
                return False

            del claims[market]
            data["claims"] = claims
            self._save(data)

            return True

    def is_market_claimed(self, market: str) -> bool:
        """
        Check if a market is claimed.

        Args:
            market: Market symbol

        Returns:
            True if claimed, False otherwise
        """
        with self.lock:
            data = self._load()
            claims = data.get("claims", {})
            return market in claims

    def get_claim_info(self, market: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a market claim.

        Args:
            market: Market symbol

        Returns:
            Claim info dict or None if not claimed
        """
        with self.lock:
            data = self._load()
            claims = data.get("claims", {})
            return claims.get(market)

    def get_all_claims(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all active claims.

        Returns:
            Dictionary mapping market -> claim info
        """
        with self.lock:
            data = self._load()
            return data.get("claims", {})

    def get_claims_by_source(self, source: str) -> Dict[str, Dict[str, Any]]:
        """
        Get all claims by a specific source.

        Args:
            source: Source name (e.g., 'grid')

        Returns:
            Dictionary mapping market -> claim info for source
        """
        with self.lock:
            data = self._load()
            claims = data.get("claims", {})
            return {market: info for market, info in claims.items() if info.get("source") == source}

    def cleanup_stale_claims(self, max_age_seconds: int = 86400) -> int:
        """
        Remove stale claims older than max_age_seconds.

        Args:
            max_age_seconds: Maximum age in seconds (default 24h)

        Returns:
            Number of claims removed
        """
        now = time.time()
        removed = 0

        with self.lock:
            data = self._load()
            claims = data.get("claims", {})

            to_remove = []
            for market, info in claims.items():
                claimed_at_str = info.get("claimed_at")
                if not claimed_at_str:
                    continue

                try:
                    claimed_at = datetime.fromisoformat(claimed_at_str.replace("Z", "+00:00"))
                    age_seconds = now - claimed_at.timestamp()

                    if age_seconds > max_age_seconds:
                        to_remove.append(market)
                except Exception:
                    continue

            for market in to_remove:
                del claims[market]
                removed += 1

            if removed > 0:
                data["claims"] = claims
                self._save(data)

        return removed


# Global instance
_manager: Optional[ExternalTradesManager] = None


def get_manager(data_file: Optional[Path] = None) -> ExternalTradesManager:
    """Get or create global manager instance."""
    global _manager
    if _manager is None:
        if data_file is None:
            data_file = Path(__file__).resolve().parent.parent / "data" / "active_external_trades.json"
        _manager = ExternalTradesManager(data_file)
    return _manager


def claim_market(market: str, source: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
    """Convenience function to claim a market."""
    return get_manager().claim_market(market, source, metadata)


def release_market(market: str) -> bool:
    """Convenience function to release a market."""
    return get_manager().release_market(market)


def is_market_claimed(market: str) -> bool:
    """Convenience function to check if market is claimed."""
    return get_manager().is_market_claimed(market)


def get_claim_info(market: str) -> Optional[Dict[str, Any]]:
    """Convenience function to get claim info."""
    return get_manager().get_claim_info(market)
