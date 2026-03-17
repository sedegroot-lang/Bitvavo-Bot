"""Best-effort single instance guard shared by all entry points."""

from __future__ import annotations

import atexit
import os
import signal
import sys
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover - optional dependency
    psutil = None

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PID_DIR = _PROJECT_ROOT / "logs"
_PID_DIR.mkdir(exist_ok=True)
_MUTEX_HANDLES: dict[str, int] = {}


def _safe_name(name: str) -> str:
    return ''.join(ch if ch.isalnum() else '_' for ch in name)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if psutil is not None:
        try:
            return psutil.pid_exists(pid)
        except Exception:
            pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return False
    return True


def _terminate_pid(pid: int) -> None:
    if pid <= 0:
        return
    try:
        if os.name == 'nt':
            import subprocess

            subprocess.run(['taskkill', '/PID', str(pid)], capture_output=True, timeout=5)
            time.sleep(0.5)
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, timeout=5)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1)
            if _pid_alive(pid):
                os.kill(pid, signal.SIGKILL)
    except Exception:
        pass


def _cleanup_pidfile(path: Path, pid: int) -> None:
    try:
        if not path.exists():
            return
        try:
            current = int(path.read_text().strip() or '0')
        except Exception:
            current = 0
        if current == pid:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    except Exception:
        pass


def _cleanup_mutex(name: str) -> None:
    handle = _MUTEX_HANDLES.pop(name, None)
    if not handle:
        return
    try:
        import ctypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.ReleaseMutex(handle)
        kernel32.CloseHandle(handle)
    except Exception:
        pass


def _acquire_windows_mutex_or_exit(script_name: str, safe_name: str) -> None:
    if os.name != 'nt' or safe_name in _MUTEX_HANDLES:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        CreateMutexW = kernel32.CreateMutexW
        CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutexW.restype = wintypes.HANDLE

        mutex_name = f"Global\\BitvavoBot_{safe_name}"
        handle = CreateMutexW(None, True, mutex_name)
        last_error = ctypes.get_last_error()
        if not handle:
            return
        if last_error == 183:  # ERROR_ALREADY_EXISTS
            # Another process holds this mutex (Windows auto-releases on process exit)
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            print(f"[singleton] {script_name}: another instance holds the mutex, exiting.")
            sys.exit(1)
        _MUTEX_HANDLES[safe_name] = handle
        atexit.register(_cleanup_mutex, safe_name)
    except Exception:
        # Fall back to PID-file logic only
        pass


def ensure_single_instance_or_exit(script_name: str | None = None, *, allow_claim: bool = False) -> None:
    """Ensure only one instance of the given script is running."""

    if script_name is None:
        script_name = os.path.basename(sys.argv[0])

    safe_name = _safe_name(script_name)
    current_pid = os.getpid()
    pidfile_path = _PID_DIR / f"{script_name}.pid"
    lock_path = pidfile_path.with_suffix(pidfile_path.suffix + '.lock')

    _acquire_windows_mutex_or_exit(script_name, safe_name)

    for attempt in range(50):
        try:
            lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            # Remove lock if stale (>5s)
            try:
                stat = lock_path.stat()
                if time.time() - stat.st_mtime > 5:
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
            except Exception:
                pass
            time.sleep(min(0.02 * (attempt + 1), 0.5))
            continue
        try:
            if pidfile_path.exists():
                try:
                    existing = int(pidfile_path.read_text().strip() or '0')
                except Exception:
                    existing = 0
                if existing and existing != current_pid and _pid_alive(existing):
                    if allow_claim:
                        _terminate_pid(existing)
                        time.sleep(0.5)
                        continue
                    os.close(lock_fd)
                    try:
                        lock_path.unlink()
                    except FileNotFoundError:
                        pass
                    print(f"[singleton] {script_name} draait al (PID {existing}).")
                    sys.exit(1)
                if existing and not _pid_alive(existing):
                    try:
                        pidfile_path.unlink()
                    except Exception:
                        pass

            with open(pidfile_path, 'w', encoding='utf-8') as fh:
                fh.write(str(current_pid))
            atexit.register(_cleanup_pidfile, pidfile_path, current_pid)
            return
        finally:
            try:
                os.close(lock_fd)
            except Exception:
                pass
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass

    print(f"[singleton] Kon geen lock krijgen voor {script_name}. Stoppen.")
    sys.exit(1)
