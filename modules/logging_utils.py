import logging
import os
import json
import threading
import time
import uuid
from logging.handlers import RotatingFileHandler
import sys
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from contextvars import ContextVar

# Global re-entrant file lock that can be imported by other modules
file_lock = threading.RLock()

# Context variable for correlation IDs (thread-safe)
_correlation_id: ContextVar[str] = ContextVar('correlation_id', default='')


def get_correlation_id() -> str:
    """Get current correlation ID for request tracing."""
    return _correlation_id.get() or ''


def set_correlation_id(correlation_id: str = '') -> str:
    """Set correlation ID for current context. Returns the ID set."""
    if not correlation_id:
        correlation_id = str(uuid.uuid4())[:8]
    _correlation_id.set(correlation_id)
    return correlation_id


def clear_correlation_id() -> None:
    """Clear correlation ID after request completes."""
    _correlation_id.set('')

# Read minimal config early if available without importing modules.config to avoid circular import
def _read_config_path():
    here = os.path.dirname(__file__)
    return os.path.join(here, '..', 'config', 'bot_config.json')

def _load_log_settings():
    cfg = {}
    try:
        with open(_read_config_path(), encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg = data
    except Exception:
        cfg = {}
    return {
        'LOG_FILE': cfg.get('LOG_FILE', os.path.join('logs', 'bot_log.txt')),
        'LOG_LEVEL': cfg.get('LOG_LEVEL', 'INFO'),
        'LOG_MAX_BYTES': int(cfg.get('LOG_MAX_BYTES', 2*1024*1024)),
        'LOG_BACKUP_COUNT': int(cfg.get('LOG_BACKUP_COUNT', 5)),
        'LOG_JSON_FORMAT': cfg.get('LOG_JSON_FORMAT', False),
        'LOG_JSON_FILE': cfg.get('LOG_JSON_FILE', os.path.join('logs', 'bot_log.jsonl')),
    }

_LOG_SETTINGS = _load_log_settings()
LOG_FILE = _LOG_SETTINGS['LOG_FILE']
LOG_LEVEL = _LOG_SETTINGS['LOG_LEVEL']
LOG_MAX_BYTES = _LOG_SETTINGS['LOG_MAX_BYTES']
LOG_BACKUP_COUNT = _LOG_SETTINGS['LOG_BACKUP_COUNT']
LOG_JSON_FORMAT = _LOG_SETTINGS['LOG_JSON_FORMAT']
LOG_JSON_FILE = _LOG_SETTINGS['LOG_JSON_FILE']

# Ensure log directory exists if a path is provided
try:
    log_dir = os.path.dirname(LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
except Exception:
    pass

class SafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that tolerates Windows file locks (e.g. OneDrive)."""

    # Cap the rotation-fallback notice file. Without this it grew unbounded
    # (one append per failed rollover) — observed at 5 GB on 2026-04-30.
    _ROTATION_FALLBACK_MAX_BYTES = 1 * 1024 * 1024  # 1 MB

    def doRollover(self):
        try:
            super().doRollover()
            return
        except PermissionError as exc:
            # Another process (often OneDrive or an editor) holds the file open.
            # Skip rotation and continue logging to the current file instead of crashing.
            try:
                fallback = f"{self.baseFilename}.rotation.log"
                # Truncate if it exceeds cap to prevent unbounded growth.
                try:
                    if os.path.exists(fallback) and os.path.getsize(fallback) > self._ROTATION_FALLBACK_MAX_BYTES:
                        os.remove(fallback)
                except Exception:
                    pass
                with open(fallback, 'a', encoding=self.encoding or 'utf-8') as fh:
                    ts = datetime.utcnow().isoformat()
                    fh.write(f"{ts} WARNING rotation skipped for {self.baseFilename}: {exc}\n")
            except Exception:
                # Fallback logging failed; continue silently.
                pass
        # Ensure the handler keeps a valid stream open.
        if not self.delay:
            try:
                self.stream = self._open()
            except Exception:
                self.stream = None


stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
try:
    stream_handler.stream.reconfigure(encoding='utf-8')
except Exception:
    pass
file_handler = SafeRotatingFileHandler(
    LOG_FILE,
    maxBytes=LOG_MAX_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding='utf-8',
    delay=True,
)
file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), handlers=[file_handler, stream_handler])

# Optional JSON log handler for structured logging
_json_handler: Optional[SafeRotatingFileHandler] = None
if LOG_JSON_FORMAT:
    try:
        json_log_dir = os.path.dirname(LOG_JSON_FILE)
        if json_log_dir:
            os.makedirs(json_log_dir, exist_ok=True)
        _json_handler = SafeRotatingFileHandler(
            LOG_JSON_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8',
            delay=True,
        )
    except Exception:
        _json_handler = None


def _write_json_log(level: str, msg: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """Write structured JSON log entry to JSONL file."""
    if not _json_handler:
        return
    try:
        entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': level.upper(),
            'message': msg,
            'correlation_id': get_correlation_id() or None,
        }
        if extra:
            entry['extra'] = extra
        line = json.dumps(entry, ensure_ascii=False) + '\n'
        with file_lock:
            _json_handler.stream = _json_handler._open() if _json_handler.stream is None else _json_handler.stream
            _json_handler.stream.write(line)
            _json_handler.stream.flush()
    except Exception:
        pass  # Don't fail on JSON logging errors


def log(msg: str, level: str = 'info', extra: Optional[Dict[str, Any]] = None) -> None:
    """Log message with optional structured data.
    
    Args:
        msg: Log message
        level: Log level ('debug', 'info', 'warning', 'error')
        extra: Optional dict with extra structured data for JSON logs
    """
    # Security: prevent API keys in logs
    forbidden = [os.getenv("BITVAVO_API_KEY"), os.getenv("BITVAVO_API_SECRET")]
    for secret in forbidden:
        if secret and secret in str(msg):
            msg = msg.replace(secret, "[REDACTED]")
    
    # Add correlation ID to text message if present
    corr_id = get_correlation_id()
    display_msg = f"[{corr_id}] {msg}" if corr_id else msg
    
    with file_lock:
        if level == 'debug':
            logging.debug(display_msg)
        elif level == 'warning':
            logging.warning(display_msg)
        elif level == 'error':
            logging.error(display_msg)
        else:
            logging.info(display_msg)
    
    # Also write to JSON log if enabled
    if LOG_JSON_FORMAT:
        _write_json_log(level, msg, extra)


def log_trade(market: str, action: str, **kwargs) -> None:
    """Log trade-related event with correlation tracking.
    
    Args:
        market: Trading pair (e.g., 'BTC-EUR')
        action: Trade action ('BUY', 'SELL', 'DCA', 'SKIP', etc.)
        **kwargs: Additional structured data (price, amount, reason, etc.)
    """
    extra = {'market': market, 'action': action, **kwargs}
    msg = f"[TRADE] {action} {market}"
    if 'price' in kwargs:
        msg += f" @ {kwargs['price']}"
    if 'amount' in kwargs:
        msg += f" x {kwargs['amount']}"
    if 'reason' in kwargs:
        msg += f" ({kwargs['reason']})"
    log(msg, level='info', extra=extra)

# Utility: locked write to JSON file
def locked_write_json(filename, data, *, indent: Optional[int] = 2):
    """Atomically write JSON with retries to avoid partial writes."""
    with file_lock:
        tmp = f"{filename}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent)
        except Exception as exc:
            log(f"Kon {filename} niet schrijven: {exc}", level='error')
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
            return

        max_attempts = 5
        for attempt in range(1, max_attempts + 1):
            try:
                os.replace(tmp, filename)
                return
            except PermissionError as exc:
                if attempt == max_attempts:
                    log(f"Kon {filename} niet schrijven: {exc}", level='error')
                    break
                sleep_seconds = 0.2 * attempt
                time.sleep(sleep_seconds)
            except Exception as exc:
                log(f"Kon {filename} niet schrijven: {exc}", level='error')
                break
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass

def reconfigure_logging():
    """Reload logging settings from config and update handlers at runtime."""
    global LOG_FILE, LOG_LEVEL, LOG_MAX_BYTES, LOG_BACKUP_COUNT, file_handler, _LOG_SETTINGS
    try:
        _LOG_SETTINGS = _load_log_settings()
        LOG_FILE = _LOG_SETTINGS['LOG_FILE']
        LOG_LEVEL = _LOG_SETTINGS['LOG_LEVEL']
        LOG_MAX_BYTES = _LOG_SETTINGS['LOG_MAX_BYTES']
        LOG_BACKUP_COUNT = _LOG_SETTINGS['LOG_BACKUP_COUNT']
        # Rebuild file handler
        for h in list(logging.getLogger().handlers):
            if isinstance(h, RotatingFileHandler):
                logging.getLogger().removeHandler(h)
                try:
                    h.close()
                except Exception:
                    pass
        try:
            log_dir = os.path.dirname(LOG_FILE)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
        except Exception:
            pass
        file_handler = SafeRotatingFileHandler(
            LOG_FILE,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8',
            delay=True,
        )
        file_handler.setFormatter(logging.Formatter('[%(asctime)s] %(levelname)s: %(message)s'))
        logging.getLogger().addHandler(file_handler)
        logging.getLogger().setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        log("Logging opnieuw geconfigureerd vanuit config.", level='debug')
    except Exception as e:
        log(f"Herconfiguratie logging mislukt: {e}", level='error')
