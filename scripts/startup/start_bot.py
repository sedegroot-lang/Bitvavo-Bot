"""Coordineer het starten van botprocessen vanuit één command.

Gebruik:
    python start_bot.py                 # start monitor -> trailing bot, ai_supervisor, auto_retrain
    python start_bot.py --mode direct   # start trailing_bot zonder monitor
    python start_bot.py --no-dashboard  # dashboard overslaan indien gewenst

Stoppen met Ctrl+C; het script sluit alle subprocessen netjes af.
"""



from __future__ import annotations
from pathlib import Path
import datetime
import os
import sys
import subprocess
import time
import signal
import threading
from typing import Optional, Iterable
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # Go up to project root
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable
START_BOT_LOG_DIR = BASE_DIR / "logs" / "start_bot"
START_BOT_LOG_DIR.mkdir(parents=True, exist_ok=True)

if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# CRITICAL: Set these environment variables BEFORE any subprocess calls
# to ensure Windows multiprocessing uses venv Python instead of system Python
os.environ["BITVAVO_PYTHON_PATH"] = PYTHON
os.environ["PYTHONEXECUTABLE"] = PYTHON  # Used by multiprocessing on Windows
os.environ["__PYVENV_LAUNCHER__"] = PYTHON  # macOS/Linux venv hint
os.environ["PYTHONIOENCODING"] = "utf-8"  # ensure subprocess stdout/stderr are UTF-8 on Windows

HOUSEKEEPING_SCRIPT = BASE_DIR / "tools" / "archive_trade_backups.py"
HOUSEKEEPING_INTERVAL = 24 * 60 * 60
BOT_LOG_PATTERN = "bot_log.txt.*"
BOT_LOG_ARCHIVE = "archive/logs/bot"
DEBUG_GUARD = os.environ.get("START_BOT_DEBUG_GUARD") == "1"

# Windows named-mutex single-instance guard (best-effort, avoids double-start via wrappers)
_mutex = None
def _acquire_windows_mutex(name: str) -> Optional[int]:
    """Try to create a named mutex. Return handle (int) when acquired, or None when mutex already exists or on error.
    This avoids races where a launcher/wrapper spawns two python processes that both would proceed.
    """
    if os.name != 'nt':
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        CreateMutex = kernel32.CreateMutexW
        CreateMutex.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        CreateMutex.restype = wintypes.HANDLE
        handle = CreateMutex(None, False, name)
        if not handle:
            return None
        ERROR_ALREADY_EXISTS = 183
        err = ctypes.get_last_error()
        if err == ERROR_ALREADY_EXISTS:
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            return None
        return int(handle)
    except Exception:
        return None

# Import dotenv loader
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        pass
try:
    import psutil as _psutil
except Exception:
    _psutil = None
