from __future__ import annotations

import os
import json
import time
from datetime import datetime, timezone
from pathlib import Path

# Debug logging
def debug_log(msg: str):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S.%f')
    try:
        with open(DEBUG_LOG, 'a', encoding='utf-8') as f:
            f.write(f'[{ts}] {msg}\n')
    except Exception:
        pass

# Alert sending
def send_alert(msg, cfg):
    try:
        import requests
    except Exception:
        try:
            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - alerts disabled (requests not available): {msg}\n")
        except Exception:
            pass
        return
    tg = cfg.get('TELEGRAM_WEBHOOK')
    wh = cfg.get('ALERT_WEBHOOK')
    dedupe_sec = cfg.get('ALERT_DEDUPE_SECONDS', 600)
    state_file = os.path.join(LOG_DIR, 'last_alert.json')
    last = {}
    if os.path.exists(state_file):
        with open(state_file, 'r', encoding='utf-8') as fh:
            last = json.load(fh)
    if last.get('msg') == msg and time.time() - last.get('ts', 0) < dedupe_sec:
        return
    for dest in (tg, wh):
        if not dest:
            continue
        try:
            if dest == tg:
                requests.post(dest, json={'text': msg}, timeout=5)
            else:
                requests.post(dest, json={'message': msg}, timeout=5)
        except Exception:
            pass
    with open(state_file, 'w', encoding='utf-8') as fh:
        json.dump({'msg': msg, 'ts': int(time.time())}, fh)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'bot_config.json')
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)
MONITOR_LOG = os.path.join(LOG_DIR, 'monitor.log')
PID_FILE = os.path.join(LOG_DIR, 'monitor.pid')
DEBUG_LOG = Path(LOG_DIR) / 'monitor_debug.log'
PAUSE_FILE = Path(LOG_DIR) / 'trading_pause.json'
TRADE_LOG_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'trade_log.json'

# Singleton enforcement
try:
    from single_instance import ensure_single_instance_or_exit
except ImportError:
    def ensure_single_instance_or_exit(*args, **kwargs):
        pass

def load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}
import subprocess
import sys
import time
import os
import json
import threading
import shutil
from datetime import datetime, timezone
import atexit
import hashlib
from pathlib import Path

# Add project root to Python path for module imports
import sys
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.json_compat import write_json_compat

# Ensure we use the same Python interpreter as the parent process (venv if present)
BASE_DIR = project_root
VENV_PYTHON = BASE_DIR / ".venv" / "Scripts" / "python.exe"
# Prefer environment variable set by parent, fallback to venv detection
PYTHON = os.environ.get("BITVAVO_PYTHON_PATH") or (str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable)


def tail_file(path, n=200):
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 1024
            data = b''
            while size > 0 and n > 0:
                if size - block > 0:
                    f.seek(size - block)
                else:
                    f.seek(0)
                chunk = f.read(min(block, size))
                data = chunk + data
                size -= block
                n -= 1
            return data.decode('utf-8', errors='replace')
    except Exception:
        return ''


def run_diagnostics(cfg):
    out = {}
    try:
        tb_path = os.path.join(os.path.dirname(__file__), '..', '..', 'trailing_bot.py')
        p = subprocess.run([sys.executable, '-m', 'py_compile', tb_path], capture_output=True, text=True, timeout=20)
        out['py_compile_returncode'] = p.returncode
        out['py_compile_stdout'] = p.stdout
        out['py_compile_stderr'] = p.stderr
    except Exception as e:
        out['py_compile_error'] = str(e)
    try:
        if os.path.exists('diagnose_balance.py'):
            p = subprocess.run([sys.executable, 'diagnose_balance.py'], capture_output=True, text=True, timeout=30)
            out['diagnose_stdout'] = p.stdout
            out['diagnose_stderr'] = p.stderr
    except Exception as e:
        out['diagnose_error'] = str(e)
    return out


def file_checksum(path):
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as fh:
            while True:
                b = fh.read(8192)
                if not b:
                    break
                h.update(b)
        return h.hexdigest()
    except Exception:
        return None


