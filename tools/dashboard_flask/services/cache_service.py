"""Centralized caching service with TTL support."""
import time
from typing import Any, Optional, Dict
from dataclasses import dataclass, field
import threading


@dataclass
class CacheEntry:
    """Single cache entry with TTL."""
    value: Any
    expires_at: float
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at


class CacheService:
    """Thread-safe in-memory cache with TTL support."""
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache, returns None if expired or missing."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if entry.is_expired():
                del self._cache[key]
                return None
            return entry.value
    
    def set(self, key: str, value: Any, ttl_seconds: float = 60) -> None:
        """Set value in cache with TTL."""
        with self._lock:
            self._cache[key] = CacheEntry(
                value=value,
                expires_at=time.time() + ttl_seconds
            )
    
    def delete(self, key: str) -> bool:
        """Delete key from cache, returns True if existed."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            self._cache.clear()
    
    def get_or_set(self, key: str, factory, ttl_seconds: float = 60) -> Any:
        """Get from cache or compute and set if missing/expired."""
        value = self.get(key)
        if value is not None:
            return value
        
        # Compute new value
        value = factory()
        self.set(key, value, ttl_seconds)
        return value
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries, returns count removed."""
        with self._lock:
            now = time.time()
            expired_keys = [
                k for k, v in self._cache.items()
                if v.expires_at < now
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    @property
    def size(self) -> int:
        """Return number of entries in cache."""
        return len(self._cache)
