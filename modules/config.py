import json
import os
from modules.logging_utils import file_lock, log

# Load .env file for sensitive credentials (Telegram token etc.)
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv()
except Exception:
    pass  # python-dotenv not installed — env vars from OS are still read

CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'bot_config.json')
STATE_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'bot_state.json')

# Local overrides path OUTSIDE OneDrive — never synced, never reverted.
# This file loads LAST and wins over everything.
LOCAL_OVERRIDE_PATH = os.path.join(
    os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
    'BotConfig', 'bot_config_local.json'
)

# Runtime state keys — stored in data/bot_state.json, NOT in bot_config.json
RUNTIME_STATE_KEYS = frozenset({
    'LAST_REINVEST_TS',
    'LAST_HEARTBEAT_TS',
    '_circuit_breaker_until_ts',
    'LAST_SCAN_STATS',
    '_SALDO_COOLDOWN_UNTIL',
    '_REGIME_ADJ',
    '_REGIME_RESULT',
    '_cb_trades_since_reset',
    'SYNC_ENABLED',
    'SYNC_INTERVAL_SECONDS',
    'MIN_SCORE_TO_BUY',
    'OPERATOR_ID',
})

def _default_config() -> dict:
    """Return a minimal default config dict when loading fails."""
    return {
        "LOG_FILE": "bot_log.txt",
        "LOG_LEVEL": "INFO",
        "MAX_CLOSED": 200,
    }

def _load_state() -> dict:
    """Load runtime state from data/bot_state.json.
    
    Compares OneDrive copy with local copy outside OneDrive.
    Uses the freshest version to protect against OneDrive reverts.
    """
    od_state = {}
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, encoding='utf-8') as f:
                od_state = json.load(f)
                if not isinstance(od_state, dict):
                    od_state = {}
    except Exception:
        pass
    # Compare with local copy outside OneDrive
    try:
        from core.local_state import load_freshest
        result = load_freshest(STATE_PATH, od_state)
        if result:
            result.pop('_save_ts', None)
            return result
    except Exception:
        pass
    return od_state

def _save_state(config: dict) -> None:
    """Extract and save runtime state keys to data/bot_state.json.
    
    Also mirrors to %LOCALAPPDATA%/BotConfig/state/ to protect against OneDrive reverts.
    """
    state = {k: config[k] for k in RUNTIME_STATE_KEYS if k in config}
    if not state:
        return
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    # Stamp for freshness comparison
    try:
        from core.local_state import stamp_data
        stamp_data(state)
    except Exception:
        pass
    tmp = STATE_PATH + '.tmp'
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_PATH)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass
    # Mirror to local storage outside OneDrive
    try:
        from core.local_state import mirror_to_local
        mirror_to_local(STATE_PATH, state)
    except Exception:
        pass

