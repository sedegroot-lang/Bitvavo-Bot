"""
Telegram Handler voor Bitvavo Bot
- Notificaties via Bot API
- Polling voor commands (geen extra library nodig)
- Auto-alerts: buy, sell, stop-loss, errors
- Commands: /start /help /status /log /trades /profit /stop /restart /update /set
            /trailing /dca /grid /balance /config /orders /performance
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
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[Telegram] Config laden mislukt: {e}")
        return {}


def _save_config(cfg: dict) -> None:
    try:
        from modules.config import save_config as _real_save
        _real_save(cfg)
    except Exception as e:
        logger.warning(f"[Telegram] Fallback to direct write: {e}")
        import tempfile
        tmp = str(CONFIG_PATH) + '.tmp'
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        os.replace(tmp, str(CONFIG_PATH))


def _reload_credentials() -> None:
    global _token, _chat_id
    cfg = _load_config()
    _token = cfg.get("TELEGRAM_BOT_TOKEN", "").strip()
    _chat_id = str(cfg.get("TELEGRAM_CHAT_ID", "")).strip()


def _save_chat_id(chat_id: str) -> None:
    global _chat_id
    cfg = _load_config()
    cfg["TELEGRAM_CHAT_ID"] = chat_id
    _save_config(cfg)
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
_ALERT_KEYWORDS = (
    "ERROR", "CRITICAL", "STALE", "DRAWDOWN", "CIRCUIT",
    "sync_removed", "API glitch", "stale buy_price", "RISK",
    "portfolio drawdown", "daily loss", "WATCHDOG", "OOM",
    "\u26a0\ufe0f", "\ud83d\udd34", "\u2757",  # warning/red emoji
)

def notify(text: str) -> None:
    """Forward trade events AND error/risk alerts to Telegram."""
    _text_lower = text.lower()
    if any(kw.lower() in _text_lower for kw in _TRADE_KEYWORDS):
        send_message(text)
    elif any(kw.lower() in _text_lower for kw in _ALERT_KEYWORDS):
        send_message(f"\u26a0\ufe0f ALERT:\n{text}")


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
            + "\n".join(f"<code>{l[-120:]}</code>" for l in lines)
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
}


def _apply_set_command(key: str, value: str) -> str:
    key_upper = key.upper()
    if key_upper not in ALLOWED_KEYS:
        return (
            f"❌ Onbekende parameter: <code>{key}</code>\n\n"
            "Toegestane parameters:\n"
            + "\n".join(f"• <code>{k}</code>" for k in sorted(ALLOWED_KEYS))
        )
    try:
        typ = ALLOWED_KEYS[key_upper]
        parsed = value.lower() in ("true", "1", "yes", "ja", "aan", "on") if typ == bool else typ(value)
        cfg = _load_config()
        if "." in key_upper:
            parent, child = key_upper.split(".", 1)
            cfg.setdefault(parent, {})[child] = parsed
        else:
            cfg[key_upper] = parsed
        _save_config(cfg)
        return f"✅ <code>{key_upper}</code> = <code>{parsed}</code>\n⚠️ Herstart bot voor sommige parameters."
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
# Command dispatcher
# ──────────────────────────────────────────
def _handle_command(text: str):
    text = text.strip()
    parts = text.split(maxsplit=2)
    cmd = parts[0].lower().split("@")[0]

    if cmd in ("/start", "/help"):
        reply = (
            "🤖 <b>Bitvavo Bot — Commands</b>\n\n"
            "<b>📊 Informatie:</b>\n"
            "/status — Bot status overzicht\n"
            "/trades — Open posities + live P&amp;L\n"
            "/orders — Open orders (trailing only)\n"
            "/profit — Winst vandaag / week / totaal\n"
            "/performance — Win rate &amp; statistieken\n"
            "/balance — EUR balance &amp; budget\n"
            "/risk — Risk management status\n"
            "/market [coin] — Prijs check (bv. /market BTC)\n\n"
            "<b>🎯 Strategieën:</b>\n"
            "/trailing — Trailing stop details\n"
            "/dca — DCA status per trade\n"
            "/grid — Grid bot dashboard\n"
            "/config — Huidige configuratie\n\n"
            "<b>⚙️ Beheer:</b>\n"
            "/set KEY VALUE — Parameter aanpassen\n"
            "/log [n] — Laatste n log regels (max 50)\n"
            "/stop — Bot stoppen\n"
            "/restart — Bot herstarten\n"
            "/update — git pull + herstart\n\n"
            "<b>Voorbeelden:</b>\n"
            "  <code>/set BASE_AMOUNT_EUR 15</code>\n"
            "  <code>/set DCA_ENABLED true</code>\n"
            "  <code>/set HARD_SL_ALT_PCT 0.05</code>\n"
            "  <code>/market SOL</code>"
        )
    elif cmd == "/status":
        reply = _get_status_text()
    elif cmd == "/trades":
        reply = _get_trades_text()
    elif cmd == "/orders":
        reply = _get_orders_text()
    elif cmd == "/profit":
        reply = _get_profit_text()
    elif cmd == "/performance":
        reply = _get_performance_text()
    elif cmd == "/balance":
        reply = _get_balance_text()
    elif cmd == "/trailing":
        reply = _get_trailing_text()
    elif cmd == "/dca":
        reply = _get_dca_text()
    elif cmd == "/grid":
        reply = _get_grid_text()
    elif cmd == "/config":
        reply = _get_config_text()
    elif cmd == "/risk":
        reply = _get_risk_text()
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
                        invested = float(trade.get("invested_eur") or 0)
                        if invested < 1.0:  # dust / stofpositie, geen echte koop
                            continue
                        send_message(
                            f"🟢 <b>KOOP: {market}</b>\n"
                            f"Prijs: €{buy_price:.4f}\n"
                            f"Geïnvesteerd: €{invested:.2f}"
                        )

                    # Nieuwe closes → verkoopmelding
                    if current_closed_count > _known_closed_count:
                        for trade in closed_trades[_known_closed_count:]:
                            market = trade.get("market", "?")
                            profit = float(trade.get("profit") or 0)
                            reason = trade.get("reason", "?")
                            buy_price = float(trade.get("buy_price") or 0)
                            sell_price = float(trade.get("sell_price") or 0)
                            sign = "+" if profit >= 0 else ""
                            emoji = "✅" if profit > 0 else ("⚠️" if profit == 0 else "🔴")
                            sl_tag = " 🛑 STOP-LOSS" if any(x in reason.lower() for x in ("stop", "sl", "hard")) else ""
                            send_message(
                                f"{emoji} <b>VERKOOP: {market}</b>{sl_tag}\n"
                                f"Gekocht: €{buy_price:.4f} → Verkocht: €{sell_price:.4f}\n"
                                f"Winst: {sign}€{profit:.2f} | Reden: {reason}"
                            )

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
