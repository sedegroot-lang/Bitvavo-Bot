"""
Telegram Handler voor Bitvavo Bot
- Notificaties via Bot API met dedupe + quiet-hours + severity-filter (TELEGRAM_NOTIFY_LEVEL)
- Polling voor commands (geen extra library nodig)
- Auto-alerts: buy, sell, stop-loss, errors (verrijkt met score/regime/peak/hold-time)
- Commands: /start /help /status /today /week /positions /trades /orders /profit
            /performance /balance /fees /risk /market /trailing /dca /grid
            /regime /ai /why /top /config /set /pause /resume /quiet
            /health /uptime /version /log /stop /restart /update
"""

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "bot_config.json"
LOG_PATH = BASE_DIR / "logs" / "bot_log.txt"
TRADE_LOG_PATH = BASE_DIR / "data" / "trade_log.json"
GRID_STATES_PATH = BASE_DIR / "data" / "grid_states.json"
DCA_AUDIT_PATH = BASE_DIR / "data" / "dca_audit.log"
EXPECTANCY_PATH = BASE_DIR / "data" / "expectancy_stats.json"
START_BAT = BASE_DIR / "start_automated.bat"
START_PS1 = BASE_DIR / "start_automated.ps1"
_OFFSET_FILE = BASE_DIR / "data" / "telegram_offset.json"

_token = ""
_chat_id = ""
_poll_thread = None
_watch_thread = None
_last_update_id = 0
_init_done = False

# Trade watcher state
_known_open: set = set()
_known_closed_count: int = 0
_watch_initialized = False


# ──────────────────────────────────────────
# Config helpers
# ──────────────────────────────────────────
def _load_config() -> dict:
    """Laad de volledige (3-laags) merged config zoals de bot die zelf gebruikt."""
    try:
        from modules.config import load_config as _real_load
        return _real_load()
    except Exception as e:
        logger.error(f"[Telegram] Config laden mislukt: {e}")
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}