def load_config() -> dict:
    """
    Load config from bot_config.json + runtime state from data/bot_state.json.
    Merges both into a single dict. Ensures a dict is returned; on error returns defaults.
    Also loads config/bot_config_overrides.json (if present) and merges on top —
    this file wins over OneDrive-synced reverts for critical settings.
    """
    with file_lock:
        try:
            with open(CONFIG_PATH, encoding='utf-8') as f:
                cfg = json.load(f)
                if not isinstance(cfg, dict):
                    raise ValueError('Config JSON is not a dict')
        except FileNotFoundError:
            log(f"Config bestand ontbreekt op {CONFIG_PATH}, gebruik defaults waar mogelijk.", level='warning')
            cfg = {}
        except json.JSONDecodeError as e:
            log(f"Config JSON onjuist: {e}. Laatste bekende config wordt genegeerd, gebruik defaults.", level='error')
            cfg = {}
        except Exception as e:
            log(f"Onverwachte fout bij laden config: {e}", level='error')
            cfg = {}

    # Load local overrides (wins over OneDrive-reverted values)
    override_path = os.path.join(os.path.dirname(CONFIG_PATH), 'bot_config_overrides.json')
    try:
        if os.path.exists(override_path):
            with open(override_path, encoding='utf-8-sig') as f:
                overrides = json.load(f)
            if isinstance(overrides, dict):
                # Deep-merge nested dicts (e.g. BUDGET_RESERVATION)
                for k, v in overrides.items():
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k] = {**cfg[k], **v}
                    else:
                        cfg[k] = v
    except Exception as e:
        log(f"Override config laden mislukt ({override_path}): {e}", level='warning')

    # Load LOCAL overrides (outside OneDrive — never reverted by sync)
    try:
        if os.path.exists(LOCAL_OVERRIDE_PATH):
            with open(LOCAL_OVERRIDE_PATH, encoding='utf-8-sig') as f:
                local_overrides = json.load(f)
            if isinstance(local_overrides, dict):
                count = 0
                for k, v in local_overrides.items():
                    if k.startswith('_'):
                        continue
                    if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                        cfg[k] = {**cfg[k], **v}
                    else:
                        cfg[k] = v
                    count += 1
                if count:
                    log(f"Lokale overrides geladen: {count} params uit {LOCAL_OVERRIDE_PATH}", level='info')
    except Exception as e:
        log(f"Lokale overrides laden mislukt ({LOCAL_OVERRIDE_PATH}): {e}", level='warning')

    # Merge runtime state into config dict (in-memory)
    state = _load_state()
    for k, v in state.items():
        if k not in cfg:  # state doesn't override config if key exists in both
            cfg[k] = v

    # Sync individual TP keys → arrays (fix AI→bot sync bug)
    _sync_tp_keys(cfg)

    # HARD FLOOR: MAX_OPEN_TRADES must NEVER be below 3
    _mot = cfg.get('MAX_OPEN_TRADES')
    if _mot is not None and int(_mot) < 3:
        log(f"HARD GUARD: MAX_OPEN_TRADES={_mot} < 3 — forced to 3", level='warning')
        cfg['MAX_OPEN_TRADES'] = 3

    # Validate config against schema
    try:
        from modules.config_schema import validate_config as _validate
        issues = _validate(cfg)
        for item in issues:
            lvl = 'error' if item['severity'] == 'error' else 'warning'
            log(f"Config validatie [{item['severity'].upper()}] {item['key']}: {item['issue']}", level=lvl)
    except Exception:
        pass  # Schema module missing or broken — don't block startup

    # Override sensitive credentials from environment variables (.env / OS)
    _tg_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    if _tg_token:
        cfg['TELEGRAM_BOT_TOKEN'] = _tg_token
    _tg_chat = os.environ.get('TELEGRAM_CHAT_ID')
    if _tg_chat:
        cfg['TELEGRAM_CHAT_ID'] = _tg_chat

    return cfg

def _sync_tp_keys(cfg: dict) -> None:
    """Sync TAKE_PROFIT_TARGET_1/2/3 → TAKE_PROFIT_TARGETS array and
    PARTIAL_TP_SELL_PCT_1/2/3 → TAKE_PROFIT_PERCENTAGES array.
    Individual keys (written by AI) override array values."""
    # TP targets
    targets = list(cfg.get('TAKE_PROFIT_TARGETS', [0.025, 0.055, 0.1]))
    changed = False
    for i, key in enumerate(['TAKE_PROFIT_TARGET_1', 'TAKE_PROFIT_TARGET_2', 'TAKE_PROFIT_TARGET_3']):
        if key in cfg and i < len(targets):
            val = float(cfg[key])
            if abs(val - targets[i]) > 1e-9:
                targets[i] = val
                changed = True
    if changed:
        cfg['TAKE_PROFIT_TARGETS'] = targets

    # TP percentages
    pcts = list(cfg.get('TAKE_PROFIT_PERCENTAGES', [0.3, 0.35, 0.35]))
    changed = False
    for i, key in enumerate(['PARTIAL_TP_SELL_PCT_1', 'PARTIAL_TP_SELL_PCT_2', 'PARTIAL_TP_SELL_PCT_3']):
        if key in cfg and i < len(pcts):
            val = float(cfg[key])
            if abs(val - pcts[i]) > 1e-9:
                pcts[i] = val
                changed = True
    if changed:
        cfg['TAKE_PROFIT_PERCENTAGES'] = pcts