def _get_windows_pids_by_cmd_match(pattern):
    pids = []
    if os.name != 'nt':
        return pids
    try:
        cmd = [
            'powershell', '-NoProfile', '-Command',
            f"Get-CimInstance Win32_Process | Where-Object {{ $_.Name -eq 'python.exe' -and $_.CommandLine -match '{pattern}' }} | Select-Object -ExpandProperty ProcessId"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if p.returncode == 0 and p.stdout:
            for line in p.stdout.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    pid = int(line)
                    pids.append(pid)
                except Exception:
                    continue
    except Exception:
        pass
    return pids


def _kill_pids(pids):
    if not pids:
        return
    grace_seconds = 5
    try:
        cfg = load_config()
        grace_seconds = int(cfg.get('GRACEFUL_KILL_SECONDS', grace_seconds))
    except Exception:
        pass
    for pid in pids:
        try:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(pid)], capture_output=True)
                t0 = time.time()
                while time.time() - t0 < grace_seconds:
                    try:
                        p = subprocess.run(['powershell', '-NoProfile', '-Command', f"Get-CimInstance Win32_Process -Filter \"ProcessId={pid}\" | Select-Object -ExpandProperty ProcessId"], capture_output=True, text=True)
                        if not p.stdout.strip():
                            break
                    except Exception:
                        break
                    time.sleep(0.5)
                subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True)
            else:
                import signal
                try:
                    os.kill(pid, signal.SIGTERM)
                except Exception:
                    pass
                t0 = time.time()
                while time.time() - t0 < grace_seconds:
                    try:
                        os.kill(pid, 0)
                        time.sleep(0.5)
                    except OSError:
                        break
                try:
                    os.kill(pid, signal.SIGKILL)
                except Exception:
                    pass
        except Exception:
            pass


def _load_pause_state() -> dict:
    if not PAUSE_FILE.exists():
        return {}
    try:
        with PAUSE_FILE.open('r', encoding='utf-8') as fh:
            data = json.load(fh) or {}
        resume_ts = float(data.get('resume_ts') or 0)
        if resume_ts and time.time() < resume_ts:
            return data
    except Exception:
        pass
    try:
        PAUSE_FILE.unlink(missing_ok=True)
    except Exception:
        pass
    return {}


def _activate_pause(reason: str, minutes: int) -> dict:
    payload = {
        'reason': reason,
        'activated_ts': int(time.time()),
        'resume_ts': int(time.time() + max(1, minutes) * 60),
    }
    try:
        with PAUSE_FILE.open('w', encoding='utf-8') as fh:
            json.dump(payload, fh, indent=2)
    except Exception:
        pass
    return payload


def _evaluate_loss_guard(cfg) -> tuple[bool, str, int]:
    max_loss = float(cfg.get('WATCHDOG_MAX_DAILY_LOSS_EUR', 0) or 0)
    lookback_hours = float(cfg.get('WATCHDOG_LOSS_LOOKBACK_HOURS', 24) or 24)
    pause_minutes = int(cfg.get('WATCHDOG_PAUSE_MINUTES', 60) or 60)
    max_consec = int(cfg.get('WATCHDOG_MAX_CONSECUTIVE_LOSSES', 0) or 0)
    if max_loss <= 0 and max_consec <= 0:
        return False, '', 0
    trades = []
    try:
        with TRADE_LOG_PATH.open('r', encoding='utf-8') as fh:
            doc = json.load(fh)
        if isinstance(doc, dict):
            trades = doc.get('closed', []) or []
        elif isinstance(doc, list):
            trades = doc
    except Exception:
        return False, '', 0
    cutoff = time.time() - lookback_hours * 3600
    recent = [t for t in trades if float(t.get('timestamp', 0) or 0) >= cutoff]
    if max_loss > 0:
        pnl = sum(float(t.get('profit', 0) or 0) for t in recent)
        if pnl <= -max_loss:
            reason = f"Loss guard: €{pnl:.2f} over laatste {lookback_hours:.0f}h (limiet €{max_loss:.2f})"
            return True, reason, pause_minutes
    if max_consec > 0:
        consec = 0
        for trade in reversed(recent):
            profit = float(trade.get('profit', 0) or 0)
            if profit < 0:
                consec += 1
                if consec >= max_consec:
                    reason = f"Loss guard: {consec} verliestrades op rij"
                    return True, reason, pause_minutes
            else:
                break
    return False, '', 0