def _save_local_override(key: str, parsed_value) -> None:
    """Schrijf één config-key direct naar LOCAL_OVERRIDE_PATH (layer 3).

    Layer 3 wint over alle andere lagen en wordt nooit door OneDrive teruggedraaid.
    Dot-notatie (bijv. GRID_TRADING.enabled) wordt vertaald naar een geneste dict
    waarbij de parent UPPERCASE is maar de child de originele case behoudt
    (bot config gebruikt lowercase children zoals 'enabled', 'trailing_pct').
    """
    from modules.config import LOCAL_OVERRIDE_PATH
    local_path = Path(LOCAL_OVERRIDE_PATH)
    try:
        local_overrides = json.loads(local_path.read_text(encoding="utf-8-sig")) if local_path.exists() else {}
        if not isinstance(local_overrides, dict):
            local_overrides = {}
    except Exception:
        local_overrides = {}

    if "." in key:
        parent_raw, child_raw = key.split(".", 1)
        parent = parent_raw.upper()  # parent altijd UPPERCASE
        child = child_raw  # child case behouden (bot config = lowercase)
        if parent not in local_overrides or not isinstance(local_overrides[parent], dict):
            local_overrides[parent] = {}
        local_overrides[parent][child] = parsed_value
    else:
        local_overrides[key.upper()] = parsed_value

    local_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(local_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(local_overrides, f, indent=2, ensure_ascii=False)
    os.replace(tmp, str(local_path))


def _reload_credentials() -> None:
    global _token, _chat_id
    cfg = _load_config()
    _token = cfg.get("TELEGRAM_BOT_TOKEN", "").strip()
    _chat_id = str(cfg.get("TELEGRAM_CHAT_ID", "")).strip()


def _save_chat_id(chat_id: str) -> None:
    global _chat_id
    _save_local_override("TELEGRAM_CHAT_ID", chat_id)
    _chat_id = chat_id
    logger.info(f"[Telegram] Chat ID opgeslagen: {chat_id}")


# ──────────────────────────────────────────
# Berichten sturen
# ──────────────────────────────────────────
def send_message(text: str, parse_mode: str = "HTML") -> bool:
    if not _token or not _chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{_token}/sendMessage"
        resp = requests.post(url, json={
            "chat_id": _chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }, timeout=10)
        if not resp.ok:
            logger.warning(f"[Telegram] sendMessage fout: {resp.text[:200]}")
        return resp.ok
    except Exception as e:
        logger.error(f"[Telegram] sendMessage exception: {e}")
        return False


_TRADE_KEYWORDS = ("KOOP", "VERKOOP", "koop", "verkoop", "BUY", "SELL", "gekocht", "verkocht", "DCA", "partial tp")
_CRITICAL_KEYWORDS = (
    "CRITICAL", "WATCHDOG", "OOM", "DRAWDOWN", "CIRCUIT",
    "portfolio drawdown", "daily loss", "kill switch", "KILL-SWITCH",
)
_ALERT_KEYWORDS = (
    "ERROR", "STALE", "sync_removed", "API glitch", "stale buy_price", "RISK",
    "\u26a0\ufe0f", "\ud83d\udd34", "\u2757",  # warning/red emoji
)

# ── Noise-control state (dedupe + burst-collapse + quiet-hours) ──
_alert_dedupe: dict = {}     # key (normalized text) -> {ts, count}
_alert_burst: dict = {}      # key -> list of recent timestamps for burst detection
_quiet_override = False      # /quiet on overrules config quiet hours
_DEFAULT_DEDUPE_S = 900      # 15 min — same alert not re-sent
_BURST_WINDOW = 300          # 5 min window to count repeats
_BURST_THRESHOLD = 5         # if >=5 same alerts in 5 min → collapsed summary instead


def _normalize_for_dedupe(text: str) -> str:
    """Strip numbers/timestamps so 'X at €1.23' and 'X at €1.45' dedupe to same key."""
    import re
    s = text.lower()
    s = re.sub(r"[\d.,:€$+\-]+", "#", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:120]


def _in_quiet_hours(cfg: dict) -> bool:
    """True if current local time falls within configured quiet window."""
    if _quiet_override:
        return True
    try:
        start = str(cfg.get("TELEGRAM_QUIET_START", "")).strip()
        end = str(cfg.get("TELEGRAM_QUIET_END", "")).strip()
        if not start or not end:
            return False
        sh, sm = [int(x) for x in start.split(":")[:2]]
        eh, em = [int(x) for x in end.split(":")[:2]]
        now = time.localtime()
        cur = now.tm_hour * 60 + now.tm_min
        s_min = sh * 60 + sm
        e_min = eh * 60 + em
        if s_min <= e_min:
            return s_min <= cur < e_min
        # window crosses midnight (e.g. 22:00 → 07:00)
        return cur >= s_min or cur < e_min
    except Exception:
        return False


def _classify(text: str) -> str:
    """Return 'trade' | 'critical' | 'alert' | 'info'."""
    low = text.lower()
    if any(kw.lower() in low for kw in _TRADE_KEYWORDS):
        return "trade"
    if any(kw.lower() in low for kw in _CRITICAL_KEYWORDS):
        return "critical"
    if any(kw.lower() in low for kw in _ALERT_KEYWORDS):
        return "alert"
    return "info"


def notify(text: str) -> None:
    """Forward trade events AND error/risk alerts to Telegram with dedupe + quiet-hours.

    Severity ladder: trade > critical > alert > info.
    Filtered by TELEGRAM_NOTIFY_LEVEL ('trades' | 'alerts' | 'verbose').
      - 'trades'  → only buy/sell + critical
      - 'alerts'  → trades + critical + alert  (default)
      - 'verbose' → everything (also info)

    Quiet hours suppress alert+info, but never trade or critical.
    Repeats of the same normalized message within ALERT_DEDUPE_SECONDS are dropped.
    Bursts (>=5 same alerts in 5 min) are collapsed into a single summary.
    """
    if not text:
        return
    cfg = _load_config()
    level = str(cfg.get("TELEGRAM_NOTIFY_LEVEL", "alerts")).lower()
    severity = _classify(text)

    # Severity vs configured level filter
    if level == "trades" and severity not in ("trade", "critical"):
        return
    if level == "alerts" and severity == "info":
        return
    # 'verbose' lets everything through

    # Quiet hours — block alert+info but always allow trade+critical
    if severity in ("alert", "info") and _in_quiet_hours(cfg):
        return

    now = time.time()
    dedupe_s = int(cfg.get("ALERT_DEDUPE_SECONDS", _DEFAULT_DEDUPE_S))

    # Dedupe + burst-collapse only for non-trade messages
    if severity != "trade":
        key = _normalize_for_dedupe(text)
        last = _alert_dedupe.get(key)
        if last and (now - last["ts"]) < dedupe_s:
            last["count"] = last.get("count", 1) + 1
            # Track for burst detection
            burst = _alert_burst.setdefault(key, [])
            burst.append(now)
            burst[:] = [t for t in burst if now - t < _BURST_WINDOW]
            if len(burst) == _BURST_THRESHOLD:  # exactly at threshold → send summary
                send_message(
                    f"🔁 <b>Burst:</b> {len(burst)}× zelfde alert in {_BURST_WINDOW//60} min\n"
                    f"<code>{__import__('html').escape(text[:300])}</code>"
                )
            return  # silently dropped (within dedupe window)
        _alert_dedupe[key] = {"ts": now, "count": 1}
        _alert_burst[key] = [now]

        # Cleanup stale dedupe entries (cap memory)
        if len(_alert_dedupe) > 200:
            cutoff = now - max(dedupe_s, 3600)
            _alert_dedupe.clear()
            _alert_dedupe.update({k: v for k, v in list(_alert_dedupe.items()) if v["ts"] > cutoff})

    # Format prefix per severity
    if severity == "trade":
        send_message(text)
    elif severity == "critical":
        send_message(f"🚨 <b>CRITICAL:</b>\n{text}")
    elif severity == "alert":
        send_message(f"⚠️ ALERT:\n{text}")
    else:  # info (verbose mode)
        send_message(f"ℹ️ {text}")


# ──────────────────────────────────────────
# Live prijs via Bitvavo API
# ──────────────────────────────────────────
def _get_price(market: str) -> float:
    try:
        r = requests.get(
            "https://api.bitvavo.com/v2/ticker/price",
            params={"market": market},
            timeout=5,
        )
        if r.ok:
            return float(r.json().get("price", 0) or 0)
    except Exception:
        pass
    return 0.0


# ──────────────────────────────────────────
# /status
# ──────────────────────────────────────────
def _get_status_text() -> str:
    try:
        cfg = _load_config()
        lines = []
        if LOG_PATH.exists():
            with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                lines = [l.rstrip() for l in f.readlines()[-5:] if l.strip()]

        sleep = cfg.get("SLEEP_SECONDS", "?")
        ai_enabled = cfg.get("AI_ENABLED", False)
        grid_on = cfg.get("GRID_TRADING", {}).get("enabled", False)
        budget = cfg.get("MAX_INVESTMENT_EUR", "?")
        profit_target = cfg.get("PROFIT_TARGET_PCT", "?")
        stop_loss = cfg.get("STOP_LOSS_PCT", "?")

        open_count = 0
        try:
            d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
            open_count = len(d.get("open", {}))
        except Exception:
            pass

        return (
            "<b>📊 Bitvavo Bot Status</b>\n"
            f"⏱ Sleep: {sleep}s\n"
            f"💰 Budget: €{budget}\n"
            f"🎯 Profit target: {profit_target}%\n"
            f"🛑 Stop loss: {stop_loss}%\n"
            f"🤖 AI: {'✅' if ai_enabled else '❌'}\n"
            f"📐 Grid: {'✅' if grid_on else '❌'}\n"
            f"📂 Open trades: {open_count}\n\n"
            "<b>Laatste log:</b>\n"
            + "\n".join(f"<code>{__import__('html').escape(l[-120:])}</code>" for l in lines)
        )
    except Exception as e:
        return f"Status ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /trades
# ──────────────────────────────────────────
def _get_trades_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        open_trades = d.get("open", {})
        if not open_trades:
            return "📂 <b>Geen open trades.</b>"

        lines = ["<b>📂 Open posities</b>\n"]
        total_invested = 0.0
        total_pnl = 0.0

        for market, trade in open_trades.items():
            buy_price = float(trade.get("buy_price") or 0)
            amount = float(trade.get("amount") or 0)
            invested = float(trade.get("invested_eur") or trade.get("total_invested_eur") or 0)
            dca = int(trade.get("dca_buys") or 0)

            current_price = _get_price(market)
            if current_price > 0 and buy_price > 0:
                pnl_pct = (current_price - buy_price) / buy_price * 100
                pnl_eur = (current_price - buy_price) * amount
            else:
                pnl_pct = 0.0
                pnl_eur = 0.0

            total_invested += invested
            total_pnl += pnl_eur

            emoji = "🟢" if pnl_pct >= 0 else "🔴"
            sign = "+" if pnl_pct >= 0 else ""
            lines.append(
                f"{emoji} <b>{market}</b>\n"
                f"  Gekocht: €{buy_price:.4f} | Nu: €{current_price:.4f}\n"
                f"  P&amp;L: {sign}{pnl_pct:.2f}% ({sign}€{pnl_eur:.2f})"
                + (f" | DCA: {dca}x" if dca else "")
            )

        total_sign = "+" if total_pnl >= 0 else ""
        lines.append(f"\n<b>Totaal geïnvesteerd: €{total_invested:.2f}</b>")
        lines.append(f"<b>Totaal P&amp;L: {total_sign}€{total_pnl:.2f}</b>")
        return "\n".join(lines)
    except Exception as e:
        return f"Trades ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /profit
# ──────────────────────────────────────────
def _get_profit_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        closed = d.get("closed", [])
        if not closed:
            return "📈 <b>Nog geen gesloten trades.</b>"

        today_ts = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        week_ts = today_ts - 7 * 86400

        today_trades = [t for t in closed if float(t.get("timestamp") or 0) >= today_ts]
        week_trades = [t for t in closed if float(t.get("timestamp") or 0) >= week_ts]

        def pnl(trades):
            return sum(float(t.get("profit") or 0) for t in trades)

        def wins(trades):
            return sum(1 for t in trades if float(t.get("profit") or 0) > 0)

        p_today = pnl(today_trades)
        p_week = pnl(week_trades)
        p_total = pnl(closed)

        sorted_closed = sorted(closed, key=lambda t: float(t.get("profit") or 0))
        worst = sorted_closed[0] if sorted_closed else {}
        best = sorted_closed[-1] if sorted_closed else {}

        s = lambda x: "+" if x >= 0 else ""
        return (
            "<b>📈 Profit Overzicht</b>\n\n"
            f"<b>Vandaag</b> ({len(today_trades)} trades): {s(p_today)}€{p_today:.2f}\n"
            f"<b>Deze week</b> ({len(week_trades)} trades): {s(p_week)}€{p_week:.2f}\n"
            f"<b>Totaal</b> ({len(closed)} trades): {s(p_total)}€{p_total:.2f}\n\n"
            f"Winratio vandaag: {wins(today_trades)}/{len(today_trades) or 1}\n"
            f"Winratio totaal: {wins(closed)}/{len(closed)}\n\n"
            f"🏆 Beste: <b>{best.get('market','?')}</b> +€{float(best.get('profit',0)):.2f}\n"
            f"💀 Slechtste: <b>{worst.get('market','?')}</b> €{float(worst.get('profit',0)):.2f}"
        )
    except Exception as e:
        return f"Profit ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /log
# ──────────────────────────────────────────
def _get_log_text(n: int = 20) -> str:
    try:
        if not LOG_PATH.exists():
            return "Log bestand niet gevonden."
        with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        lines = [l.rstrip() for l in lines[-n:] if l.strip()]
        return f"<b>📋 Laatste {len(lines)} log regels:</b>\n" + \
               "\n".join(f"<code>{l[-120:]}</code>" for l in lines)
    except Exception as e:
        return f"Log ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /set
# ──────────────────────────────────────────
ALLOWED_KEYS = {
    "SLEEP_SECONDS": int,
    "MAX_INVESTMENT_EUR": float,
    "PROFIT_TARGET_PCT": float,
    "STOP_LOSS_PCT": float,
    "MIN_SCORE": float,
    "MIN_SCORE_TO_BUY": float,
    "AI_ENABLED": bool,
    "GRID_TRADING.enabled": bool,
    "GRID_TRADING.investment_per_grid": float,
    "GRID_TRADING.max_grids": int,
    "MAX_OPEN_TRADES": int,
    "BASE_AMOUNT_EUR": float,
    "DCA_ENABLED": bool,
    "DCA_MAX_BUYS": int,
    "DCA_DROP_PCT": float,
    "DCA_AMOUNT_EUR": float,
    "HARD_SL_ALT_PCT": float,
    "HARD_SL_BTCETH_PCT": float,
    "DEFAULT_TRAILING": float,
    "TRAILING_ACTIVATION_PCT": float,
    "ALERT_DEDUPE_SECONDS": int,
    "BUDGET_RESERVATION.trailing_pct": float,
    "BUDGET_RESERVATION.grid_pct": float,
    "BUDGET_RESERVATION.reserve_pct": float,
    "BUDGET_RESERVATION.min_reserve_eur": float,
    "BUDGET_RESERVATION.mode": str,
    # Telegram noise/UX tuning
    "TELEGRAM_NOTIFY_LEVEL": str,    # 'trades' | 'alerts' | 'verbose'
    "TELEGRAM_QUIET_START": str,     # "HH:MM" — start quiet hours
    "TELEGRAM_QUIET_END": str,       # "HH:MM" — end quiet hours
}


def _apply_set_command(key: str, value: str) -> str:
    # Voor dot-keys: parent UPPERCASE, child case-preserve voor lookup
    if "." in key:
        parent_raw, child_raw = key.split(".", 1)
        canonical_key = f"{parent_raw.upper()}.{child_raw}"
    else:
        canonical_key = key.upper()

    # Case-insensitive lookup zodat /set BUDGET_RESERVATION.TRAILING_PCT en
    # /set budget_reservation.trailing_pct beide werken
    matched_key = None
    matched_typ = None
    for allowed_key, allowed_typ in ALLOWED_KEYS.items():
        if allowed_key.lower() == canonical_key.lower():
            matched_key = allowed_key  # gebruik exacte casing uit ALLOWED_KEYS (lowercase children!)
            matched_typ = allowed_typ
            break

    if matched_key is None:
        return (
            f"❌ Onbekende parameter: <code>{key}</code>\n\n"
            "Toegestane parameters:\n"
            + "\n".join(f"• <code>{k}</code>" for k in sorted(ALLOWED_KEYS))
        )
    try:
        typ = matched_typ
        if typ == bool:
            parsed = value.lower() in ("true", "1", "yes", "ja", "aan", "on")
        elif typ == str:
            parsed = value
        else:
            parsed = typ(value)
        _save_local_override(matched_key, parsed)
        from modules.config import LOCAL_OVERRIDE_PATH
        return (
            f"✅ <code>{matched_key}</code> = <code>{parsed}</code>\n"
            f"📁 Opgeslagen in: <code>%LOCALAPPDATA%/BotConfig/bot_config_local.json</code>\n"
            f"⏱️ Actief na volgende bot-loop (~25s)."
        )
    except Exception as e:
        return f"❌ Fout bij instellen: {e}"



# ──────────────────────────────────────────
# /stop en /restart
# ──────────────────────────────────────────
def _stop_bot() -> str:
    try:
        result = subprocess.run(
            ["taskkill", "/F", "/IM", "python.exe"],
            capture_output=True, text=True, timeout=10
        )
        return "🛑 <b>Bot gestopt.</b>\nAlle Python processen beëindigd."
    except Exception as e:
        return f"❌ Stop mislukt: {e}"


def _save_offset() -> None:
    """Sla _last_update_id op naar bestand zodat herstart niet opnieuw pollt."""
    try:
        _OFFSET_FILE.write_text(json.dumps({"offset": _last_update_id}), encoding="utf-8")
    except Exception:
        pass


def _load_offset() -> int:
    """Laad opgeslagen offset (0 als bestand niet bestaat)."""
    try:
        return json.loads(_OFFSET_FILE.read_text(encoding="utf-8")).get("offset", 0)
    except Exception:
        return 0


def _restart_bot() -> None:
    """Start een nieuw bot-proces en kill daarna het huidige.

    1) Sla Telegram offset op (voorkomt restart-loop)
    2) Start nieuw proces via PowerShell -SkipCleanup (geen taskkill)
    3) Kill alleen het huidige Python-proces tree
    """
    def _do():
        time.sleep(1)
        try:
            # 1) Sla offset op zodat nieuwe bot /restart niet opnieuw verwerkt
            _save_offset()

            # 2) Start nieuw bot-proces via ps1 met -SkipCleanup
            #    (geen taskkill in ps1, zodat het nieuwe proces niet gedood wordt)
            ps1_path = str(START_PS1)
            cmd = [
                "powershell", "-NoExit", "-ExecutionPolicy", "Bypass",
                "-File", ps1_path, "-SkipCleanup",
            ]
            subprocess.Popen(
                cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            time.sleep(3)

            # 3) Kill het huidige proces + alle child-processen
            my_pid = os.getpid()
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(my_pid)],
                capture_output=True, timeout=10,
            )
        except Exception as e:
            logger.error(f"[Telegram] Herstart mislukt: {e}")
    t = threading.Thread(target=_do, daemon=False)
    t.start()