def _sync_overrides(config: dict) -> None:
    """Keep bot_config_overrides.json in sync with config changes.
    
    When save_config writes a key that also exists in the overrides file,
    update the overrides file too. This prevents overrides from reverting
    future config changes on next bot restart.
    """
    override_path = os.path.join(os.path.dirname(CONFIG_PATH), 'bot_config_overrides.json')
    try:
        if not os.path.exists(override_path):
            return
        with open(override_path, encoding='utf-8') as f:
            overrides = json.load(f)
        if not isinstance(overrides, dict):
            return

        changed = False
        for k, v in overrides.items():
            if k.startswith('_'):  # skip _comment etc.
                continue
            if k in config:
                new_val = config[k]
                if isinstance(v, dict) and isinstance(new_val, dict):
                    # Deep compare for nested dicts (e.g. BUDGET_RESERVATION)
                    if v != new_val:
                        overrides[k] = new_val
                        changed = True
                elif v != new_val:
                    overrides[k] = new_val
                    changed = True

        if changed:
            # HARD FLOOR: never write MAX_OPEN_TRADES < 3 to overrides
            if overrides.get('MAX_OPEN_TRADES') is not None and int(overrides['MAX_OPEN_TRADES']) < 3:
                overrides['MAX_OPEN_TRADES'] = 3
            tmp = override_path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(overrides, f, indent=2)
            os.replace(tmp, override_path)
            log("Overrides file automatisch gesynchroniseerd met config wijzigingen.", level='info')
    except Exception as e:
        log(f"Overrides sync mislukt (niet kritiek): {e}", level='debug')


def save_config(config: dict) -> None:
    """
    Sla config veilig en atomisch op met file locking (tmp + replace).
    Runtime state keys worden apart opgeslagen in data/bot_state.json.
    Overrides file wordt automatisch mee-gesynchroniseerd.
    """
    if not isinstance(config, dict):
        log("Ongeldig config object (expect dict); save geannuleerd.", level='error')
        return

    # HARD FLOOR: MAX_OPEN_TRADES must NEVER be saved below 3
    _mot = config.get('MAX_OPEN_TRADES')
    if _mot is not None and int(_mot) < 3:
        log(f"SAVE GUARD: MAX_OPEN_TRADES={_mot} < 3 — forced to 3", level='warning')
        config['MAX_OPEN_TRADES'] = 3

    # Save runtime state separately
    _save_state(config)

    # Strip runtime state keys from config before saving
    clean = {k: v for k, v in config.items() if k not in RUNTIME_STATE_KEYS}

    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    tmp_path = CONFIG_PATH + '.tmp'
    with file_lock:
        try:
            with open(tmp_path, "w", encoding='utf-8') as f:
                json.dump(clean, f, indent=2)
            os.replace(tmp_path, CONFIG_PATH)
            log("Config succesvol en atomisch opgeslagen.", level='debug')
        except Exception as e:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            log(f"Kon config niet opslaan: {e}", level='error')
            return

    # Auto-sync overrides file to prevent stale values reverting changes
    _sync_overrides(clean)

CONFIG = load_config()


def _cli_validate() -> int:
    """Dry-run config validator. Loads the merged config and reports schema
    issues. Exits non-zero on errors so this can be used in CI/pre-commit.

    Usage: python -m modules.config --validate
    """
    import sys as _sys
    cfg = load_config()
    try:
        from modules.config_schema import validate_config as _validate
    except Exception as e:
        print(f"[validate] schema module niet beschikbaar: {e}")
        return 2
    issues = _validate(cfg)
    errors = [i for i in issues if i.get('severity') == 'error']
    warnings = [i for i in issues if i.get('severity') != 'error']
    print(f"[validate] config keys: {len(cfg)}")
    print(f"[validate] errors:   {len(errors)}")
    print(f"[validate] warnings: {len(warnings)}")
    for item in issues:
        sev = str(item.get('severity', '?')).upper()
        print(f"  [{sev}] {item.get('key')}: {item.get('issue')}")
    print(f"[validate] LOCAL_OVERRIDE_PATH = {LOCAL_OVERRIDE_PATH}")
    print(f"[validate] exists = {os.path.exists(LOCAL_OVERRIDE_PATH)}")
    return 1 if errors else 0


if __name__ == '__main__':
    import sys as _sys
    if '--validate' in _sys.argv:
        _sys.exit(_cli_validate())
    print("Usage: python -m modules.config --validate")
    _sys.exit(2)

