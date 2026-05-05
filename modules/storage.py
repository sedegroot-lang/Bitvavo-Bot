"""Lightweight TinyDB-backed storage layer with JSON migration helpers."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from threading import RLock
from typing import Iterable, List, Optional, Sequence

from tinydb import TinyDB
from tinydb.middlewares import CachingMiddleware
from tinydb.storages import JSONStorage

from modules.logging_utils import log

# Windows inter-process mutex for file locking
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    CreateMutexW = kernel32.CreateMutexW
    CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    CreateMutexW.restype = wintypes.HANDLE

    ReleaseMutex = kernel32.ReleaseMutex
    ReleaseMutex.argtypes = [wintypes.HANDLE]
    ReleaseMutex.restype = wintypes.BOOL

    WaitForSingleObject = kernel32.WaitForSingleObject
    WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    WaitForSingleObject.restype = wintypes.DWORD

    CloseHandle = kernel32.CloseHandle
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL

    WAIT_OBJECT_0 = 0
    WAIT_TIMEOUT = 0x00000102
    INFINITE = 0xFFFFFFFF
else:
    # Non-Windows platforms: no-op mutex (thread lock is sufficient)
    CreateMutexW = None

__all__ = [
    "StorageManager",
    "get_manager",
    "configure",
    "reset",
    "fetch_all",
    "replace_all",
    "append_many",
    "migrate_json_dataset",
]


class FileMutex:
    """Windows inter-process file mutex for safe concurrent access."""

    def __init__(self, name: str, timeout_ms: int = 5000):
        self.name = name
        self.timeout_ms = timeout_ms
        self.handle = None

    def __enter__(self):
        if sys.platform != "win32" or CreateMutexW is None:
            return self

        # Create global mutex name (safe for Windows)
        safe_name = self.name.replace(".", "_").replace("-", "_").replace("/", "_").replace("\\", "_")
        mutex_name = f"Global\\BitvavoStorage_{safe_name}"

        # Create or open the mutex
        self.handle = CreateMutexW(None, False, mutex_name)
        if not self.handle:
            log(f"storage: failed to create mutex {mutex_name}", level="warning")
            return self

        # Wait for mutex ownership (with timeout to prevent deadlock)
        result = WaitForSingleObject(self.handle, self.timeout_ms)
        if result != WAIT_OBJECT_0:
            if result == WAIT_TIMEOUT:
                log(f"storage: mutex timeout for {self.name}", level="warning")
            else:
                log(f"storage: failed to acquire mutex {self.name}, result={result}", level="warning")

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if sys.platform != "win32" or not self.handle:
            return False

        try:
            ReleaseMutex(self.handle)
            CloseHandle(self.handle)
        except Exception as e:
            log(f"storage: error releasing mutex {self.name}: {e}", level="warning")

        self.handle = None
        return False


class StorageManager:
    """Owns TinyDB instances and provides serialized access helpers."""

    def __init__(self, root: Optional[Path] = None) -> None:
        base = root or Path(os.getenv("BOT_STORAGE_ROOT", "data"))
        self.root = Path(base)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._db_cache: dict[str, TinyDB] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_db(self, name: str) -> TinyDB:
        key = name.lower().strip()
        with self._lock:
            db = self._db_cache.get(key)
            if db is not None:
                return db
            path = self.root / f"{key}.tinydb.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                db = TinyDB(path, storage=CachingMiddleware(JSONStorage))
            except json.JSONDecodeError:
                # Corrupted TinyDB JSON file (partial write or stray bytes).
                # Rotate the corrupted file and start with a fresh DB to
                # avoid crashing writers that attempt to mirror JSON files.
                try:
                    ts = int(time.time())
                    corrupt_path = path.with_name(f"{path.name}.corrupt.{ts}")
                    path.replace(corrupt_path)
                    log(f"storage: rotated corrupted tinydb file {path} -> {corrupt_path}", level="warning")
                except Exception as e:
                    log(f"storage: failed to rotate corrupted tinydb file {path}: {e}", level="warning")
                # Create a fresh DB file
                db = TinyDB(path, storage=CachingMiddleware(JSONStorage))
            self._db_cache[key] = db
            return db

    def _table(self, name: str, table: Optional[str]):
        db = self._get_db(name)
        return db.table(table) if table else db.table("default")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def fetch_all(self, name: str, *, table: Optional[str] = None) -> List[dict]:
        tbl = self._table(name, table)
        return list(tbl.all())

    def replace_all(self, name: str, records: Sequence[dict], *, table: Optional[str] = None) -> None:
        if records is None:
            raise TypeError("records must be a sequence of dicts")
        payload = list(records)
        if any(not isinstance(item, dict) for item in payload):
            raise TypeError("records must contain dict instances")

        # Use inter-process mutex to prevent concurrent writes from duplicate processes
        with FileMutex(name):
            db = self._get_db(name)
            tbl_name = table if table else "default"
            # Perform the write with a defensive retry in case the TinyDB JSON
            # file is corrupted. If a JSON decode error occurs, rotate the
            # corrupted file and retry once with a fresh DB.
            for attempt in (1, 2):
                try:
                    tbl = db.table(tbl_name)
                    with self._lock:
                        tbl.truncate()
                        if payload:
                            tbl.insert_multiple(payload)
                        db.storage.flush()
                    return
                except json.JSONDecodeError as exc:
                    log(f"storage: JSON decode error while writing {name}: {exc}; attempt={attempt}", level="warning")
                except Exception as exc:
                    # Some TinyDB storage backends raise other exceptions on corrupt data;
                    # treat them the same as JSONDecodeError for robustness.
                    log(f"storage: error while writing {name}: {exc}; attempt={attempt}", level="warning")

                # If we get here, rotate the underlying tinydb file and recreate DB
                try:
                    path = self.root / f"{name}.tinydb.json"
                    ts = int(time.time())
                    corrupt_path = path.with_name(f"{path.name}.corrupt.{ts}")
                    if path.exists():
                        path.replace(corrupt_path)
                        log(f"storage: rotated corrupted tinydb file {path} -> {corrupt_path}", level="warning")
                    # Remove cached DB so a fresh instance will be created
                    with self._lock:
                        if name in self._db_cache:
                            try:
                                self._db_cache[name].close()
                            except Exception:
                                pass
                            del self._db_cache[name]
                    db = self._get_db(name)
                    # loop will retry once more
                except Exception as e:
                    log(f"storage: failed to rotate tinydb file for {name}: {e}", level="warning")
                    return

    def append_many(self, name: str, records: Iterable[dict], *, table: Optional[str] = None) -> None:
        payload = list(records)
        if any(not isinstance(item, dict) for item in payload):
            raise TypeError("records must contain dict instances")

        # Use inter-process mutex to prevent concurrent writes
        with FileMutex(name):
            db = self._get_db(name)
            tbl = db.table(table) if table else db.table("default")
            with self._lock:
                if payload:
                    tbl.insert_multiple(payload)
                db.storage.flush()

    def migrate_json_dataset(
        self,
        name: str,
        json_path: str,
        *,
        table: Optional[str] = None,
        force: bool = False,
    ) -> None:
        """Populate TinyDB with data from JSON file if table empty or force."""

        src = Path(json_path)
        if not src.exists():
            return
        db = self._get_db(name)
        tbl = db.table(table) if table else db.table("default")
        with self._lock:
            if not force and len(tbl) > 0:
                return
            try:
                with open(src, "r", encoding="utf-8") as fh:
                    payload = json.load(fh)
            except Exception:
                return
            tbl.truncate()
            docs: List[dict]
            if isinstance(payload, list):
                docs = [item for item in payload if isinstance(item, dict)]
            elif isinstance(payload, dict):
                docs = [payload]
            else:
                docs = []
            if docs:
                tbl.insert_multiple(docs)
            db.storage.flush()

    def close(self) -> None:
        with self._lock:
            for db in self._db_cache.values():
                db.close()
            self._db_cache.clear()


_MANAGER: Optional[StorageManager] = None


def get_manager() -> StorageManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = StorageManager()
    return _MANAGER


def configure(root: Path | str) -> StorageManager:
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.close()
    _MANAGER = StorageManager(Path(root))
    return _MANAGER


def reset() -> None:
    global _MANAGER
    if _MANAGER is not None:
        _MANAGER.close()
        _MANAGER = None


def fetch_all(name: str, *, table: Optional[str] = None) -> List[dict]:
    return get_manager().fetch_all(name, table=table)


def replace_all(name: str, records: Sequence[dict], *, table: Optional[str] = None) -> None:
    get_manager().replace_all(name, records, table=table)


def append_many(name: str, records: Iterable[dict], *, table: Optional[str] = None) -> None:
    get_manager().append_many(name, records, table=table)


def migrate_json_dataset(
    name: str,
    json_path: str,
    *,
    table: Optional[str] = None,
    force: bool = False,
) -> None:
    get_manager().migrate_json_dataset(name, json_path, table=table, force=force)