def _git_pull_and_restart() -> None:
    """Voer git pull uit in BASE_DIR en herstart daarna de bot.

    Stuurt een Telegram-bericht met de uitvoer van git pull.
    Bij een fout wordt een foutmelding gestuurd en wordt NIET herstart.
    """
    def _do():
        time.sleep(1)
        try:
            result = subprocess.run(
                ["git", "pull"],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = (result.stdout or "").strip() or (result.stderr or "").strip() or "(geen uitvoer)"
            if result.returncode != 0:
                send_message(
                    f"❌ <b>git pull mislukt (code {result.returncode}):</b>\n<pre>{output[:500]}</pre>\n"
                    "Bot wordt <b>niet</b> herstart."
                )
                return
            send_message(
                f"✅ <b>git pull geslaagd:</b>\n<pre>{output[:500]}</pre>\n"
                "🔄 Bot wordt nu herstart…"
            )
            time.sleep(2)
            _restart_bot()
        except Exception as e:
            send_message(f"❌ <b>Update mislukt:</b> {e}")
            logger.error(f"[Telegram] /update mislukt: {e}")

    t = threading.Thread(target=_do, daemon=False)
    t.start()


# ──────────────────────────────────────────
# /trailing — Trailing stop info for open trades
# ──────────────────────────────────────────
def _get_trailing_text() -> str:
    try:
        cfg = _load_config()
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        open_trades = d.get("open", {})
        if not open_trades:
            return "🎯 <b>Geen open trailing posities.</b>"

        activation_pct = float(cfg.get("TRAILING_ACTIVATION_PCT", 0.025)) * 100
        default_trail = float(cfg.get("DEFAULT_TRAILING", 0.04)) * 100
        levels = cfg.get("STEPPED_TRAILING_LEVELS", [])

        lines = [
            f"<b>🎯 Trailing Stop Overzicht</b>\n",
            f"Activatie: {activation_pct:.1f}% | Default trail: {default_trail:.1f}%\n",
        ]

        for market, trade in open_trades.items():
            bp = float(trade.get("buy_price") or 0)
            hp = float(trade.get("highest_price") or 0)
            amt = float(trade.get("amount") or 0)
            invested = float(trade.get("invested_eur") or trade.get("total_invested_eur") or 0)
            activated = trade.get("trailing_activated", False)
            cp = _get_price(market)

            if bp <= 0:
                continue

            profit_pct = ((cp - bp) / bp * 100) if cp > 0 else 0
            highest_pct = ((hp - bp) / bp * 100) if hp > 0 else 0
            pnl_eur = (cp - bp) * amt if cp > 0 else 0

            # Determine current trail level
            trail_pct = default_trail
            for level_profit, level_trail in levels:
                if highest_pct / 100 >= level_profit:
                    trail_pct = level_trail * 100

            status_icon = "🟢" if activated else "⏳"
            sign = "+" if profit_pct >= 0 else ""

            lines.append(
                f"\n{status_icon} <b>{market}</b>"
                f" {'(trailing actief!)' if activated else ''}\n"
                f"  Koop: €{bp:.4f} | Nu: €{cp:.4f}\n"
                f"  P&amp;L: {sign}{profit_pct:.2f}% ({sign}€{pnl_eur:.2f})\n"
                f"  Hoogste: €{hp:.4f} ({highest_pct:+.1f}%)\n"
                f"  Trail: {trail_pct:.1f}%"
                + (f" | Invested: €{invested:.2f}" if invested > 0 else "")
            )

        return "\n".join(lines)
    except Exception as e:
        return f"Trailing info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /dca — DCA status for open trades
# ──────────────────────────────────────────
def _get_dca_text() -> str:
    try:
        cfg = _load_config()
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        open_trades = d.get("open", {})

        dca_enabled = cfg.get("DCA_ENABLED", False)
        dca_max = cfg.get("DCA_MAX_BUYS", 1)
        dca_drop = float(cfg.get("DCA_DROP_PCT", 0.025)) * 100
        dca_amount = cfg.get("DCA_AMOUNT_EUR", 5)
        dca_hybrid = cfg.get("DCA_HYBRID", False)
        rsi_threshold = cfg.get("RSI_DCA_THRESHOLD", 35)

        lines = [
            f"<b>💉 DCA Overzicht</b>\n",
            f"Status: {'✅ Aan' if dca_enabled else '❌ Uit'}\n"
            f"Max buys: {dca_max} | Drop: {dca_drop:.1f}%\n"
            f"Bedrag: €{dca_amount} | RSI drempel: {rsi_threshold}\n"
            f"Hybrid: {'✅' if dca_hybrid else '❌'}\n",
        ]

        if not open_trades:
            lines.append("Geen open posities.")
            return "\n".join(lines)

        for market, trade in open_trades.items():
            bp = float(trade.get("buy_price") or 0)
            dca_buys = int(trade.get("dca_buys") or 0)
            dca_max_local = int(trade.get("dca_max") or dca_max)
            next_price = float(trade.get("dca_next_price") or 0)
            cp = _get_price(market)

            if bp <= 0:
                continue

            drop_to_next = ((next_price - cp) / cp * 100) if cp > 0 and next_price > 0 else 0

            emoji = "✅" if dca_buys >= dca_max_local else ("⏳" if dca_buys > 0 else "🔵")
            lines.append(
                f"\n{emoji} <b>{market}</b>\n"
                f"  DCA: {dca_buys}/{dca_max_local}"
                + (f" | Volgende @ €{next_price:.4f} ({drop_to_next:+.1f}%)" if dca_buys < dca_max_local and next_price > 0 else " (max bereikt)")
            )

        # Show last DCA audit events
        try:
            if DCA_AUDIT_PATH.exists():
                with open(DCA_AUDIT_PATH, encoding="utf-8") as f:
                    audit_lines = f.readlines()
                recent = audit_lines[-5:] if len(audit_lines) >= 5 else audit_lines
                if recent:
                    lines.append("\n<b>Laatste DCA events:</b>")
                    for al in recent:
                        try:
                            ev = json.loads(al.strip())
                            ts = time.strftime("%H:%M", time.localtime(ev.get("ts", 0)))
                            lines.append(f"  <code>{ts} {ev.get('market','?')} {ev.get('status','?')}: {ev.get('reason','?')}</code>")
                        except Exception:
                            pass
        except Exception:
            pass

        return "\n".join(lines)
    except Exception as e:
        return f"DCA info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /grid — Grid bot dashboard
# ──────────────────────────────────────────
def _get_grid_text() -> str:
    try:
        cfg = _load_config()
        gcfg = cfg.get("GRID_TRADING", {})
        grid_enabled = gcfg.get("enabled", False)

        lines = [
            f"<b>📐 Grid Bot Dashboard</b>\n",
            f"Status: {'✅ Aan' if grid_enabled else '❌ Uit'}\n"
            f"Max grids: {gcfg.get('max_grids', 2)} | Per grid: €{gcfg.get('investment_per_grid', 65)}\n"
            f"Levels: {gcfg.get('num_grids', 10)} | SL: {float(gcfg.get('stop_loss_pct', 0.08))*100:.0f}%\n",
        ]

        if not GRID_STATES_PATH.exists():
            lines.append("Geen actieve grids.")
            return "\n".join(lines)

        grid_data = json.loads(GRID_STATES_PATH.read_text(encoding="utf-8"))
        grids = grid_data if isinstance(grid_data, dict) else {}

        if not grids:
            lines.append("Geen actieve grids.")
            return "\n".join(lines)

        total_profit = 0.0
        total_trades = 0
        total_fees = 0.0

        for market, state in grids.items():
            if not isinstance(state, dict):
                continue
            status = state.get("status", "?")
            config = state.get("config", {})
            profit = float(state.get("total_profit", 0) or 0)
            trades = int(state.get("total_trades", 0) or 0)
            fees = float(state.get("total_fees", 0) or 0)
            lower = float(config.get("lower_price", 0) or 0)
            upper = float(config.get("upper_price", 0) or 0)
            investment = float(config.get("total_investment", 0) or 0)
            cp = _get_price(market)

            total_profit += profit
            total_trades += trades
            total_fees += fees

            # Count open orders
            levels = state.get("levels", [])
            placed_buys = sum(1 for l in levels if isinstance(l, dict) and l.get("status") == "placed" and l.get("side") == "buy")
            placed_sells = sum(1 for l in levels if isinstance(l, dict) and l.get("status") == "placed" and l.get("side") == "sell")

            status_icon = "🟢" if status == "running" else ("🟡" if status in ("initialized", "placing_orders") else "🔴")
            sign = "+" if profit >= 0 else ""
            in_range = "✅" if lower <= cp <= upper and cp > 0 else "⚠️"

            lines.append(
                f"\n{status_icon} <b>{market}</b> ({status})\n"
                f"  Range: €{lower:.2f} – €{upper:.2f} {in_range}\n"
                f"  Nu: €{cp:.2f} | Investering: €{investment:.0f}\n"
                f"  Orders: {placed_buys} koop / {placed_sells} verkoop\n"
                f"  Trades: {trades} | Profit: {sign}€{profit:.2f} | Fees: €{fees:.2f}"
            )

        lines.append(
            f"\n<b>Grid totaal:</b> {total_trades} trades, "
            f"{'+'if total_profit>=0 else ''}€{total_profit:.2f} profit, €{total_fees:.2f} fees"
        )
        return "\n".join(lines)
    except Exception as e:
        return f"Grid info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /balance — EUR balance en budget verdeling
# ──────────────────────────────────────────
def _get_balance_text() -> str:
    try:
        cfg = _load_config()
        budget_cfg = cfg.get("BUDGET_RESERVATION", {})
        trailing_pct = float(budget_cfg.get("trailing_pct", 75))
        grid_pct = float(budget_cfg.get("grid_pct", 25))
        reserve_pct = float(budget_cfg.get("reserve_pct", 0))

        # Get account overview if available
        overview_path = BASE_DIR / cfg.get("ACCOUNT_OVERVIEW_FILE", "data/account_overview.json")
        total_eur = 0.0
        eur_available = 0.0
        eur_in_order = 0.0
        if overview_path.exists():
            try:
                ov = json.loads(overview_path.read_text(encoding="utf-8"))
                total_eur = float(ov.get("total_eur", 0) or 0)
                eur_available = float(ov.get("eur_available", 0) or 0)
                eur_in_order = float(ov.get("eur_in_order", 0) or 0)
            except Exception:
                pass

        # Calculate budgets
        reserve_eur = float(budget_cfg.get("min_reserve_eur", 0))
        usable = max(0, total_eur - reserve_eur)
        trailing_budget = usable * trailing_pct / 100
        grid_budget = usable * grid_pct / 100

        # Count invested in open trades
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        open_trades = d.get("open", {})
        total_invested = sum(
            float(t.get("invested_eur") or t.get("total_invested_eur") or 0)
            for t in open_trades.values()
        )

        max_trades = int(cfg.get("MAX_OPEN_TRADES", 5))
        base_eur = float(cfg.get("BASE_AMOUNT_EUR", 12))
        dca_max = int(cfg.get("DCA_MAX_BUYS", 1))
        dca_eur = float(cfg.get("DCA_AMOUNT_EUR", 5))
        max_per_trade = base_eur + (dca_max * dca_eur)
        max_trailing_needed = max_trades * max_per_trade

        return (
            "<b>💰 Balance &amp; Budget</b>\n\n"
            f"<b>EUR Balans:</b>\n"
            f"  Totaal: €{total_eur:.2f}\n"
            f"  Beschikbaar: €{eur_available:.2f}\n"
            f"  In orders: €{eur_in_order:.2f}\n\n"
            f"<b>Budget verdeling ({budget_cfg.get('mode', 'static')}):</b>\n"
            f"  Trailing: {trailing_pct:.0f}% = €{trailing_budget:.2f}\n"
            f"  Grid: {grid_pct:.0f}% = €{grid_budget:.2f}\n"
            f"  Reserve: {reserve_pct:.0f}% (min €{reserve_eur:.0f})\n\n"
            f"<b>Trailing Bot gebruik:</b>\n"
            f"  Open trades: {len(open_trades)}/{max_trades}\n"
            f"  Geïnvesteerd: €{total_invested:.2f} / €{trailing_budget:.2f}\n"
            f"  Per trade: €{base_eur} + {dca_max}x€{dca_eur} DCA = max €{max_per_trade:.0f}\n"
            f"  Max nodig (vol): €{max_trailing_needed:.0f}"
        )
    except Exception as e:
        return f"Balance ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /orders — Open orders (trailing only, geen grid)
# ──────────────────────────────────────────
def _get_orders_text() -> str:
    try:
        # Fetch open orders from Bitvavo API
        cfg = _load_config()
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        open_trades = d.get("open", {})

        # Get grid markets to exclude
        grid_markets = set()
        if GRID_STATES_PATH.exists():
            try:
                gs = json.loads(GRID_STATES_PATH.read_text(encoding="utf-8"))
                grid_markets = set(gs.keys()) if isinstance(gs, dict) else set()
            except Exception:
                pass

        lines = ["<b>📋 Open Orders (Trailing Bot)</b>\n"]

        trailing_orders = []
        for market, trade in open_trades.items():
            if market in grid_markets:
                continue  # Skip grid markets
            bp = float(trade.get("buy_price") or 0)
            amt = float(trade.get("amount") or 0)
            invested = float(trade.get("invested_eur") or 0)
            cp = _get_price(market)
            pnl = (cp - bp) * amt if cp > 0 and bp > 0 else 0
            trailing_orders.append((market, bp, amt, invested, cp, pnl))

        if not trailing_orders:
            lines.append("Geen open trailing orders.")
        else:
            for market, bp, amt, invested, cp, pnl in trailing_orders:
                sign = "+" if pnl >= 0 else ""
                lines.append(
                    f"{'🟢' if pnl >= 0 else '🔴'} <b>{market}</b>\n"
                    f"  €{bp:.4f} → €{cp:.4f} | {sign}€{pnl:.2f}"
                )

        # Show grid order count separately
        if grid_markets:
            grid_order_count = 0
            if GRID_STATES_PATH.exists():
                try:
                    gs = json.loads(GRID_STATES_PATH.read_text(encoding="utf-8"))
                    for m, state in gs.items():
                        if isinstance(state, dict):
                            levels = state.get("levels", [])
                            grid_order_count += sum(1 for l in levels if isinstance(l, dict) and l.get("status") == "placed")
                except Exception:
                    pass
            lines.append(f"\n<i>Grid orders ({grid_order_count} stuks) staan in /grid</i>")

        return "\n".join(lines)
    except Exception as e:
        return f"Orders ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /performance — Win rate en statistieken
# ──────────────────────────────────────────
def _get_performance_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        closed = d.get("closed", [])
        if not closed:
            return "📊 <b>Nog geen data voor performance.</b>"

        profits = [float(t.get("profit") or 0) for t in closed]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p < 0]
        total_profit = sum(profits)
        win_rate = len(wins) / len(profits) * 100 if profits else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else float('inf')

        # Calculate streaks
        max_win_streak = 0
        max_loss_streak = 0
        cur_win = 0
        cur_loss = 0
        for p in profits:
            if p > 0:
                cur_win += 1
                cur_loss = 0
                max_win_streak = max(max_win_streak, cur_win)
            elif p < 0:
                cur_loss += 1
                cur_win = 0
                max_loss_streak = max(max_loss_streak, cur_loss)
            else:
                cur_win = 0
                cur_loss = 0

        # Hold time
        hold_times = []
        for t in closed:
            opened = float(t.get("opened_ts") or t.get("timestamp_open") or 0)
            closed_ts = float(t.get("timestamp") or 0)
            if opened > 0 and closed_ts > opened:
                hold_times.append(closed_ts - opened)
        avg_hold = sum(hold_times) / len(hold_times) if hold_times else 0
        avg_hold_h = avg_hold / 3600

        # Top/worst markets
        market_stats = {}
        for t in closed:
            m = t.get("market", "?")
            market_stats.setdefault(m, []).append(float(t.get("profit") or 0))
        top_markets = sorted(market_stats.items(), key=lambda x: sum(x[1]), reverse=True)[:3]
        worst_markets = sorted(market_stats.items(), key=lambda x: sum(x[1]))[:3]

        lines = [
            "<b>📊 Performance Dashboard</b>\n",
            f"Totaal trades: {len(profits)}",
            f"Winst: {len(wins)} | Verlies: {len(losses)}",
            f"Win rate: <b>{win_rate:.1f}%</b>",
            f"Profit factor: <b>{profit_factor:.2f}</b>",
            f"\nGem. winst: +€{avg_win:.2f}",
            f"Gem. verlies: €{avg_loss:.2f}",
            f"Totaal P&amp;L: <b>{'+'if total_profit>=0 else ''}€{total_profit:.2f}</b>",
            f"\nMax win streak: {max_win_streak}",
            f"Max loss streak: {max_loss_streak}",
            f"Gem. hold time: {avg_hold_h:.1f}u",
        ]

        if top_markets:
            lines.append("\n<b>🏆 Top markten:</b>")
            for m, profs in top_markets:
                lines.append(f"  {m}: +€{sum(profs):.2f} ({len(profs)} trades)")

        if worst_markets and sum(worst_markets[0][1]) < 0:
            lines.append("\n<b>💀 Slechtste markten:</b>")
            for m, profs in worst_markets:
                if sum(profs) < 0:
                    lines.append(f"  {m}: €{sum(profs):.2f} ({len(profs)} trades)")

        return "\n".join(lines)
    except Exception as e:
        return f"Performance ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /config — Show current config summary