DEBUG_LOG = (Path(__file__).resolve().parent / "start_bot_debug.log")
def debug_log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    try:
        with open(DEBUG_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {msg}\n")
    except Exception:
        pass

# Singleton enforcement using Windows Mutex
sys.path.insert(0, str(BASE_DIR / "scripts" / "helpers"))
try:
    from single_instance import ensure_single_instance_or_exit  # type: ignore
except ImportError:
    def ensure_single_instance_or_exit(*args, **kwargs):
        pass

import argparse
import json

from scheduler.hodl_dca import HodlScheduler


# ...existing code...



# ...existing code...



def _release_windows_mutex(handle: int) -> None:
    try:
        if not handle:
            return
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        try:
            kernel32.ReleaseMutex(handle)
        except Exception:
            pass
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
    except Exception:
        pass


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if _psutil is not None:
        try:
            return _psutil.pid_exists(pid)
        except Exception:
            return False
    if os.name == "nt":
        try:
            proc = subprocess.run(
                ["tasklist", "/NH", "/FI", f"PID eq {pid}"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode != 0:
                return False
            return str(pid) in proc.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception:
        return False


def _launched_from_vscode(pid: int) -> bool:
    """Return True if the process (or any ancestor) looks like it's launched from VS Code's terminal.

    Heuristic: walk parent chain (psutil) and look for Code.exe or a powershell invocation that runs
    VS Code's shellIntegration.ps1. If psutil isn't available, conservatively return False.
    """
    if _psutil is None:
        return False
    try:
        cur = _psutil.Process(pid)
        checked = set()
        while cur is not None:
            try:
                exe = (cur.exe() or '').lower()
            except Exception:
                exe = ''
            try:
                cmd = ' '.join(cur.cmdline() or []).lower()
            except Exception:
                cmd = ''
            # VS Code main process
            if exe.endswith('code.exe') or 'visual studio code' in cmd:
                return True
            # VS Code terminal integration typically injects shellIntegration.ps1 into powershell
            if 'shellintegration.ps1' in cmd or 'shellintegration' in cmd:
                return True
            # powershell itself isn't definitive, but if parent is Code.exe earlier it will match
            parent = None
            try:
                parent = cur.parent()
            except Exception:
                parent = None
            if parent is None:
                break
            if parent.pid in checked:
                break
            checked.add(parent.pid)
            cur = parent
    except Exception:
        return False
    return False


class ManagedProcess:
    """Wrap een subprocess en zorg voor gecontroleerde starts/stops."""

    def __init__(self, name: str, command: Iterable[str], *, auto_restart: bool) -> None:
        self.name = name
        self.command = list(command)
        self.auto_restart = auto_restart
        self.proc: Optional[subprocess.Popen] = None
        self.restart_attempts = 0
        self.last_restart_time = 0
        # Dedicated stdout/stderr log files per managed process prevent PIPE blocking
        safe_name = ''.join(ch if ch.isalnum() or ch in ('-', '_') else '_' for ch in name)
        self.stdout_log_path = START_BOT_LOG_DIR / f"{safe_name}.stdout.log"
        self.stderr_log_path = START_BOT_LOG_DIR / f"{safe_name}.stderr.log"
        self._stdout_handle: Optional[object] = None
        self._stderr_handle: Optional[object] = None

    def _write_log_header(self, handle: Optional[object], stream_name: str) -> None:
        if not handle:
            return
        try:
            banner = f"\n===== {stream_name} restart {datetime.datetime.now(datetime.timezone.utc).isoformat()}Z =====\n"
            handle.write(banner.encode('utf-8', errors='ignore'))
            handle.flush()
        except Exception:
            pass

    def _open_log_handles(self) -> None:
        self._close_log_handles()
        try:
            self.stdout_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._stdout_handle = open(self.stdout_log_path, 'ab', buffering=0)
        except Exception:
            self._stdout_handle = None
        try:
            self.stderr_log_path.parent.mkdir(parents=True, exist_ok=True)
            self._stderr_handle = open(self.stderr_log_path, 'ab', buffering=0)
        except Exception:
            self._stderr_handle = None
        self._write_log_header(self._stdout_handle, f"{self.name} STDOUT")
        self._write_log_header(self._stderr_handle, f"{self.name} STDERR")

    def _close_log_handles(self) -> None:
        for handle_attr in ('_stdout_handle', '_stderr_handle'):
            handle = getattr(self, handle_attr, None)
            if handle:
                try:
                    handle.flush()
                except Exception:
                    pass
                try:
                    handle.close()
                except Exception:
                    pass
            setattr(self, handle_attr, None)

    def _singleton_candidate_names(self) -> list[str]:
        candidates = set()
        if self.name:
            candidates.add(self.name)
            if not self.name.endswith('.py'):
                candidates.add(f"{self.name}.py")
        if len(self.command) >= 2:
            script_arg = self.command[1]
            script_name = os.path.basename(script_arg)
            if script_name:
                candidates.add(script_name)
                stem = Path(script_name).stem
                if stem:
                    candidates.add(stem)
        return [c for c in candidates if c]

    def _wait_for_singleton_release(self, timeout: float = 10.0) -> None:
        candidates = self._singleton_candidate_names()
        if not candidates:
            return
        pid_dir = BASE_DIR / 'logs'
        try:
            pid_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        deadline = time.time() + max(timeout, 1.0)
        notified = False

        def _lock_path(pid_path: Path) -> Path:
            return Path(f"{pid_path}.lock")

        while time.time() < deadline:
            blocking = False
            for candidate in candidates:
                pid_path = pid_dir / f"{candidate}.pid"
                lock_path = _lock_path(pid_path)

                if pid_path.exists():
                    try:
                        pid = int(pid_path.read_text(encoding='utf-8').strip() or '0')
                    except Exception:
                        pid = 0
                    if pid and _pid_alive(pid):
                        blocking = True
                    else:
                        try:
                            pid_path.unlink()
                        except Exception:
                            blocking = True
                    if blocking:
                        break

                if lock_path.exists():
                    try:
                        age = time.time() - lock_path.stat().st_mtime
                    except Exception:
                        age = 0
                    if age < 1.0:
                        blocking = True
                    else:
                        try:
                            lock_path.unlink()
                        except Exception:
                            blocking = True
                    if blocking:
                        break

            if not blocking:
                return

            if not notified:
                print(f"[start_bot] Wachten tot lock/pid bestanden voor {self.name} zijn vrijgegeven...")
                debug_log(f"ManagedProcess: wachten op locks voor {self.name}")
                notified = True
            time.sleep(0.5)

        print(f"[start_bot] Waarschuwing: lock/pid bestanden voor {self.name} bleven bestaan na {timeout}s, probeer toch te herstarten.")
        debug_log(f"ManagedProcess: lock timeout voor {self.name}")

    def start(self) -> None:
        now = time.time()
        # Reset attempts if last restart was long ago
        if now - self.last_restart_time > 10:
            self.restart_attempts = 0
        self.last_restart_time = now
        debug_log(f"ManagedProcess.start: {self.name} - is_running={self.is_running()} restart_attempts={self.restart_attempts}")
        if self.is_running():
            debug_log(f"ManagedProcess.start: {self.name} draait al (pid={self.proc.pid})")
            return
        if self.restart_attempts >= 3:
            print(f"   ❌ {self.name} herhaaldelijk gefaald, gestopt")
            debug_log(f"ManagedProcess.start: {self.name} exited too many times, not restarting.")
            return
        
        # Note: We rely on each script's own ensure_single_instance_or_exit() check
        # to prevent duplicates. No need to check here as it causes race conditions.
        
        debug_log(f"ManagedProcess.start: {self.name} command={self.command}")
        
        self._wait_for_singleton_release()
        self._open_log_handles()
        # DO NOT use CREATE_NEW_PROCESS_GROUP - it can cause Windows to re-execute the script!
        # Pass environment to ensure BITVAVO_PYTHON_PATH is inherited
        env = os.environ.copy()
        self.proc = subprocess.Popen(
            self.command,
            cwd=str(BASE_DIR),
            stdout=self._stdout_handle or subprocess.DEVNULL,
            stderr=self._stderr_handle or subprocess.DEVNULL,
            env=env,
        )
        # record a start timestamp on the Popen object so ensure() can
        # detect quick exits vs long-running processes and avoid restart loops
        try:
            setattr(self.proc, 'start_time', time.time())
        except Exception:
            pass
        _display_names = {
            'monitor': '🔍 Monitor daemon',
            'ai_supervisor': '🧠 AI Supervisor',
            'auto_retrain': '📊 Auto retrain',
            'auto_backup': '💾 Auto backup',
            'flask_dashboard': '🌐 Dashboard → http://localhost:5001',
            'pairs_runner': '🔄 Pairs arbitrage',
        }
        _label = _display_names.get(self.name, self.name)
        print(f"   ✅ {_label} (pid={self.proc.pid})")
        debug_log(f"ManagedProcess.start: {self.name} gestart (pid={self.proc.pid}) cmd={self.command}")
        # Post-start verification: wait briefly and ensure the process stayed alive.
        try:
            time.sleep(0.5)
            if self.proc.poll() is not None:
                rc = self.proc.poll()
                debug_log(f"ManagedProcess.start: {self.name} exited quickly (pid={self.proc.pid}) rc={rc}")
                print(f"   ⚠️  {self.name} exited (rc={rc}), zie logs/start_bot/ voor details")
                # Detect singleton guard message and disable auto_restart for monitor
                singleton_msgs = [
                    "monitor draait al", "Another instance holds the startup mutex", "monitor al actief"
                ]
                log_tail = ''
                if self.stderr_log_path.exists():
                    try:
                        with open(self.stderr_log_path, 'rb') as lf:
                            lf.seek(0, os.SEEK_END)
                            size = lf.tell()
                            lf.seek(max(0, size - 2048))
                            log_tail = lf.read().decode('utf-8', errors='ignore')
                    except Exception:
                        log_tail = ''
                if self.name == "monitor" and any(msg in log_tail for msg in singleton_msgs):
                    print(f"   ⚠️  monitor singleton gedetecteerd")
                    debug_log(f"ManagedProcess.start: monitor singleton detected, disabling auto_restart.")
                    self.auto_restart = False
                self.restart_attempts += 1
                self.proc = None
                self._close_log_handles()
                return
            # NOTE: Duplicate detection removed! Each script has its own Windows Mutex
            # in ensure_single_instance_or_exit() which prevents true duplicates.
            # Checking here causes false positives from intermediate Python spawn processes.
        except Exception:
            pass

    def stop(self) -> None:
        debug_log(f"ManagedProcess.stop: {self.name} - proc={self.proc}")
        if not self.proc or self.proc.poll() is not None:
            return
        debug_log(f"ManagedProcess.stop: {self.name} stoppen (pid={self.proc.pid})")
        try:
            if os.name == "nt":
                os.kill(self.proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                self.proc.terminate()
            self.proc.wait(timeout=10)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        finally:
            self._close_log_handles()

    def ensure(self) -> None:
        debug_log(f"ManagedProcess.ensure: {self.name} auto_restart={self.auto_restart} running={self.is_running()}")
        if not self.auto_restart:
            return
        if self.proc and self.proc.poll() is None:
            return
        # Process is not running anymore -> restart with simple backoff guard
        if self.proc and self.proc.poll() is not None:
            rc = self.proc.returncode
            debug_log(f"ManagedProcess.ensure: {self.name} detected exit rc={rc}, restarting")
            print(f"   ⚠️ {self.name} gestopt (rc={rc}), herstart...")
            self._close_log_handles()
            self.proc = None
            time.sleep(3)
        self.start()

    def is_running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None


def _script_command(script: str, *extra: str) -> list[str]:
    return [PYTHON, script, *extra]


def _start_daily_report_scheduler(check_interval_seconds: int = 60 * 60) -> None:
    """Start a background thread that runs `tools/daily_report.py` once per day.

    It uses a small marker file to record the last run timestamp so the job
    is idempotent across restarts. The scheduler is non-blocking and logs
    output to `logs/start_bot/daily_report.log`.
    """
    # Minimal safe scheduler: start a background thread that triggers the daily
    # report script at most once per 24h. The original implementation included
    # several nested try/except blocks and had indentation issues on some systems.
    try:
        import threading
        marker = BASE_DIR / 'data' / 'last_daily_report_ts'
        reports_log = START_BOT_LOG_DIR / 'daily_report.log'

        def _worker():
            # Lightweight loop: check marker and run report if needed.
            while True:
                try:
                    now = time.time()
                    last_ts = None
                    if marker.exists():
                        try:
                            last_ts = float(marker.read_text(encoding='utf-8').strip())
                        except Exception:
                            last_ts = None

                    if not last_ts or (now - float(last_ts)) >= 24 * 60 * 60:
                        cmd = _script_command(str(BASE_DIR / 'tools' / 'daily_report.py'))
                        try:
                            proc = subprocess.run(cmd, cwd=str(BASE_DIR), capture_output=True, text=True, timeout=60*10)
                            with open(reports_log, 'a', encoding='utf-8') as lf:
                                lf.write(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}Z] daily_report exit={proc.returncode}\n")
                            if proc.returncode == 0:
                                try:
                                    marker.parent.mkdir(parents=True, exist_ok=True)
                                    marker.write_text(str(time.time()), encoding='utf-8')
                                except Exception:
                                    pass
                        except Exception as e:
                            try:
                                with open(reports_log, 'a', encoding='utf-8') as lf:
                                    lf.write(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}Z] daily_report invocation failed: {e}\n")
                            except Exception:
                                pass

                except Exception:
                    # Keep the loop alive on unexpected errors
                    pass
                time.sleep(check_interval_seconds)

        t = threading.Thread(target=_worker, name='daily-report-scheduler', daemon=True)
        t.start()
    except Exception:
        # Fail silently - scheduler is optional
        return


_hodl_scheduler_thread: Optional[threading.Thread] = None


def _start_hodl_scheduler() -> None:
    """Launch the HODL/DCA scheduler loop if enabled in config."""
    global _hodl_scheduler_thread
    try:
        scheduler = HodlScheduler()
    except Exception as exc:
        debug_log(f"hodl_scheduler: init mislukt {exc}")
        return
    if not scheduler.enabled:
        debug_log("hodl_scheduler: niet geactiveerd in config")
        return
    interval = int(getattr(scheduler, "poll_interval", scheduler.settings.get("poll_interval_seconds", 300)) or 300)
    interval = max(60, interval)

    def _worker() -> None:
        debug_log(f"hodl_scheduler: thread gestart interval={interval}s, enabled={scheduler.enabled}, schedules={len(scheduler.schedules)}")
        while True:
            try:
                debug_log(f"hodl_scheduler: running cycle (enabled={scheduler.enabled}, schedules={len(scheduler.schedules)})")
                executed = scheduler.run_cycle()
                debug_log(f"hodl_scheduler: cycle done, executed={len(executed)} entries")
                if executed:
                    debug_log(f"hodl_scheduler: {len(executed)} entries uitgevoerd")
            except Exception as exc_inner:
                debug_log(f"hodl_scheduler: cycle fout {exc_inner}")
                import traceback
                debug_log(f"hodl_scheduler: traceback: {traceback.format_exc()}")
            time.sleep(interval)

    if _hodl_scheduler_thread and _hodl_scheduler_thread.is_alive():
        debug_log("hodl_scheduler: thread draait al")
        return
    _hodl_scheduler_thread = threading.Thread(target=_worker, name='hodl-dca-scheduler', daemon=True)
    _hodl_scheduler_thread.start()
    debug_log(f"hodl_scheduler: gestart (interval {interval}s)")


def _parent_running_start_bot() -> tuple[bool, Optional[tuple[int, str]]]:
    """Return (True, (ppid, cmdline)) when the parent process' commandline mentions start_bot.py.
    Uses psutil when available, otherwise WMIC on Windows as a best-effort fallback.
    """
    try:
        ppid = os.getppid()
        if not ppid or ppid <= 0:
            return (False, None)
        # Prefer psutil for reliable access
        if _psutil is not None:
            try:
                p = _psutil.Process(ppid)
                try:
                    cmd = ' '.join(p.cmdline() or [])
                except Exception:
                    cmd = ''
                if 'start_bot.py' in cmd:
                    return (True, (ppid, cmd))
                return (False, (ppid, cmd))
            except Exception:
                pass

        # WMIC fallback on Windows
        if os.name == 'nt':
            try:
                proc = subprocess.run([
                    'wmic', 'process', 'where', f'ProcessId={ppid}', 'get', 'CommandLine', '/format:csv'
                ], capture_output=True, text=True, timeout=5)
                if proc.returncode == 0 and proc.stdout:
                    lines = proc.stdout.splitlines()
                    for line in lines[1:]:
                        line = line.strip()
                        if not line:
                            continue
                        # CSV: Node,CommandLine
                        parts = line.split(',', 1)
                        if len(parts) == 2:
                            cmd = parts[1] or ''
                            if 'start_bot.py' in cmd:
                                return (True, (ppid, cmd))
                            return (False, (ppid, cmd))
            except Exception:
                pass
    except Exception:
        pass
    return (False, None)


def _is_script_running(script_name: str) -> bool:
    """Check of er al een python proces draait met `script_name` in de commandline.
    Gebruik psutil wanneer beschikbaar, anders WMIC fallback op Windows.
    """
    if not script_name:
        return False
    # Try psutil first
    if _psutil is not None:
        try:
            for proc in _psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmd = proc.info.get("cmdline") or []
                    if any(script_name in str(part) for part in cmd):
                        if _pid_alive(int(proc.info.get("pid") or 0)):
                            return True
                except (_psutil.NoSuchProcess, _psutil.AccessDenied, _psutil.ZombieProcess):
                    continue
                except Exception:
                    continue
        except Exception:
            pass

    # WMIC fallback for Windows
    if os.name == "nt":
        try:
            cmd = [
                "wmic",
                "process",
                "where",
                "name='python.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout:
                lines = proc.stdout.splitlines()
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parts = line.split(',', 2)
                        if len(parts) < 3:
                            continue
                        cmdline = parts[1] or ''
                        pid_str = parts[2]
                        if script_name in cmdline:
                            pid = int(pid_str)
                            if _pid_alive(pid):
                                return True
                    except Exception:
                        continue
        except Exception:
            pass
    return False


def _find_running_script_pids(script_name: str) -> list[int]:
    """Return list of PIDs for running processes that reference script_name and appear to belong to this repo.

    Uses psutil when available for reliable matching; otherwise returns empty list.
    """
    if not script_name:
        return []
    pids: list[int] = []
    repo_path = str(BASE_DIR)
    if _psutil is None:
        return pids
    try:
        for proc in _psutil.process_iter(["pid", "cmdline", "cwd", "exe"]):
            try:
                pid = int(proc.info.get('pid') or 0)
                if pid == os.getpid():
                    continue
                if not _pid_alive(pid):
                    continue
                cmd = proc.info.get('cmdline') or []
                cmdline = ' '.join(str(x) for x in cmd)
                cwd = proc.info.get('cwd') or ''
                exe = proc.info.get('exe') or ''
                # match when script_name appears anywhere in the commandline
                if script_name in cmdline or os.path.basename(script_name) in cmdline:
                    # verify repo membership where possible
                    if (cwd and cwd.startswith(repo_path)) or (repo_path in cmdline) or (exe and exe.startswith(repo_path)):
                        pids.append(pid)
            except Exception:
                continue
    except Exception:
        return []
    return pids


def prefetch_icons() -> None:
    """Prefetch coin icons for all whitelist markets (non-blocking background task)."""
    prefetch_script = BASE_DIR / "tools" / "prefetch_icons_cmc.py"
    if not prefetch_script.exists():
        return
    try:
        debug_log("prefetch_icons: gestart")
        subprocess.Popen(
            [PYTHON, str(prefetch_script)],
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        )
    except Exception as e:
        debug_log(f"prefetch_icons: fout {e}")


def build_processes(mode: str, include_dashboard: bool, include_pairs: bool) -> list[ManagedProcess]:
    processes: list[ManagedProcess] = []
    def _script_al_running(script_name: str) -> bool:
        """Return True when a process with script_name in its cmdline is running."""
        if _psutil is None:
            return False
        try:
            for proc in _psutil.process_iter(["pid", "cmdline"]):
                try:
                    cmd = proc.info.get("cmdline") or []
                    if any(script_name in str(x) for x in cmd):
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    # Always start monitor, ai_supervisor, auto_retrain, and auto_backup
    processes.append(
        ManagedProcess("monitor", _script_command(str(BASE_DIR / "scripts" / "helpers" / "monitor.py")), auto_restart=True)
    )
    # NOTE: trailing_bot is NOT started here — monitor.py is the sole manager
    # for trailing_bot restarts. Starting it from both places caused duplicate
    # instances due to race conditions.
    # Ensure the AI supervisor is kept running; restart if it exits quickly
    processes.append(
        ManagedProcess("ai_supervisor", _script_command(str(BASE_DIR / "ai" / "ai_supervisor.py")), auto_restart=False)
    )
    processes.append(
        ManagedProcess("auto_retrain", _script_command(str(BASE_DIR / "tools" / "auto_retrain.py"), "--loop"), auto_restart=False)
    )
    processes.append(
        ManagedProcess("auto_backup", _script_command(str(BASE_DIR / "scripts" / "helpers" / "auto_backup.py")), auto_restart=True)
    )
    
    # Flask Dashboard V1 removed 2026-04-29 — replaced entirely by Dashboard V2 (port 5002).

    # Dashboard V2 (FastAPI + PWA, port 5002 - new modern dashboard)
    dash_v2_path = BASE_DIR / "tools" / "dashboard_v2" / "backend" / "main.py"
    if dash_v2_path.exists():
        try:
            import importlib  # noqa: F401
            import fastapi  # noqa: F401
            v2_cmd = [
                PYTHON, "-m", "uvicorn",
                "tools.dashboard_v2.backend.main:app",
                "--host", "0.0.0.0",
                "--port", "5002",
            ]
            processes.append(
                ManagedProcess(
                    "dashboard_v2",
                    v2_cmd,
                    auto_restart=True,
                )
            )
        except Exception as e:
            debug_log(f"dashboard_v2: niet gestart (fastapi missing? {e})")
    else:
        debug_log("dashboard_v2: backend/main.py niet gevonden")

    # Dashboard V2 watchdog: auto-restarts the FastAPI uvicorn process if
    # /api/health reports stale data while heartbeat.json is fresh
    # (catches Windows file-handle freezes / OneDrive sync glitches).
    dash_v2_wd = BASE_DIR / "scripts" / "dashboard_v2_watchdog.py"
    if dash_v2_wd.exists():
        processes.append(
            ManagedProcess(
                "dashboard_v2_watchdog",
                [PYTHON, str(dash_v2_wd)],
                auto_restart=True,
            )
        )

    # Note: Dashboard watchdog removed - dashboards are self-managing
    
    if include_pairs:
        if not _script_al_running("start_pairs.py"):
            processes.append(
                ManagedProcess(
                    "pairs_runner",
                    _script_command(str(BASE_DIR / "scripts" / "startup" / "start_pairs.py")),
                    auto_restart=True,
                )
            )
        else:
            debug_log("pairs_runner draait al, overslaan")
    return processes
    # ...existing code...
    return processes


def _list_running_start_bot_pids() -> list[int]:
    """Zoek naar andere python-processen die start_bot.py draaien."""
    pids: list[int] = []
    current_pid = os.getpid()
    # Also skip parent PID — on Windows, VS Code terminals and wrapper scripts
    # can appear with the same commandline, and killing them kills our own tree.
    parent_pid = 0
    try:
        parent_pid = os.getppid()
    except Exception:
        parent_pid = 0
    skip_pids = {current_pid, parent_pid}
    if DEBUG_GUARD:
        print(f"[start_bot] guard current_pid={current_pid} parent_pid={parent_pid}")
    # Define repo path used by both detection branches
    repo_path = str(BASE_DIR)

    # Prefer psutil (more reliable and immediate) if available.
    if _psutil is not None:
        try:
            for proc in _psutil.process_iter(["pid", "cmdline"]):
                try:
                    # Get PID first and check if it's current process or parent
                    pid = int(proc.info["pid"])
                    if pid in skip_pids:
                        continue
                    
                    # Check process is still alive before accessing cmdline
                    # (some processes may have exited between iteration start and now)
                    if not _pid_alive(pid):
                        continue
                    
                    cmdline = proc.info.get("cmdline") or []
                    cmdline_str = ' '.join(cmdline)
                    # If cmdline is empty or too short, still check any part for start_bot.py
                    found = False
                    for part in cmdline:
                        try:
                            if os.path.basename(part) == 'start_bot.py' or 'start_bot.py' in part:
                                found = True
                                break
                        except Exception:
                            continue
                    if not found and 'start_bot.py' in cmdline_str:
                        found = True

                    if not found:
                        continue

                    # gather additional info for debugging and verify it's in this repo
                    exe = ''
                    cwd = ''
                    try:
                        exe = proc.exe() or ''
                    except Exception:
                        exe = ''
                    try:
                        cwd = proc.cwd() or ''
                    except Exception:
                        cwd = ''

                    # Only treat as a duplicate if the process is clearly running from this repo
                    repo_path = str(BASE_DIR)
                    is_repo_process = False
                    try:
                        if cwd and cwd.startswith(repo_path):
                            is_repo_process = True
                        elif repo_path in cmdline_str:
                            is_repo_process = True
                        elif exe and exe.startswith(repo_path):
                            is_repo_process = True
                    except Exception:
                        is_repo_process = False

                    if DEBUG_GUARD:
                        print(f"[start_bot] guard candidate pid={pid}, exe={exe}, cwd={cwd}, cmdline={cmdline}, repo_match={is_repo_process}")

                    if not is_repo_process:
                        # skip transient/unrelated python invocations
                        continue

                    # NOTE: VS Code bypass removed — it caused false negatives where
                    # legitimate duplicate instances launched from VS Code terminals
                    # were ignored, leading to all processes running 2x.

                    pids.append(pid)
                except (_psutil.NoSuchProcess, _psutil.AccessDenied, _psutil.ZombieProcess):
                    # Process disappeared or not accessible - skip it
                    continue
                except Exception:
                    continue
            if pids:
                return pids
        except Exception:
            pass

    # Fallback to WMIC on Windows if psutil not available or returned nothing
    if os.name == "nt":
        try:
            cmd = [
                "wmic",
                "process",
                "where",
                "name='python.exe'",
                "get",
                "ProcessId,CommandLine",
                "/format:csv",
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if proc.returncode == 0 and proc.stdout:
                if DEBUG_GUARD:
                    print(f"[start_bot] guard wmic raw stdout: {proc.stdout!r}")
                lines = proc.stdout.splitlines()
                for line in lines[1:]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parts = line.split(',', 2)
                        if len(parts) < 3:
                            continue
                        cmdline = parts[1] or ''
                        pid_str = parts[2]
                        if 'start_bot.py' not in cmdline:
                            continue
                        pid = int(pid_str)
                        if pid in skip_pids:
                            continue
                        # Quick liveness check
                        if not _pid_alive(pid):
                            continue

                        # If psutil is available, inspect the process for repo membership and VSCode ancestry
                        if _psutil is not None:
                            try:
                                p = _psutil.Process(pid)
                                try:
                                    exe = p.exe() or ''
                                except Exception:
                                    exe = ''
                                try:
                                    cwd = p.cwd() or ''
                                except Exception:
                                    cwd = ''
                                try:
                                    cmdline_full = ' '.join(p.cmdline() or []) or cmdline
                                except Exception:
                                    cmdline_full = cmdline

                                # Determine whether the process is clearly part of this repo
                                is_repo_process = False
                                try:
                                    if cwd and cwd.startswith(repo_path):
                                        is_repo_process = True
                                    elif repo_path in cmdline_full:
                                        is_repo_process = True
                                    elif exe and exe.startswith(repo_path):
                                        is_repo_process = True
                                except Exception:
                                    is_repo_process = False

                                if DEBUG_GUARD:
                                    print(f"[start_bot] guard wmic candidate pid={pid}, exe={exe}, cwd={cwd}, cmdline={cmdline_full}, repo_match={is_repo_process}")

                                if not is_repo_process:
                                    # skip unrelated python processes
                                    continue

                                pids.append(pid)
                            except Exception:
                                # If psutil inspection fails, fall back to naive cmdline repo check
                                if repo_path in cmdline:
                                    pids.append(pid)
                        else:
                            # No psutil: only accept WMIC candidates that contain the repo path in the commandline
                            if repo_path in cmdline:
                                pids.append(pid)
                    except Exception:
                        continue
        except Exception:
            pass
    return pids


def _terminate_start_bot_instances(pids: list[int], *, timeout: int = 10) -> None:
    """Stop other running start_bot.py instances so restart can proceed.
    
    Improved version with multiple termination strategies and forced cleanup.
    """
    if not pids:
        return

    def _kill_with_taskkill(pid: int, force_tree: bool = True) -> bool:
        """Kill process using Windows taskkill - most reliable on Windows."""
        if os.name != "nt":
            return False
        try:
            args = ["taskkill", "/PID", str(pid), "/F"]
            if force_tree:
                args.append("/T")  # Kill entire process tree
            result = subprocess.run(args, check=False, capture_output=True, timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    def _kill_with_psutil(pid: int) -> bool:
        """Kill process using psutil."""
        if _psutil is None:
            return False
        try:
            proc = _psutil.Process(pid)
            # First terminate all children
            for child in proc.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            # Then terminate parent
            proc.terminate()
            proc.wait(timeout=5)
            return not proc.is_running()
        except Exception:
            return False

    def _kill_with_os(pid: int) -> bool:
        """Kill process using os.kill."""
        try:
            if os.name == "nt":
                os.kill(pid, signal.CTRL_BREAK_EVENT)
            else:
                os.kill(pid, signal.SIGTERM)
            time.sleep(0.5)
            # Check if still alive
            try:
                os.kill(pid, 0)
                # Still alive, force kill
                if os.name == "nt":
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGKILL)
                return True
            except OSError:
                return True  # Already dead
        except Exception:
            return False

    for pid in pids:
        print(f"[start_bot] Bestaand start_bot proces gevonden (pid={pid}), probeer te stoppen...")
        
        # Strategy 1: Try taskkill first (most reliable on Windows)
        if _kill_with_taskkill(pid):
            print(f"[start_bot] Proces {pid} gestopt via taskkill")
            continue
        
        # Strategy 2: Try psutil
        if _kill_with_psutil(pid):
            print(f"[start_bot] Proces {pid} gestopt via psutil")
            continue
        
        # Strategy 3: Try os.kill
        if _kill_with_os(pid):
            print(f"[start_bot] Proces {pid} gestopt via os.kill")
            continue
        
        # Strategy 4: Force kill with taskkill (no /T, just the pid)
        if _kill_with_taskkill(pid, force_tree=False):
            print(f"[start_bot] Proces {pid} gestopt via taskkill (force)")
            continue
        
        print(f"[start_bot] WAARSCHUWING: Kon proces {pid} niet stoppen")
    
    # Wait a bit for processes to fully terminate
    time.sleep(2)
    
    # Final verification and force cleanup of any remaining
    for pid in pids:
        try:
            if _psutil and _psutil.pid_exists(pid):
                print(f"[start_bot] Proces {pid} nog actief, forceer kill...")
                _kill_with_taskkill(pid)
        except Exception:
            pass


def run_housekeeping(now: float, last_run: Optional[float]) -> float:
    if last_run is not None and now - last_run < HOUSEKEEPING_INTERVAL:
        return last_run
    if not HOUSEKEEPING_SCRIPT.exists():
        return now
    debug_log("housekeeping: starten")
    tasks: list[tuple[list[str], str]] = [
        ([PYTHON, str(HOUSEKEEPING_SCRIPT), "--compress"], "trade backups"),
        (
            [
                PYTHON,
                str(HOUSEKEEPING_SCRIPT),
                "--pattern",
                BOT_LOG_PATTERN,
                "--keep",
                "0",
                "--archive-dir",
                BOT_LOG_ARCHIVE,
                "--compress",
            ],
            "bot logs",
        ),
    ]
    for command, label in tasks:
        try:
            subprocess.run(command, cwd=str(BASE_DIR), check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as exc:
            debug_log(f"housekeeping: mislukt ({label}), rc={exc.returncode}")
        except Exception as exc:  # noqa: BLE001 - best effort cleanup
            debug_log(f"housekeeping: fout ({label}): {exc}")
    return now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start bot + helpers met een command")
    parser.add_argument(
        "--mode",
        choices=["monitor", "direct"],
        default="monitor",
        help="monitor: monitor.py start de bot; direct: start trailing_bot zelf",
    )
    parser.add_argument(
        "--no-dashboard",
        dest="with_dashboard",
        action="store_false",
        help="Sla dashboard_watchdog over",
    )
    parser.add_argument(
        "--no-pairs",
        dest="with_pairs",
        action="store_false",
        help="Sla de Golf 3 pairs-arbitrage runner over (ook als config deze inschakelt)",
    )
    parser.set_defaults(with_dashboard=True, with_pairs=True)
    parser.add_argument(
        "--no-autorestart",
        action="store_true",
        help="Schakel automatische herstart van helpers uit",
    )
    parser.add_argument(
        "--allow-no-operator",
        action="store_true",
        help="Allow starting the bot even when BITVAVO_OPERATOR_ID is not configured (not recommended).",
    )
    return parser.parse_args()


def main() -> None:
    # Clean up ALL stale PID and lock files before starting
    # This prevents old PID files from blocking new starts
    try:
        import glob
        import psutil as ps  # Import here to avoid scope issues
        logs_dir = BASE_DIR / "logs"
        if logs_dir.exists():
            removed_count = 0
            for pidfile in glob.glob(str(logs_dir / "*.pid*")):
                try:
                    # Remove ALL lock files (they should never persist)
                    if pidfile.endswith('.lock'):
                        os.remove(pidfile)
                        removed_count += 1
                        continue
                    
                    # For PID files, check if process exists
                    if pidfile.endswith('.pid'):
                        should_remove = False
                        try:
                            with open(pidfile, 'r') as f:
                                old_pid = int(f.read().strip())
                            # Check if process exists
                            try:
                                proc = ps.Process(old_pid)
                                # If it's not a Python process, it's stale
                                if 'python' not in proc.name().lower():
                                    should_remove = True
                            except (ps.NoSuchProcess, ps.AccessDenied):
                                # Process doesn't exist
                                should_remove = True
                        except (ValueError, IOError):
                            # Can't read PID - remove it
                            should_remove = True
                        
                        if should_remove:
                            os.remove(pidfile)
                            removed_count += 1
                except Exception as e:
                    print(f"[start_bot] Warning: kon PID file {pidfile} niet verwijderen: {e}")
            
            if removed_count > 0:
                print(f"   🧹 {removed_count} oude PID/lock files opgeruimd")
    except ImportError:
        # psutil not available - skip cleanup
        pass
    except Exception as e:
        print(f"[start_bot] Warning: PID cleanup gefaald: {e}")
    
    # Abort early if another start_bot instance is already running.
    # CRITICAL FIX: Skip this check when launched by start_automated.bat/ps1
    # because the wrapper script is still running and gets detected as "duplicate"
    parent_is_launcher = False
    try:
        if _psutil is not None:
            parent = _psutil.Process(os.getppid())
            parent_cmdline = ' '.join(parent.cmdline() or []).lower()
            # Only skip duplicate check when launched by start_automated.ps1/bat wrapper
            # IMPORTANT: Do NOT match 'start_bot' here — that would skip the check
            # when start_bot.py is its own parent (e.g. due to Windows process inheritance)
            if 'start_automated' in parent_cmdline:
                parent_is_launcher = True
                debug_log(f"main: Skipping duplicate check - launched by wrapper: {parent_cmdline[:100]}")
    except Exception as e:
        debug_log(f"main: Could not check parent process: {e}")
    
    if not parent_is_launcher:
        existing_instances = _list_running_start_bot_pids()
        if existing_instances:
            print(f"   \u26a0\ufe0f  Bestaande bot gevonden (pid: {existing_instances}), stoppen...")
            debug_log(f"main: andere start_bot actief {existing_instances}")
            _terminate_start_bot_instances(existing_instances)
            time.sleep(3)
            remaining = _list_running_start_bot_pids()
            if remaining:
                debug_log(f"main: kon processen niet stoppen: {remaining}")
            else:
                debug_log("main: oude processen gestopt")
    else:
        debug_log("main: launched by wrapper, skip duplicate check")

    # Single-instance check: prevent duplicate start_bot processes using mutex+PID guard
    # RE-ENABLED: Use allow_claim=False so a second launch exits cleanly
    # instead of killing the first (which would orphan child processes).
    ensure_single_instance_or_exit('start_bot.py', allow_claim=False)
    
    debug_log(f"main: START pid={os.getpid()}")
    try:
        parent_info = None
        parent_pid = None
        try:
            parent_pid = os.getppid()
        except Exception:
            parent_pid = None
        if parent_pid:
            try:
                if _psutil is not None:
                    p = _psutil.Process(parent_pid)
                    try:
                        parent_cmd = ' '.join(p.cmdline() or [])
                    except Exception:
                        parent_cmd = ''
                    try:
                        parent_exe = p.exe() or ''
                    except Exception:
                        parent_exe = ''
                    parent_info = (parent_pid, parent_exe, parent_cmd)
                else:
                    parent_info = (parent_pid, None, None)
            except Exception:
                parent_info = (parent_pid, None, None)
        log_line = f"[start_bot] started pid={os.getpid()} parent={parent_info}\n"
        debug_log(f"main: {log_line.strip()}")
        try:
            with open(BASE_DIR / 'start_bot.log', 'a', encoding='utf-8') as lf:
                lf.write(log_line)
        except Exception:
            pass
    except Exception as e:
        debug_log(f"main: exception bij startup diagnostics {e}")
    try:
        load_dotenv()
        debug_log("main: .env geladen")
    except Exception as e:
        debug_log(f"main: exception bij load_dotenv {e}")
    args = parse_args()
    debug_log(f"main: parse_args {args}")
    allow_no_operator = args.allow_no_operator
    operator_id_env = os.getenv('BITVAVO_OPERATOR_ID')
    operator_id_cfg = None
    config_doc: dict = {}
    try:
        cfg_path = BASE_DIR / 'config' / 'bot_config.json'
        if cfg_path.exists():
            with cfg_path.open('r', encoding='utf-8') as fh:
                config_doc = json.load(fh)
                operator_id_cfg = config_doc.get('BITVAVO_OPERATOR_ID')
    except Exception:
        operator_id_cfg = None
    debug_log(f"main: operator_id_env={operator_id_env} operator_id_cfg={operator_id_cfg}")
    if not allow_no_operator and not (operator_id_env or operator_id_cfg):
        print('[start_bot] ERROR: BITVAVO_OPERATOR_ID is not set in environment or bot_config.json.')
        debug_log('main: exit vanwege ontbrekende BITVAVO_OPERATOR_ID')
        print('[start_bot] If you understand the risk, re-run with --allow-no-operator to proceed.')
        return
    pairs_cfg = config_doc.get('PAIRS_ARBITRAGE') if isinstance(config_doc, dict) else None
    pairs_enabled_cfg = bool((pairs_cfg or {}).get('enabled'))
    include_pairs = args.with_pairs and pairs_enabled_cfg

    # Prefetch coin icons for dashboard (runs quickly, skips cached)
    prefetch_icons()

    # Note: invested_eur sync happens inside trailing_bot.py on startup
    # via modules.invested_sync — no need to run it here.

    processes = build_processes(args.mode, args.with_dashboard, include_pairs)
    debug_log(f"main: build_processes {[(p.name, p.command) for p in processes]}")
    # Extra guard: als er al een monitor actief is, niet opnieuw proberen
    if any(p.name == "monitor" for p in processes):
        # Check of er al een monitor draait
        monitor_pids = _find_running_script_pids('monitor.py')
        if monitor_pids:
            debug_log(f"main: monitor(s) actief, geen nieuwe starten: {monitor_pids}")
            processes = [p for p in processes if p.name != "monitor"]
    if args.no_autorestart:
        for proc in processes:
            proc.auto_restart = False
            debug_log(f"main: auto_restart uitgeschakeld voor {proc.name}")
    
    # Disable auto-restart during initial startup to prevent duplicates
    # (will be enabled after all processes have started successfully)
    for proc in processes:
        proc.auto_restart = False
    
    print("")
    print("   Starting services...")
    print("")
    for proc in processes:
        debug_log(f"main: start process {proc.name}")
        proc.start()
        # Longer delay to ensure PID file is fully written and locked
        # before next process starts. This prevents race conditions.
        time.sleep(1.0)

    # Re-enable auto-restart for critical processes after initial startup.
    # During the initial startup we disable auto-restart to avoid accidental
    # duplicate spawns; once processes have started we want the supervisor
    # loop to be able to restart helpers.
    # NOTE: trailing_bot is deliberately excluded — monitor.py is the sole
    # restart manager for the trading bot.  Having *both* start_bot and
    # monitor restart trailing_bot causes a dual-manager race condition
    # where two instances fight over the singleton lock, force-killing each
    # other in an infinite loop (exit rc=1, no traceback).
    try:
        for proc in processes:
            if proc.name in ("monitor", "auto_backup", "ai_supervisor", "pairs_runner"):
                proc.auto_restart = True
                debug_log(f"main: auto_restart enabled for {proc.name}")
    except Exception:
        # Non-critical: if enabling fails, continue running with existing settings
        pass
    
    print("")
    print("   " + "─" * 50)
    print(f"   ✅ Alle {len(processes)} services gestart")
    print("   " + "─" * 50)
    print("")
    debug_log("main: alle processen gestart")
    try:
        _start_daily_report_scheduler()
        debug_log('main: daily_report scheduler gestart')
    except Exception:
        debug_log('main: kon daily_report scheduler niet starten')
    try:
        _start_hodl_scheduler()
        debug_log('main: hodl_scheduler gestart')
    except Exception:
        debug_log('main: kon hodl_scheduler niet starten')
    last_housekeeping: Optional[float] = None
    try:
        while True:
            time.sleep(5)
            now = time.time()
            last_housekeeping = run_housekeeping(now, last_housekeeping)
            for proc in processes:
                proc.ensure()
                debug_log(f"main: ensure process {proc.name}")
    except KeyboardInterrupt:
        print("")
        print("   🛑 Stop-signaal ontvangen, services afsluiten...")
        debug_log("main: KeyboardInterrupt ontvangen, processen afsluiten")
        for proc in processes:
            proc.stop()
            debug_log(f"main: gestopt process {proc.name}")


if __name__ == "__main__":
    main()