def monitor_loop():
    def _is_running(pid: int) -> bool:
        try:
            # On POSIX this will raise OSError if the pid doesn't exist. On Windows, os.kill with 0 is not reliable
            os.kill(pid, 0)
        except OSError:
            return False
        except Exception:
            return True
        return True

    ensure_single_instance_or_exit('monitor')

    # PID-file handling
    try:
        stale_pid = None
        if os.path.exists(PID_FILE):
            try:
                with open(PID_FILE, 'r', encoding='utf-8') as ph:
                    stale_pid = int(ph.read().strip() or 0)
            except Exception:
                stale_pid = None
            if stale_pid and stale_pid != os.getpid():
                if _is_running(stale_pid):
                    print(f"Monitor already running with PID {stale_pid}, exiting")
                    return
                else:
                    try:
                        os.remove(PID_FILE)
                    except Exception:
                        pass
        try:
            with open(PID_FILE, 'w', encoding='utf-8') as ph:
                ph.write(str(os.getpid()))
        except Exception:
            pass
    except Exception:
        pass

    def _cleanup_pid():
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE, 'r', encoding='utf-8') as ph:
                    p = ph.read().strip()
                if not p or int(p) == os.getpid():
                    os.remove(PID_FILE)
        except Exception:
            pass

    atexit.register(_cleanup_pid)

    # watcher thread: detect files in auto_updates and request restart
    restart_requested = threading.Event()

    def _watcher_thread():
        last_seen = set()
        while True:
            try:
                cfg_w = load_config()
                if not cfg_w.get('AUTO_APPROVE_UPDATES'):
                    last_seen = set()

                pause_state = _load_pause_state()
                if pause_state:
                    resume_dt = datetime.fromtimestamp(pause_state['resume_ts'], timezone.utc)
                    msg = f"Monitor: trading pause actief tot {resume_dt.isoformat()} ({pause_state.get('reason')})"
                    print(msg)
                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - {msg}\n")
                    time.sleep(min(backoff_base * 2, 60))
                    continue

                guard_hit, guard_reason, guard_pause = _evaluate_loss_guard(cfg)
                if guard_hit:
                    state = _activate_pause(guard_reason, guard_pause)
                    alert_msg = f"Monitor pauzeert trades: {guard_reason}. Hervat om {datetime.fromtimestamp(state['resume_ts'], timezone.utc).isoformat()}Z"
                    print(alert_msg)
                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - {alert_msg}\n")
                    try:
                        send_alert(alert_msg, cfg)
                    except Exception:
                        pass
                    time.sleep(min(guard_pause * 60, 300))
                    continue
                else:
                    updates_dir = os.path.join(os.path.dirname(__file__), 'auto_updates')
                    if os.path.exists(updates_dir):
                        curr = set(f for f in os.listdir(updates_dir) if not os.path.isdir(os.path.join(updates_dir, f)) and f not in ('applied', 'failed'))
                        curr = set(f for f in curr if not f.startswith('.') and '..' not in f)
                        new = curr - last_seen
                        if new:
                            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Watcher detected updates: {new}\n")
                            restart_requested.set()
                        last_seen = curr
            except Exception:
                pass
            time.sleep(3)

    watcher = threading.Thread(target=_watcher_thread, daemon=True)
    watcher.start()

    # heartbeat thread
    bot_running_event = threading.Event()

    def _monitor_heartbeat():
        cfg_local = load_config()
        interval = int(cfg_local.get('HEARTBEAT_UPDATE_SECONDS', 30))
        hb_path = os.path.join(os.path.dirname(__file__), 'heartbeat.json')
        while True:
            try:
                bots = _get_windows_pids_by_cmd_match('trailing_bot.py')
                if bot_running_event.is_set() or bots:
                    ot = 0
                    try:
                        if os.path.exists('trade_log.json'):
                            with open('trade_log.json', 'r', encoding='utf-8') as fh:
                                tj = json.load(fh)
                                ot = len(tj.get('open', {})) if isinstance(tj.get('open', {}), dict) else 0
                    except Exception:
                        ot = 0
                    hb = {}
                    try:
                        if os.path.exists(hb_path):
                            with open(hb_path, 'r', encoding='utf-8') as fh:
                                current = json.load(fh)
                            if isinstance(current, dict):
                                hb.update(current)
                    except Exception:
                        hb = {}
                    hb.update({'ts': int(time.time()), 'open_trades': ot})
                    try:
                        ai_path = os.path.join(os.path.dirname(__file__), 'ai_heartbeat.json')
                        ai_payload = {"online": False, "last_seen": None}
                        stale = int(cfg_local.get('AI_HEARTBEAT_STALE_SECONDS', 900)) if isinstance(cfg_local.get('AI_HEARTBEAT_STALE_SECONDS', None), (int, float)) else 900
                        if ai_path and os.path.exists(ai_path):
                            with open(ai_path, 'r', encoding='utf-8') as af:
                                ai_doc = json.load(af) or {}
                            ts_val = ai_doc.get('ts')
                            status_text = ai_doc.get('status')
                            last_seen = float(ts_val) if isinstance(ts_val, (int, float)) else None
                            if last_seen is not None:
                                ai_payload['last_seen'] = last_seen
                                ai_payload['online'] = (time.time() - last_seen) <= max(60, stale)
                            if status_text:
                                ai_payload['status'] = str(status_text)
                        hb['ai_status'] = ai_payload
                    except Exception:
                        pass
                    try:
                        write_json_compat(hb_path, hb)
                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Monitor wrote heartbeat (bots={bots})\n")
                    except Exception:
                        pass
                time.sleep(interval)
                cfg_local = load_config()
                interval = int(cfg_local.get('HEARTBEAT_UPDATE_SECONDS', interval))
            except Exception:
                time.sleep(5)

    hb_thread = threading.Thread(target=_monitor_heartbeat, daemon=True)
    hb_thread.start()

    # main loop: launch trailing_bot.py and manage restarts
    restart_count = 0
    last_start_time = 0
    try:
        while True:
            cfg = load_config()
            max_restarts = cfg.get('WATCHDOG_MAX_RESTARTS', 0)
            backoff_base = cfg.get('WATCHDOG_BACKOFF_SECONDS', 5)

            # Auto-apply updates when requested
            try:
                if restart_requested.is_set() or cfg.get('AUTO_APPROVE_UPDATES'):
                    restart_requested.clear()
                    updates_dir = os.path.join(os.path.dirname(__file__), 'auto_updates')
                    applied_dir = os.path.join(updates_dir, 'applied')
                    failed_dir = os.path.join(updates_dir, 'failed')
                    os.makedirs(applied_dir, exist_ok=True)
                    os.makedirs(failed_dir, exist_ok=True)
                    if os.path.exists(updates_dir):
                        for fname in os.listdir(updates_dir):
                            fpath = os.path.join(updates_dir, fname)
                            if os.path.isdir(fpath) or fname in ('applied', 'failed'):
                                continue
                            if fname.startswith('.') or '..' in fname:
                                continue
                            dest = os.path.join(os.path.dirname(__file__), fname)
                            try:
                                apply_compile = bool(cfg.get('APPLY_PY_COMPILE', True)) and fname.lower().endswith('.py')
                                if apply_compile:
                                    p = subprocess.run([sys.executable, '-m', 'py_compile', fpath], capture_output=True, text=True, timeout=20)
                                    if p.returncode != 0:
                                        dst_fail = os.path.join(failed_dir, fname)
                                        shutil.move(fpath, dst_fail)
                                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                            mh.write(f"{datetime.utcnow(timezone.utc).isoformat()}Z - Compile failed for {fname}; moved to failed: {p.stderr}\n")
                                        try:
                                            send_alert(f"Auto-apply compile failed for {fname}: {p.stderr}", cfg)
                                        except Exception:
                                            pass
                                        continue
                                if cfg.get('RUN_TESTS_BEFORE_APPLY') and fname.lower().endswith('.py'):
                                    try:
                                        t = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-v'], cwd=os.path.dirname(__file__), capture_output=True, text=True, timeout=60)
                                        if t.returncode != 0:
                                            dst_fail = os.path.join(failed_dir, fname)
                                            shutil.move(fpath, dst_fail)
                                            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Tests failed for {fname}; moved to failed: {t.stdout}\n{t.stderr}\n")
                                            try:
                                                send_alert(f"Auto-apply tests failed for {fname}: see monitor log", cfg)
                                            except Exception:
                                                pass
                                            continue
                                    except Exception as e:
                                        try:
                                            dst_fail = os.path.join(failed_dir, fname)
                                            if os.path.exists(fpath):
                                                shutil.move(fpath, dst_fail)
                                        except Exception:
                                            pass
                                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Test-run error for {fname}: {e}\n")
                                        continue
                                if os.path.exists(dest):
                                    bak = dest + '.autobak'
                                    shutil.copy2(dest, bak)
                                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Autobackup {dest} -> {bak}\n")
                                shutil.copy2(fpath, dest)
                                bak_path = dest + '.autobak'

                                smoke_cmd = cfg.get('AUTO_UPDATE_SMOKE_TEST')
                                smoke_timeout = int(cfg.get('AUTO_UPDATE_SMOKE_TIMEOUT', 90) or 90)
                                if smoke_cmd:
                                    try:
                                        formatted = smoke_cmd.format(file=fname, path=dest)
                                        smoke_proc = subprocess.run(formatted, shell=True, capture_output=True, text=True, timeout=smoke_timeout, cwd=BASE_DIR)
                                    except Exception as smoke_exc:
                                        smoke_proc = None
                                        smoke_error = str(smoke_exc)
                                    else:
                                        smoke_error = smoke_proc.stderr if smoke_proc and smoke_proc.returncode != 0 else ''
                                    if not smoke_proc or smoke_proc.returncode != 0:
                                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Smoke-test failed for {fname}: {smoke_error or smoke_proc.stdout}\n")
                                        try:
                                            if os.path.exists(bak_path):
                                                shutil.copy2(bak_path, dest)
                                            dst_fail = os.path.join(failed_dir, fname)
                                            if os.path.exists(fpath):
                                                shutil.move(fpath, dst_fail)
                                        except Exception:
                                            pass
                                        try:
                                            send_alert(f"Auto-update smoke test failed for {fname}; rollback applied", cfg)
                                        except Exception:
                                            pass
                                        continue
                                with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                    mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Applied update {fname} -> {dest}\n")
                                shutil.move(fpath, os.path.join(applied_dir, fname))
                                if cfg.get('AUTO_RESTART_AFTER_UPDATE'):
                                    try:
                                        bots = _get_windows_pids_by_cmd_match('trailing_bot.py')
                                        bots = [p for p in bots if p != os.getpid()]
                                        if bots:
                                            _kill_pids(bots)
                                            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Restarted bot PIDs {bots} after applying updates\n")
                                    except Exception as e:
                                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Failed to restart bot after update: {e}\n")
                            except Exception as e:
                                try:
                                    dst_fail = os.path.join(failed_dir, fname)
                                    if os.path.exists(fpath):
                                        shutil.move(fpath, dst_fail)
                                except Exception:
                                    pass
                                with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                                    mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Failed to apply update {fname}: {e}\n")
            except Exception:
                pass

            # maintenance mode
            if os.path.exists('MAINTENANCE'):
                print(f"{datetime.now(timezone.utc).isoformat()}Z - MAINTENANCE file present, sleeping 30s")
                time.sleep(30)
                continue

            stdout_path = os.path.join(LOG_DIR, 'trailing_stdout.log')
            stderr_path = os.path.join(LOG_DIR, 'trailing_stderr.log')

            try:
                existing_bots = _get_windows_pids_by_cmd_match('trailing_bot.py')
                if existing_bots:
                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - trailing_bot.py already running (PIDs: {existing_bots}), not starting another instance.\n")
                    print(f"Monitor: trailing_bot.py already running (PIDs: {existing_bots}), not starting another instance.")
                    time.sleep(backoff_base)
                    rc = 0
                else:
                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Starting trailing_bot.py\n")
                    with open(stdout_path, 'ab') as out_f, open(stderr_path, 'ab') as err_f:
                        tb_path = os.path.join(os.path.dirname(__file__), '..', '..', 'trailing_bot.py')
                        checksum = file_checksum(tb_path)
                        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - launching trailing_bot.py (checksum={checksum})\n")
                        # Pass environment to ensure venv Python is used
                        env = os.environ.copy()
                        proc = subprocess.Popen([PYTHON, tb_path], stdout=out_f, stderr=err_f, env=env)
                        try:
                            bot_running_event.set()
                        except Exception:
                            pass
                        last_start_time = time.time()
                        proc.wait()
                        rc = proc.returncode
                        try:
                            bot_running_event.clear()
                        except Exception:
                            pass
            except KeyboardInterrupt:
                with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                    mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Monitor received KeyboardInterrupt, exiting\n")
                break
            except Exception as e:
                with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                    mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Failed to start trailing_bot.py: {e}\n")
                rc = -999

            # process exited: collect logs and diagnostics
            msg = f"{datetime.now(timezone.utc).isoformat()}Z - trailing_bot.py exited with returncode={rc}"
            print(msg)
            tail_out = tail_file(stdout_path, 40)
            tail_err = tail_file(stderr_path, 200)
            diag = run_diagnostics(cfg)
            report_path = os.path.join(LOG_DIR, f'failure_{int(time.time())}.json')
            report = {'ts': int(time.time()), 'returncode': rc, 'stdout_tail': tail_out, 'stderr_tail': tail_err, 'diagnostics': diag}
            try:
                with open(report_path, 'w', encoding='utf-8') as fh:
                    json.dump(report, fh, indent=2)
            except Exception:
                pass
            try:
                send_alert(f"Bot exited (rc={rc}). See {report_path}", cfg)
            except Exception:
                try:
                    with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                        mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - send_alert failed for rc={rc}\n")
                except Exception:
                    pass

            # backoff and restart logic
            restart_count += 1
            if max_restarts and max_restarts > 0 and restart_count > max_restarts:
                print('Max restarts exceeded, not restarting')
                break
            runtime = time.time() - last_start_time
            backoff = backoff_base * (2 if runtime < 10 else 1)
            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Sleeping {backoff}s before restart\n")
            time.sleep(backoff)
    except KeyboardInterrupt:
        with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
            mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - Monitor received KeyboardInterrupt, exiting\n")
    except Exception:
        import traceback
        tb = traceback.format_exc()
        debug_log(f"monitor: unhandled exception:\n{tb}")
        try:
            with open(MONITOR_LOG, 'a', encoding='utf-8') as mh:
                mh.write(f"{datetime.now(timezone.utc).isoformat()}Z - monitor unhandled exception:\n{tb}\n")
        except Exception:
            pass
        # Sleep before exit to avoid tight restart loops by supervisor
        try:
            time.sleep(60)
        except Exception:
            pass
        try:
            sys.exit(1)
        except Exception:
            pass

if __name__ == '__main__':
    import os
    print(f'[monitor.py] __name__=="__main__" triggered! PID={os.getpid()} PPID={os.getppid()}')
    print('Starting monitor...')
    
    # Single-instance check: prevent duplicate monitor processes using Windows Mutex
    try:
        from single_instance import ensure_single_instance_or_exit
        ensure_single_instance_or_exit('monitor.py', allow_claim=True)
    except ImportError:
        pass  # single_instance module not available, skip check
    
    monitor_loop()