# ──────────────────────────────────────────
def _get_config_text() -> str:
    try:
        cfg = _load_config()
        budget = cfg.get("BUDGET_RESERVATION", {})
        grid = cfg.get("GRID_TRADING", {})
        return (
            "<b>⚙️ Config Overzicht</b>\n\n"
            f"<b>Trading:</b>\n"
            f"  Base: €{cfg.get('BASE_AMOUNT_EUR', '?')}\n"
            f"  Max trades: {cfg.get('MAX_OPEN_TRADES', '?')}\n"
            f"  Min score: {cfg.get('MIN_SCORE_TO_BUY', '?')}\n"
            f"  Sleep: {cfg.get('SLEEP_SECONDS', '?')}s\n"
            f"\n<b>Trailing:</b>\n"
            f"  Default: {float(cfg.get('DEFAULT_TRAILING', 0.04))*100:.1f}%\n"
            f"  Activatie: {float(cfg.get('TRAILING_ACTIVATION_PCT', 0.025))*100:.1f}%\n"
            f"  Hard SL alt: {float(cfg.get('HARD_SL_ALT_PCT', 0.05))*100:.0f}%\n"
            f"  Hard SL BTC/ETH: {float(cfg.get('HARD_SL_BTCETH_PCT', 0.03))*100:.0f}%\n"
            f"\n<b>DCA:</b>\n"
            f"  Enabled: {'✅' if cfg.get('DCA_ENABLED') else '❌'}\n"
            f"  Max buys: {cfg.get('DCA_MAX_BUYS', '?')}\n"
            f"  Drop: {float(cfg.get('DCA_DROP_PCT', 0.025))*100:.1f}%\n"
            f"  Bedrag: €{cfg.get('DCA_AMOUNT_EUR', '?')}\n"
            f"  Hybrid: {'✅' if cfg.get('DCA_HYBRID') else '❌'}\n"
            f"\n<b>Grid:</b>\n"
            f"  Enabled: {'✅' if grid.get('enabled') else '❌'}\n"
            f"  Max grids: {grid.get('max_grids', '?')}\n"
            f"  Per grid: €{grid.get('investment_per_grid', '?')}\n"
            f"\n<b>Budget:</b>\n"
            f"  Mode: {budget.get('mode', 'static')}\n"
            f"  Trailing: {budget.get('trailing_pct', 55)}%\n"
            f"  Grid: {budget.get('grid_pct', 25)}%\n"
            f"\n<b>AI:</b> {'✅' if cfg.get('AI_ENABLED') else '❌'}"
            f" | Supervisor: {'✅' if cfg.get('AI_SUPERVISOR_ENABLED') else '❌'}"
        )
    except Exception as e:
        return f"Config ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /risk — Risk management status
