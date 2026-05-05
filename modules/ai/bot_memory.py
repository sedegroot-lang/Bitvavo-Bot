"""
Lightweight local memory layer with mem0-compatible API.

Why not pip install mem0ai?
  mem0ai pulls 200+ MB of dependencies (openai client, qdrant, embedchain).
  For the bot's use-case (persisted facts about trades/markets/decisions) a
  simple JSON file with token-overlap search is sufficient and zero-dep.

API mirrors the parts of mem0 we actually use:
  m = BotMemory()
  m.add("BTC-EUR DCA werkt slecht in bear markets", user_id="bot",
        metadata={"category": "lesson", "market": "BTC-EUR"})
  results = m.search("BTC bear", user_id="bot", limit=5)
  m.get_all(user_id="bot")
  m.delete(memory_id)
  m.update(memory_id, "new text")
  m.reset(user_id="bot")

Storage: data/bot_memory.json (atomic writes, file-locked).

The bot can now store and retrieve facts across restarts WITHOUT any
external API or embedding model. Embedding-based recall can be added
later by injecting an `embedder` callable.
"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from collections import Counter
from pathlib import Path
from threading import RLock
from typing import Any, Dict, List, Optional

try:
    from modules.config import PROJECT_ROOT  # type: ignore
except Exception:  # pragma: no cover
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_STORE = Path(PROJECT_ROOT) / "data" / "bot_memory.json"

_TOKEN_RE = re.compile(r"[A-Za-z0-9\-]+")


def _tokenise(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2]


class BotMemory:
    """File-backed memory store. Thread-safe."""

    def __init__(self, store_path: Optional[Path] = None) -> None:
        self.path = Path(store_path) if store_path else DEFAULT_STORE
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._data: Dict[str, List[Dict[str, Any]]] = self._load()

    # ── persistence ──
    def _load(self) -> Dict[str, List[Dict[str, Any]]]:
        if not self.path.exists():
            return {}
        try:
            with self.path.open("r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                return {}
            return d
        except Exception:
            return {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, ensure_ascii=False, indent=2)
        # OneDrive may briefly hold a lock — retry a few times
        last_err: Optional[Exception] = None
        for attempt in range(5):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError as e:  # pragma: no cover - timing dependent
                last_err = e
                time.sleep(0.1 * (attempt + 1))
        if last_err is not None:
            raise last_err

    # ── public API (mem0-compatible) ──
    def add(
        self,
        text: str,
        user_id: str = "bot",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Add a memory. Deduplicates: if a near-identical text already exists
        for this user (Jaccard >= 0.85), the existing entry is updated rather
        than duplicated."""
        with self._lock:
            entries = self._data.setdefault(user_id, [])
            new_tokens = set(_tokenise(text))
            for e in entries:
                ex_tokens = set(_tokenise(e.get("text", "")))
                if new_tokens and ex_tokens:
                    j = len(new_tokens & ex_tokens) / max(1, len(new_tokens | ex_tokens))
                    if j >= 0.85:
                        e["text"] = text
                        e["metadata"] = {**(e.get("metadata") or {}), **(metadata or {})}
                        e["updated_at"] = time.time()
                        e["hits"] = int(e.get("hits", 0)) + 1
                        self._save()
                        return e
            entry = {
                "id": uuid.uuid4().hex[:12],
                "text": text,
                "user_id": user_id,
                "metadata": metadata or {},
                "created_at": time.time(),
                "updated_at": time.time(),
                "hits": 0,
            }
            entries.append(entry)
            self._save()
            return entry

    def search(
        self,
        query: str,
        user_id: str = "bot",
        limit: int = 5,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Token-overlap search with recency boost. Returns top-N entries."""
        with self._lock:
            entries = list(self._data.get(user_id, []))
        if not entries:
            return []

        q_tokens = Counter(_tokenise(query))
        if not q_tokens:
            return []

        now = time.time()
        scored: List[tuple[float, Dict[str, Any]]] = []
        for e in entries:
            if category and (e.get("metadata") or {}).get("category") != category:
                continue
            e_tokens = Counter(_tokenise(e.get("text", "")))
            if not e_tokens:
                continue
            # cosine-ish overlap
            common = sum(min(q_tokens[t], e_tokens[t]) for t in q_tokens if t in e_tokens)
            if common == 0:
                continue
            denom = (sum(q_tokens.values()) * sum(e_tokens.values())) ** 0.5
            if denom == 0:
                continue
            score = common / denom
            # recency boost: 1.0 for today, decay over 30d (only on matches)
            age_days = (now - float(e.get("updated_at", e.get("created_at", now)))) / 86400.0
            recency = max(0.0, 1.0 - age_days / 30.0) * 0.2
            score = score + recency
            if score > 0:
                scored.append((score, e))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, e in scored[:limit]:
            r = dict(e)
            r["score"] = round(score, 4)
            results.append(r)

        # increment hit counters for retrieved
        if results:
            with self._lock:
                ids = {r["id"] for r in results}
                for e in self._data.get(user_id, []):
                    if e["id"] in ids:
                        e["hits"] = int(e.get("hits", 0)) + 1
                self._save()
        return results

    def get_all(self, user_id: str = "bot") -> List[Dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._data.get(user_id, [])]

    def get(self, memory_id: str, user_id: str = "bot") -> Optional[Dict[str, Any]]:
        with self._lock:
            for e in self._data.get(user_id, []):
                if e["id"] == memory_id:
                    return dict(e)
        return None

    def update(self, memory_id: str, text: str, user_id: str = "bot") -> bool:
        with self._lock:
            for e in self._data.get(user_id, []):
                if e["id"] == memory_id:
                    e["text"] = text
                    e["updated_at"] = time.time()
                    self._save()
                    return True
        return False

    def delete(self, memory_id: str, user_id: str = "bot") -> bool:
        with self._lock:
            entries = self._data.get(user_id, [])
            for i, e in enumerate(entries):
                if e["id"] == memory_id:
                    entries.pop(i)
                    self._save()
                    return True
        return False

    def reset(self, user_id: Optional[str] = None) -> None:
        with self._lock:
            if user_id is None:
                self._data = {}
            else:
                self._data.pop(user_id, None)
            self._save()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            users = list(self._data.keys())
            total = sum(len(self._data[u]) for u in users)
            by_cat: Counter = Counter()
            for u in users:
                for e in self._data[u]:
                    cat = (e.get("metadata") or {}).get("category", "uncategorised")
                    by_cat[cat] += 1
        return {
            "users": users,
            "total_memories": total,
            "by_category": dict(by_cat),
            "store_path": str(self.path),
        }


# ── singleton helper ──
_singleton: Optional[BotMemory] = None


def get_memory() -> BotMemory:
    global _singleton
    if _singleton is None:
        _singleton = BotMemory()
    return _singleton