# ──────────────────────────────────────────
def _get_risk_text() -> str:
    try:
        cfg = _load_config()
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))

        # Daily P&L
        today_ts = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        closed = d.get("closed", [])
        today_pnl = sum(float(t.get("profit") or 0) for t in closed if float(t.get("timestamp") or 0) >= today_ts)

        # Open trades risk
        open_trades = d.get("open", {})
        total_risk = 0.0
        for market, trade in open_trades.items():
            bp = float(trade.get("buy_price") or 0)
            amt = float(trade.get("amount") or 0)
            invested = float(trade.get("invested_eur") or 0)
            cp = _get_price(market)
            if cp > 0 and bp > 0:
                unrealized = (cp - bp) * amt
                if unrealized < 0:
                    total_risk += abs(unrealized)

        max_daily_loss = float(cfg.get("RISK_MAX_DAILY_LOSS", 10))
        max_drawdown = float(cfg.get("RISK_MAX_DRAWDOWN_PCT", 15))

        cb_status = "✅ OK"
        if today_pnl < -max_daily_loss:
            cb_status = "🔴 DAILY LIMIT"

        return (
            "<b>🛡️ Risk Management</b>\n\n"
            f"Dagelijks P&amp;L: {'+'if today_pnl>=0 else ''}€{today_pnl:.2f} / -€{max_daily_loss:.0f} limiet\n"
            f"Circuit breaker: {cb_status}\n"
            f"Open risico: €{total_risk:.2f} (unrealized loss)\n"
            f"Max drawdown: {max_drawdown}%\n"
            f"SL alt: {float(cfg.get('HARD_SL_ALT_PCT', 0.05))*100:.0f}%\n"
            f"SL BTC/ETH: {float(cfg.get('HARD_SL_BTCETH_PCT', 0.03))*100:.0f}%"
        )
    except Exception as e:
        return f"Risk info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /market [symbol] — Quick market check
# ──────────────────────────────────────────
def _get_market_text(symbol: str) -> str:
    try:
        market = f"{symbol.upper()}-EUR"
        price = _get_price(market)
        if price <= 0:
            return f"❌ Geen prijs gevonden voor <b>{market}</b>"

        # Check if in open trades
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        trade = d.get("open", {}).get(market)
        trade_info = ""
        if trade:
            bp = float(trade.get("buy_price") or 0)
            pnl_pct = ((price - bp) / bp * 100) if bp > 0 else 0
            trade_info = f"\n📂 Open positie: €{bp:.4f} → €{price:.4f} ({pnl_pct:+.1f}%)"

        # Check whitelist
        cfg = _load_config()
        wl = cfg.get("WHITELIST_MARKETS", [])
        in_whitelist = "✅" if market in wl else "❌"

        return (
            f"<b>📈 {market}</b>\n"
            f"Prijs: €{price:.4f}\n"
            f"Whitelist: {in_whitelist}"
            + trade_info
        )
    except Exception as e:
        return f"Market info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /today, /week — period summaries
# ──────────────────────────────────────────
def _summarize_period(closed_trades: list, since_ts: float, label: str) -> str:
    period = [t for t in closed_trades if float(t.get("timestamp") or 0) >= since_ts]
    if not period:
        return f"<b>📅 {label}</b>\nNog geen gesloten trades."
    profits = [float(t.get("profit") or 0) for t in period]
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p < 0]
    total = sum(profits)
    winr = len(wins) / len(profits) * 100 if profits else 0.0
    avg_w = sum(wins) / len(wins) if wins else 0.0
    avg_l = sum(losses) / len(losses) if losses else 0.0

    # Top 3 by P&L
    by_market: dict = {}
    for t in period:
        by_market.setdefault(t.get("market", "?"), []).append(float(t.get("profit") or 0))
    top = sorted(by_market.items(), key=lambda kv: sum(kv[1]), reverse=True)[:3]

    s = "+" if total >= 0 else ""
    lines = [
        f"<b>📅 {label}</b>",
        f"Trades: {len(profits)}  |  Win rate: <b>{winr:.0f}%</b>",
        f"P&amp;L: <b>{s}€{total:.2f}</b>",
        f"Gem. winst: +€{avg_w:.2f}  |  Gem. verlies: €{avg_l:.2f}",
    ]
    if top:
        lines.append("\n<b>🏆 Top:</b>")
        for m, profs in top:
            lines.append(f"  {m}: {'+' if sum(profs)>=0 else ''}€{sum(profs):.2f} ({len(profs)}×)")
    return "\n".join(lines)


def _get_today_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        today = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        return _summarize_period(d.get("closed", []), today, "Vandaag")
    except Exception as e:
        return f"Today ophalen mislukt: {e}"


def _get_week_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        wk = time.time() - 7 * 86400
        return _summarize_period(d.get("closed", []), wk, "Laatste 7 dagen")
    except Exception as e:
        return f"Week ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /ai — Model status & metrics
# ──────────────────────────────────────────
def _get_ai_text() -> str:
    try:
        cfg = _load_config()
        ai_on = cfg.get("AI_ENABLED", False)
        sup_on = cfg.get("AI_SUPERVISOR_ENABLED", False)
        lines = [
            "<b>🤖 AI Status</b>",
            f"AI: {'✅' if ai_on else '❌'}  |  Supervisor: {'✅' if sup_on else '❌'}",
        ]
        # Enhanced metrics
        for path, label in [
            (BASE_DIR / "ai" / "ai_model_metrics_enhanced.json", "Enhanced model"),
            (BASE_DIR / "ai" / "ai_model_metrics.json", "Base model"),
        ]:
            if not path.exists():
                continue
            try:
                m = json.loads(path.read_text(encoding="utf-8"))
                trained_at = m.get("trained_at") or m.get("trained_ts") or 0
                age_str = "?"
                if trained_at:
                    age_h = (time.time() - float(trained_at)) / 3600
                    age_str = f"{age_h:.1f}u geleden" if age_h < 48 else f"{age_h/24:.1f}d geleden"
                acc = m.get("test_accuracy") or m.get("accuracy")
                auc = m.get("test_auc") or m.get("auc")
                samples = m.get("samples_total") or m.get("n_samples")
                lines.append(f"\n<b>{label}:</b>")
                lines.append(f"  Getraind: {age_str}")
                if samples:
                    lines.append(f"  Samples: {samples}")
                if acc is not None:
                    lines.append(f"  Accuracy: {float(acc)*100:.1f}%")
                if auc is not None:
                    lines.append(f"  AUC: {float(auc):.3f}")
            except Exception:
                pass
        # Recent suggestions
        sug_path = BASE_DIR / "ai" / "ai_market_suggestions.json"
        if sug_path.exists():
            try:
                doc = json.loads(sug_path.read_text(encoding="utf-8"))
                pending = [s for s in doc.get("suggestions", []) if s.get("status") in (None, "pending")]
                lines.append(f"\n<b>Pending suggestions:</b> {len(pending)}")
                for s in pending[-3:]:
                    lines.append(f"  · {s.get('market','?')}: {s.get('reason','?')[:60]}")
            except Exception:
                pass
        return "\n".join(lines)
    except Exception as e:
        return f"AI info ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /regime — Current market regime
# ──────────────────────────────────────────
def _get_regime_text() -> str:
    try:
        state_path = BASE_DIR / "data" / "bot_state.json"
        if not state_path.exists():
            return "❓ Geen regime data."
        st = json.loads(state_path.read_text(encoding="utf-8"))
        rr = st.get("_REGIME_RESULT", {})
        ra = st.get("_REGIME_ADJ", {})
        scan = st.get("LAST_SCAN_STATS", {})
        regime = rr.get("regime", "?")
        conf = float(rr.get("confidence", 0) or 0)
        emoji = {"trending_up": "📈", "ranging": "↔️", "high_volatility": "⚡", "bearish": "📉"}.get(regime, "❓")
        lines = [
            "<b>🌍 Markt Regime</b>",
            f"{emoji} <b>{regime}</b>  (confidence {conf*100:.1f}%)",
        ]
        if ra:
            lines.append(f"\n<b>Regime adjustments:</b>")
            lines.append(f"  Position size mult: ×{ra.get('base_amount_mult',1):.2f}")
            lines.append(f"  Max-trades mult: ×{ra.get('max_trades_mult',1):.2f}")
            lines.append(f"  Min-score adj: +{ra.get('min_score_adj',0):.1f}")
            lines.append(f"  SL mult: ×{ra.get('sl_mult',1):.2f}")
            lines.append(f"  Grid: {'⏸️ pauze' if ra.get('grid_pause') else '▶️ actief'}")
            lines.append(f"  DCA: {'✅' if ra.get('dca_enabled') else '❌'}")
            desc = ra.get("description")
            if desc:
                lines.append(f"\n<i>{desc}</i>")
        if scan:
            lines.append(
                f"\n<b>Laatste scan:</b> {scan.get('evaluated',0)}/{scan.get('total_markets',0)} markten "
                f"geëvalueerd, {scan.get('passed_min_score',0)} pass min-score "
                f"(drempel {scan.get('min_score_threshold','?')})"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Regime ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /pause /resume — Halt new entries
# ──────────────────────────────────────────
_PAUSE_STATE_FILE = BASE_DIR / "data" / "telegram_pause_state.json"


def _pause_entries() -> str:
    """Tijdelijk geen nieuwe entries: zet MIN_SCORE_TO_BUY = 999.

    Bewaart oude waarde in telegram_pause_state.json zodat /resume het kan herstellen.
    Bestaande open trades blijven gewoon trailing/managed.
    """
    try:
        cfg = _load_config()
        prev = float(cfg.get("MIN_SCORE_TO_BUY", 7.0))
        if prev >= 999:
            return "⏸️ Bot stond al op pauze (MIN_SCORE_TO_BUY ≥ 999)."
        _PAUSE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _PAUSE_STATE_FILE.write_text(json.dumps({"prev_min_score": prev, "ts": time.time()}), encoding="utf-8")
        _save_local_override("MIN_SCORE_TO_BUY", 999.0)
        return (
            f"⏸️ <b>Entries gepauzeerd.</b>\n"
            f"MIN_SCORE_TO_BUY: {prev} → 999\n"
            f"Open trades worden gewoon getrailed/beheerd.\n"
            f"Gebruik <code>/resume</code> om te hervatten."
        )
    except Exception as e:
        return f"❌ Pause mislukt: {e}"


def _resume_entries() -> str:
    try:
        if not _PAUSE_STATE_FILE.exists():
            return "▶️ Geen pauze-staat gevonden — niets te herstellen."
        st = json.loads(_PAUSE_STATE_FILE.read_text(encoding="utf-8"))
        prev = float(st.get("prev_min_score", 7.0))
        prev = max(prev, 7.0)  # respect the 7.0 lock
        _save_local_override("MIN_SCORE_TO_BUY", prev)
        try:
            _PAUSE_STATE_FILE.unlink()
        except Exception:
            pass
        return f"▶️ <b>Entries hervat.</b>\nMIN_SCORE_TO_BUY teruggezet op {prev}."
    except Exception as e:
        return f"❌ Resume mislukt: {e}"


# ──────────────────────────────────────────
# /uptime, /version, /quiet
# ──────────────────────────────────────────
_PROCESS_START_TS = time.time()


def _get_uptime_text() -> str:
    try:
        secs = time.time() - _PROCESS_START_TS
        if secs < 3600:
            up = f"{secs/60:.1f} min"
        elif secs < 86400:
            up = f"{secs/3600:.2f} uur"
        else:
            up = f"{secs/86400:.2f} dagen"
        # Last heartbeat from bot_state
        hb_str = "?"
        try:
            st = json.loads((BASE_DIR / "data" / "bot_state.json").read_text(encoding="utf-8"))
            hb = float(st.get("LAST_HEARTBEAT_TS", 0) or 0)
            if hb:
                age = time.time() - hb
                hb_str = f"{age:.0f}s geleden" if age < 120 else f"{age/60:.1f} min geleden"
        except Exception:
            pass
        return f"<b>⏱ Uptime</b>\nTelegram-handler: {up}\nLaatste bot-heartbeat: {hb_str}"
    except Exception as e:
        return f"Uptime mislukt: {e}"


def _get_version_text() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--pretty=format:%h %s (%ar)"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
        )
        commit = (result.stdout or "").strip() or "(geen git info)"
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(BASE_DIR), capture_output=True, text=True, timeout=5,
        ).stdout.strip() or "?"
        return f"<b>📦 Versie</b>\nBranch: <code>{branch}</code>\nCommit: <code>{commit}</code>"
    except Exception as e:
        return f"Version mislukt: {e}"


def _set_quiet(arg: str) -> str:
    global _quiet_override
    a = (arg or "").strip().lower()
    if a in ("on", "aan", "1", "true", "ja"):
        _quiet_override = True
        return "🔕 Quiet mode <b>aan</b> — alleen trade + critical alerts. Gebruik <code>/quiet off</code> om te stoppen."
    if a in ("off", "uit", "0", "false", "nee"):
        _quiet_override = False
        return "🔔 Quiet mode <b>uit</b> — normale alerts hervat."
    return f"Quiet override: {'aan' if _quiet_override else 'uit'}\nGebruik <code>/quiet on</code> of <code>/quiet off</code>."


# ──────────────────────────────────────────
# /why <market> — Why was this trade opened?
# ──────────────────────────────────────────
def _get_why_text(symbol: str) -> str:
    try:
        market = symbol.upper() if "-" in symbol else f"{symbol.upper()}-EUR"
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        trade = d.get("open", {}).get(market)
        source = "open trade"
        if not trade:
            # try recent closed
            for t in reversed(d.get("closed", [])):
                if t.get("market") == market:
                    trade = t
                    source = "laatste closed trade"
                    break
        if not trade:
            return f"❌ Geen recente trade gevonden voor <b>{market}</b>."

        score = trade.get("score")
        regime = trade.get("opened_regime", "?")
        rsi = trade.get("rsi_at_entry")
        macd = trade.get("macd_at_entry")
        vol = trade.get("volatility_at_entry")
        vol24 = trade.get("volume_24h_eur")
        bp = float(trade.get("buy_price") or 0)
        opened = float(trade.get("opened_ts") or trade.get("timestamp") or 0)
        opened_str = time.strftime("%d-%m %H:%M", time.localtime(opened)) if opened else "?"

        regime_emoji = {
            "trending_up": "📈", "ranging": "↔️", "high_volatility": "⚡",
            "bearish": "📉", "aggressive": "🔥", "defensive": "🛡️",
        }.get(regime, "❓")

        lines = [
            f"<b>💡 Waarom {market}?</b>  <i>({source})</i>",
            f"Geopend: {opened_str} @ €{bp:.6g}",
            "",
        ]
        if score is not None:
            lines.append(f"📊 Score: <b>{float(score):.2f}</b>")
        lines.append(f"{regime_emoji} Regime: {regime}")
        if isinstance(rsi, (int, float)) and rsi:
            rsi_v = float(rsi)
            tag = "📉 oversold" if rsi_v < 30 else ("📈 overbought" if rsi_v > 70 else "neutraal")
            lines.append(f"RSI@entry: {rsi_v:.1f} ({tag})")
        if isinstance(macd, (int, float)):
            lines.append(f"MACD@entry: {float(macd):+.6f}")
        if isinstance(vol, (int, float)) and vol:
            lines.append(f"Volatiliteit: {float(vol)*100:.2f}%")
        if isinstance(vol24, (int, float)) and vol24:
            lines.append(f"24h volume: €{float(vol24):,.0f}")
        return "\n".join(lines)
    except Exception as e:
        return f"Why ophalen mislukt: {e}"


# ──────────────────────────────────────────
# /fees — Total fees paid
# ──────────────────────────────────────────
def _get_fees_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        closed = d.get("closed", [])
        if not closed:
            return "💸 Nog geen fee data."
        today_ts = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
        wk_ts = time.time() - 7 * 86400

        def fees_in(ts_min):
            tot = 0.0
            cnt = 0
            for t in closed:
                if float(t.get("timestamp") or 0) < ts_min:
                    continue
                f = float(t.get("buy_fee") or 0) + float(t.get("sell_fee") or 0)
                if f == 0:
                    # Estimate at 0.25% taker on both sides if not stored
                    inv = float(t.get("invested_eur") or 0)
                    sp = float(t.get("sell_price") or 0)
                    am = float(t.get("amount") or 0)
                    proceeds = sp * am
                    f = (inv + proceeds) * 0.0025
                tot += f
                cnt += 1
            return tot, cnt

        f_today, n_today = fees_in(today_ts)
        f_week, n_week = fees_in(wk_ts)
        f_total = sum(
            (float(t.get("buy_fee") or 0) + float(t.get("sell_fee") or 0))
            or ((float(t.get("invested_eur") or 0) + float(t.get("sell_price") or 0) * float(t.get("amount") or 0)) * 0.0025)
            for t in closed
        )
        return (
            "<b>💸 Fee Overzicht</b>\n"
            f"Vandaag: €{f_today:.2f} ({n_today} trades)\n"
            f"7 dagen: €{f_week:.2f} ({n_week} trades)\n"
            f"Totaal: €{f_total:.2f} ({len(closed)} trades)\n"
            "<i>Geschat op 0.25% per zijde wanneer fee niet expliciet opgeslagen.</i>"
        )
    except Exception as e:
        return f"Fees mislukt: {e}"


# ──────────────────────────────────────────
# /top — Top 5 movers from open positions + whitelist
# ──────────────────────────────────────────
def _get_top_text() -> str:
    try:
        cfg = _load_config()
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        wl = cfg.get("WHITELIST_MARKETS", []) or []
        markets = list(set(list(d.get("open", {}).keys()) + list(wl)))[:25]  # cap API calls
        if not markets:
            return "📈 Geen markten om te checken."

        rows = []
        try:
            r = requests.get("https://api.bitvavo.com/v2/ticker/24h", timeout=8)
            if r.ok:
                data = r.json()
                lookup = {row["market"]: row for row in data if isinstance(row, dict) and "market" in row}
                for m in markets:
                    row = lookup.get(m)
                    if not row:
                        continue
                    try:
                        change = float(row.get("priceChangePercentage", 0))
                        rows.append((m, change, float(row.get("last", 0))))
                    except Exception:
                        pass
        except Exception:
            pass

        if not rows:
            return "📈 Kon 24h data niet ophalen."
        rows.sort(key=lambda x: x[1], reverse=True)
        winners = rows[:5]
        losers = rows[-5:][::-1]
        lines = ["<b>📈 Top 24h movers (open + whitelist)</b>", "", "<b>🟢 Winners:</b>"]
        for m, c, p in winners:
            lines.append(f"  {m}: {c:+.2f}%  (€{p:.4g})")
        lines.append("\n<b>🔴 Losers:</b>")
        for m, c, p in losers:
            lines.append(f"  {m}: {c:+.2f}%  (€{p:.4g})")
        return "\n".join(lines)
    except Exception as e:
        return f"Top mislukt: {e}"


# ──────────────────────────────────────────
# /health — Quick health check
# ──────────────────────────────────────────
def _get_health_text() -> str:
    try:
        cfg = _load_config()
        checks = []
        # 1. Config sane
        max_t = int(cfg.get("MAX_OPEN_TRADES", 0) or 0)
        checks.append(("Config", max_t >= 3, f"MAX_OPEN_TRADES={max_t} (≥3 vereist)"))
        # 2. Heartbeat fresh
        hb_ok = False
        hb_msg = "?"
        try:
            st = json.loads((BASE_DIR / "data" / "bot_state.json").read_text(encoding="utf-8"))
            hb = float(st.get("LAST_HEARTBEAT_TS", 0) or 0)
            if hb:
                age = time.time() - hb
                hb_ok = age < 300
                hb_msg = f"{age:.0f}s geleden"
        except Exception as e:
            hb_msg = str(e)[:40]
        checks.append(("Heartbeat", hb_ok, hb_msg))
        # 3. Trade log readable
        tl_ok = False
        tl_msg = "missing"
        try:
            d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
            tl_ok = True
            tl_msg = f"{len(d.get('open', {}))} open / {len(d.get('closed', []))} closed"
        except Exception as e:
            tl_msg = str(e)[:40]
        checks.append(("Trade log", tl_ok, tl_msg))
        # 4. AI model present (if AI_ENABLED)
        if cfg.get("AI_ENABLED"):
            mp = BASE_DIR / "ai" / "ai_xgb_model_enhanced.json"
            checks.append(("AI model", mp.exists(), str(mp.name) if mp.exists() else "ontbreekt"))
        # 5. Recent errors in log
        err_count = 0
        try:
            if LOG_PATH.exists():
                with open(LOG_PATH, encoding="utf-8", errors="replace") as f:
                    last = f.readlines()[-200:]
                err_count = sum(1 for l in last if "ERROR" in l or "CRITICAL" in l)
        except Exception:
            pass
        checks.append(("Errors laatste 200 log lines", err_count < 20, f"{err_count} fouten"))

        lines = ["<b>🏥 Health Check</b>"]
        for name, ok, msg in checks:
            icon = "✅" if ok else "❌"
            lines.append(f"{icon} {name}: {msg}")
        all_ok = all(ok for _, ok, _ in checks)
        lines.append(f"\n<b>Verdict: {'✅ Gezond' if all_ok else '⚠️ Aandacht nodig'}</b>")
        return "\n".join(lines)
    except Exception as e:
        return f"Health check mislukt: {e}"


# ──────────────────────────────────────────
# /positions — compact one-liner per trade
# ──────────────────────────────────────────
def _get_positions_text() -> str:
    try:
        d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
        opens = d.get("open", {})
        if not opens:
            return "📂 Geen open posities."
        lines = ["<b>📂 Open posities (compact)</b>"]
        total_pnl = 0.0
        for market, t in opens.items():
            bp = float(t.get("buy_price") or 0)
            am = float(t.get("amount") or 0)
            cp = _get_price(market)
            pnl_pct = (cp - bp) / bp * 100 if bp > 0 and cp > 0 else 0
            pnl = (cp - bp) * am if bp > 0 and cp > 0 else 0
            total_pnl += pnl
            icon = "🟢" if pnl_pct >= 0 else "🔴"
            sign = "+" if pnl_pct >= 0 else ""
            lines.append(f"{icon} {market}: {sign}{pnl_pct:.2f}% ({sign}€{pnl:.2f})")
        s = "+" if total_pnl >= 0 else ""
        lines.append(f"\n<b>Totaal P&amp;L: {s}€{total_pnl:.2f}</b>")
        return "\n".join(lines)
    except Exception as e:
        return f"Positions mislukt: {e}"


# ──────────────────────────────────────────
# Command dispatcher
# ──────────────────────────────────────────
def _handle_command(text: str):
    text = text.strip()
    parts = text.split(maxsplit=2)
    cmd = parts[0].lower().split("@")[0]

    if cmd in ("/start", "/help"):
        reply = (
            "🤖 <b>Bitvavo Bot — Commands</b>\n\n"
            "<b>📊 Snel overzicht:</b>\n"
            "/status — Bot status\n"
            "/today — P&amp;L vandaag\n"
            "/week — P&amp;L 7 dagen\n"
            "/positions — Compact open trades\n"
            "/trades — Open posities + live P&amp;L (uitgebreid)\n"
            "/profit — Vandaag / week / totaal\n"
            "/performance — Win rate &amp; statistieken\n"
            "/balance — EUR balance &amp; budget verdeling\n"
            "/fees — Totaal aan fees betaald\n"
            "/risk — Risk management status\n\n"
            "<b>🎯 Strategie &amp; markt:</b>\n"
            "/trailing — Trailing stop details per trade\n"
            "/dca — DCA status per trade\n"
            "/grid — Grid bot dashboard\n"
            "/regime — Huidig marktregime + adjustments\n"
            "/ai — AI model status &amp; metrics\n"
            "/why [coin] — Waarom werd deze trade geopend\n"
            "/top — Top 24h winners/losers\n"
            "/market [coin] — Snelle prijscheck\n"
            "/orders — Open orders (trailing only)\n\n"
            "<b>⚙️ Beheer:</b>\n"
            "/config — Huidige configuratie\n"
            "/set KEY VALUE — Parameter aanpassen\n"
            "/pause — Pauzeer nieuwe entries\n"
            "/resume — Hervat entries\n"
            "/quiet on|off — Mute non-critical alerts\n"
            "/health — Snelle health check\n"
            "/uptime — Telegram + bot heartbeat\n"
            "/version — Git branch + commit\n"
            "/log [n] — Laatste n log regels (max 50)\n"
            "/stop — Bot stoppen\n"
            "/restart — Bot herstarten\n"
            "/update — git pull + herstart\n\n"
            "<b>Tuning voor minder ruis:</b>\n"
            "  <code>/set TELEGRAM_NOTIFY_LEVEL trades</code>  (alleen trade+critical)\n"
            "  <code>/set TELEGRAM_QUIET_START 22:00</code>\n"
            "  <code>/set TELEGRAM_QUIET_END 07:00</code>\n"
            "  <code>/set ALERT_DEDUPE_SECONDS 1800</code>\n\n"
            "<b>Voorbeelden:</b>\n"
            "  <code>/why BTC</code>  ·  <code>/market SOL</code>\n"
            "  <code>/set BASE_AMOUNT_EUR 15</code>\n"
            "  <code>/set BUDGET_RESERVATION.trailing_pct 80</code>"
        )
    elif cmd == "/status":
        reply = _get_status_text()
    elif cmd == "/trades":
        reply = _get_trades_text()
    elif cmd == "/positions":
        reply = _get_positions_text()
    elif cmd == "/today":
        reply = _get_today_text()
    elif cmd == "/week":
        reply = _get_week_text()
    elif cmd == "/orders":
        reply = _get_orders_text()
    elif cmd == "/profit":
        reply = _get_profit_text()
    elif cmd == "/performance":
        reply = _get_performance_text()
    elif cmd == "/balance":
        reply = _get_balance_text()
    elif cmd == "/fees":
        reply = _get_fees_text()
    elif cmd == "/trailing":
        reply = _get_trailing_text()
    elif cmd == "/dca":
        reply = _get_dca_text()
    elif cmd == "/grid":
        reply = _get_grid_text()
    elif cmd == "/regime":
        reply = _get_regime_text()
    elif cmd == "/ai":
        reply = _get_ai_text()
    elif cmd == "/config":
        reply = _get_config_text()
    elif cmd == "/risk":
        reply = _get_risk_text()
    elif cmd == "/health":
        reply = _get_health_text()
    elif cmd == "/uptime":
        reply = _get_uptime_text()
    elif cmd == "/version":
        reply = _get_version_text()
    elif cmd == "/top":
        reply = _get_top_text()
    elif cmd == "/why":
        if len(parts) >= 2:
            reply = _get_why_text(parts[1])
        else:
            reply = "❌ Gebruik: <code>/why BTC</code>"
    elif cmd == "/quiet":
        reply = _set_quiet(parts[1] if len(parts) >= 2 else "")
    elif cmd == "/pause":
        reply = _pause_entries()
    elif cmd == "/resume":
        reply = _resume_entries()
    elif cmd == "/market":
        if len(parts) >= 2:
            reply = _get_market_text(parts[1])
        else:
            reply = "❌ Gebruik: <code>/market BTC</code>"
    elif cmd == "/log":
        n = 20
        if len(parts) >= 2:
            try:
                n = min(int(parts[1]), 50)
            except ValueError:
                pass
        reply = _get_log_text(n)
    elif cmd == "/stop":
        reply = _stop_bot()
    elif cmd == "/restart":
        send_message("🔄 <b>Bot wordt herstart...</b>\nNa ~10 seconden is hij weer actief.")
        _restart_bot()
        return
    elif cmd == "/update":
        send_message("⬇️ <b>Update ophalen via git pull…</b>")
        _git_pull_and_restart()
        return
    elif cmd == "/set":
        if len(parts) < 3:
            reply = "❌ Gebruik: <code>/set KEY VALUE</code>\nbijv: <code>/set SLEEP_SECONDS 30</code>"
        else:
            reply = _apply_set_command(parts[1], parts[2])
    else:
        reply = f"❓ Onbekend: <code>{cmd}</code> — Stuur /help"

    send_message(reply)


# ──────────────────────────────────────────
# Trade watcher (auto-alerts bij buy/sell)
# ──────────────────────────────────────────
def _trade_watch_loop():
    global _known_open, _known_closed_count, _watch_initialized

    while True:
        try:
            if TRADE_LOG_PATH.exists():
                d = json.loads(TRADE_LOG_PATH.read_text(encoding="utf-8"))
                open_trades = d.get("open", {})
                closed_trades = d.get("closed", [])
                current_open = set(open_trades.keys())
                current_closed_count = len(closed_trades)

                if not _watch_initialized:
                    _known_open = current_open
                    _known_closed_count = current_closed_count
                    _watch_initialized = True
                else:
                    # Nieuwe opens → koopmelding (sla dust-posities over)
                    for market in current_open - _known_open:
                        trade = open_trades.get(market, {})
                        buy_price = float(trade.get("buy_price") or 0)
                        invested = float(trade.get("invested_eur") or trade.get("initial_invested_eur") or 0)
                        if invested < 1.0:  # dust / stofpositie, geen echte koop
                            continue
                        score = float(trade.get("score") or 0)
                        regime = str(trade.get("opened_regime") or "?")
                        rsi_e = trade.get("rsi_at_entry")
                        macd_e = trade.get("macd_at_entry")
                        amount = float(trade.get("amount") or 0)
                        regime_emoji = {
                            "trending_up": "📈", "ranging": "↔️",
                            "high_volatility": "⚡", "bearish": "📉",
                            "aggressive": "🔥", "defensive": "🛡️",
                        }.get(regime, "❓")
                        extras = []
                        if score:
                            extras.append(f"Score: <b>{score:.1f}</b>")
                        extras.append(f"{regime_emoji} {regime}")
                        if isinstance(rsi_e, (int, float)) and rsi_e:
                            extras.append(f"RSI: {float(rsi_e):.0f}")
                        if isinstance(macd_e, (int, float)):
                            extras.append(f"MACD: {float(macd_e):+.4f}")
                        send_message(
                            f"🟢 <b>KOOP: {market}</b>\n"
                            f"Prijs: €{buy_price:.6g} | Bedrag: {amount:.4g}\n"
                            f"Geïnvesteerd: <b>€{invested:.2f}</b>\n"
                            + " · ".join(extras)
                        )

                    # Nieuwe closes → verkoopmelding (verrijkt)
                    if current_closed_count > _known_closed_count:
                        for trade in closed_trades[_known_closed_count:]:
                            market = trade.get("market", "?")
                            profit = float(trade.get("profit") or 0)
                            profit_pct = float(trade.get("profit_pct") or 0)
                            reason = str(trade.get("reason", "?"))
                            buy_price = float(trade.get("buy_price") or 0)
                            sell_price = float(trade.get("sell_price") or 0)
                            highest_price = float(trade.get("highest_price") or 0)
                            invested = float(trade.get("invested_eur") or trade.get("initial_invested_eur") or 0)
                            opened_ts = float(trade.get("opened_ts") or trade.get("timestamp_open") or 0)
                            closed_ts = float(trade.get("timestamp") or 0)
                            dca = int(trade.get("dca_buys") or 0)
                            ptp = float(trade.get("partial_tp_returned_eur") or 0)
                            sign = "+" if profit >= 0 else ""

                            # Hold time
                            hold_str = ""
                            if opened_ts > 0 and closed_ts > opened_ts:
                                secs = closed_ts - opened_ts
                                if secs < 3600:
                                    hold_str = f"⏱ {secs/60:.0f}m"
                                elif secs < 86400:
                                    hold_str = f"⏱ {secs/3600:.1f}u"
                                else:
                                    hold_str = f"⏱ {secs/86400:.1f}d"

                            # Peak vs realised
                            peak_str = ""
                            if highest_price > 0 and buy_price > 0:
                                peak_pct = (highest_price - buy_price) / buy_price * 100
                                gap = peak_pct - profit_pct
                                peak_str = f"📈 Peak: {peak_pct:+.2f}% (gaf {gap:.2f}% terug)"

                            reason_label = {
                                "trailing_stop": "🎯 Trailing stop",
                                "trailing_tp": "🎯 Trailing TP",
                                "stop_loss": "🛑 Stop-loss",
                                "hard_sl": "🛑 Hard stop-loss",
                                "saldo_error": "❗ Saldo error",
                                "sync_removed": "❗ Sync removed",
                                "manual": "👤 Handmatig",
                            }.get(reason, f"📋 {reason}")

                            emoji = "✅" if profit > 0 else ("⚠️" if profit == 0 else "🔴")
                            extras = [f"Reden: {reason_label}"]
                            if hold_str:
                                extras.append(hold_str)
                            if dca:
                                extras.append(f"DCA: {dca}×")
                            if ptp > 0:
                                extras.append(f"Partial TP: €{ptp:.2f}")

                            msg_lines = [
                                f"{emoji} <b>VERKOOP: {market}</b>",
                                f"€{buy_price:.6g} → €{sell_price:.6g}  ({sign}{profit_pct:.2f}%)",
                                f"💰 P&amp;L: <b>{sign}€{profit:.2f}</b>"
                                + (f"  /  €{invested:.2f} ingelegd" if invested > 0 else ""),
                            ]
                            if peak_str:
                                msg_lines.append(peak_str)
                            msg_lines.append(" · ".join(extras))
                            send_message("\n".join(msg_lines))

                    _known_open = current_open
                    _known_closed_count = current_closed_count

        except Exception as e:
            logger.debug(f"[Telegram] Trade watcher fout: {e}")

        time.sleep(15)


# ──────────────────────────────────────────
# Polling loop
# ──────────────────────────────────────────
def _poll_loop():
    global _last_update_id, _chat_id
    url = f"https://api.telegram.org/bot{_token}/getUpdates"

    # Herstel opgeslagen offset (voorkomt herverwerking van /restart)
    saved = _load_offset()
    if saved > _last_update_id:
        _last_update_id = saved
        logger.info(f"[Telegram] Offset hersteld uit bestand: {saved}")

    logger.info("[Telegram] Polling gestart.")

    while True:
        try:
            resp = requests.get(url, params={
                "offset": _last_update_id + 1,
                "timeout": 30,
                "allowed_updates": ["message"],
            }, timeout=40)

            if not resp.ok:
                time.sleep(5)
                continue

            for update in resp.json().get("result", []):
                _last_update_id = update["update_id"]
                _save_offset()  # Persist zodat herstart niet herverwerkt
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                incoming_chat_id = str(chat.get("id", ""))
                text = msg.get("text", "")

                if not text:
                    continue

                if not _chat_id and incoming_chat_id:
                    _save_chat_id(incoming_chat_id)
                    send_message(
                        f"✅ <b>Verbinding geslaagd!</b>\n"
                        f"Chat ID <code>{incoming_chat_id}</code> opgeslagen.\n"
                        f"Stuur /help voor alle commands."
                    )
                    continue

                if incoming_chat_id != _chat_id:
                    logger.warning(f"[Telegram] Bericht onbekende chat: {incoming_chat_id}")
                    continue

                if text.startswith("/"):
                    _handle_command(text)

        except requests.exceptions.Timeout:
            pass
        except Exception as e:
            logger.error(f"[Telegram] Poll fout: {e}")
            time.sleep(10)


# ──────────────────────────────────────────
# Init
# ──────────────────────────────────────────
def init(config: dict = None):
    global _poll_thread, _watch_thread, _init_done
    if _init_done:
        return
    _init_done = True

    _reload_credentials()

    if not _token:
        logger.warning("[Telegram] Geen token geconfigureerd.")
        return

    logger.info("[Telegram] Handler geïnitialiseerd.")

    _poll_thread = threading.Thread(target=_poll_loop, daemon=True, name="TelegramPoller")
    _poll_thread.start()

    _watch_thread = threading.Thread(target=_trade_watch_loop, daemon=True, name="TelegramTradeWatcher")
    _watch_thread.start()

    # Geen opstartmelding sturen
