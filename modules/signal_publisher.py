"""Signal Publisher — Betaald Telegram signaalkanaal voor trading signalen.

Publiceert geformatteerde trade-signalen (BUY, SELL, DCA, Partial TP, Regime)
naar een apart Telegram kanaal. Dit kanaal is bedoeld voor betalende abonnees
en bevat ALLEEN signalen, geen persoonlijke bot-data.

Signalen worden verstuurd met vertraging (configurable) om front-running te voorkomen.

Gebruik:
    from modules.signal_publisher import publish_buy, publish_sell, publish_dca, ...
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config" / "bot_config.json"

# Module state
_token: str = ""
_channel_id: str = ""
_enabled: bool = False
_delay_seconds: int = 0
_include_price: bool = True
_include_score: bool = False
_include_regime: bool = True
_affiliate_link: str = ""
_init_done: bool = False
_lock = threading.Lock()

# Rate limiting: max 20 msgs/min to Telegram
_msg_timestamps: list = []
_RATE_LIMIT = 20
_RATE_WINDOW = 60


def init(config: Optional[Dict[str, Any]] = None) -> None:
    """Initialiseer signal publisher met config."""
    global _token, _channel_id, _enabled, _delay_seconds, _init_done
    global _include_price, _include_score, _include_regime, _affiliate_link

    if config is None:
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                config = json.load(f)
        except Exception:
            config = {}

    sp_cfg = config.get("SIGNAL_PUBLISHER", {})
    _enabled = bool(sp_cfg.get("enabled", False))
    _token = str(sp_cfg.get("bot_token") or config.get("TELEGRAM_BOT_TOKEN", "")).strip()
    _channel_id = str(sp_cfg.get("channel_id", "")).strip()
    _delay_seconds = int(sp_cfg.get("delay_seconds", 0))
    _include_price = bool(sp_cfg.get("include_price", True))
    _include_score = bool(sp_cfg.get("include_score", False))
    _include_regime = bool(sp_cfg.get("include_regime", True))
    _affiliate_link = str(sp_cfg.get("affiliate_link", "")).strip()
    _init_done = True

    if _enabled and _channel_id:
        logger.info(f"[SignalPublisher] Geactiveerd — kanaal: {_channel_id}, delay: {_delay_seconds}s")
    elif _enabled:
        logger.warning("[SignalPublisher] Enabled maar channel_id ontbreekt — signalen worden NIET verstuurd")


def _rate_limited() -> bool:
    """Check if we're hitting Telegram rate limits."""
    now = time.time()
    _msg_timestamps[:] = [ts for ts in _msg_timestamps if now - ts < _RATE_WINDOW]
    return len(_msg_timestamps) >= _RATE_LIMIT


def _send(text: str) -> bool:
    """Stuur bericht naar het signaalkanaal."""
    if not _enabled or not _token or not _channel_id:
        return False

    if _rate_limited():
        logger.warning("[SignalPublisher] Rate limit bereikt, signaal overgeslagen")
        return False

    try:
        url = f"https://api.telegram.org/bot{_token}/sendMessage"
        resp = requests.post(
            url,
            json={
                "chat_id": _channel_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        _msg_timestamps.append(time.time())
        if not resp.ok:
            logger.warning(f"[SignalPublisher] Telegram error: {resp.text[:200]}")
        return resp.ok
    except Exception as e:
        logger.error(f"[SignalPublisher] Send failed: {e}")
        return False


def _send_delayed(text: str) -> None:
    """Stuur signaal met optionele vertraging (in achtergrondthread)."""
    if _delay_seconds > 0:

        def _delayed():
            time.sleep(_delay_seconds)
            _send(text)

        thread = threading.Thread(target=_delayed, daemon=True)
        thread.start()
    else:
        _send(text)


def _footer() -> str:
    """Footer met optionele affiliate link."""
    parts = []
    if _affiliate_link:
        parts.append(f'\n\n<a href="{_affiliate_link}">Start met traden op Bitvavo</a>')
    return "".join(parts)


# ── Publieke signaal functies ─────────────────────────────────────


def publish_buy(
    market: str,
    entry_price: float,
    amount_eur: float,
    score: Optional[float] = None,
    regime: Optional[str] = None,
    reason: str = "",
) -> None:
    """Publiceer een BUY signaal."""
    if not _enabled:
        return
    if not _init_done:
        init()

    coin = market.replace("-EUR", "")
    lines = [f"🟢 <b>BUY SIGNAL: {coin}</b>"]

    if _include_price:
        lines.append(f"📍 Entry: €{entry_price:.4f}")
        lines.append(f"💰 Positie: €{amount_eur:.2f}")

    if _include_score and score is not None:
        lines.append(f"📊 Score: {score:.1f}")

    if _include_regime and regime:
        regime_emoji = {
            "trending_up": "📈",
            "ranging": "↔️",
            "high_volatility": "⚡",
            "bearish": "📉",
        }.get(regime, "❓")
        lines.append(f"{regime_emoji} Regime: {regime.replace('_', ' ').title()}")

    if reason:
        lines.append(f"💡 {reason}")

    lines.append(f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}")
    lines.append(_footer())

    _send_delayed("\n".join(lines))


def publish_sell(
    market: str,
    entry_price: float,
    exit_price: float,
    profit_eur: float,
    profit_pct: float,
    reason: str = "trailing_stop",
    hold_time_hours: Optional[float] = None,
    dca_count: int = 0,
) -> None:
    """Publiceer een SELL signaal (trade gesloten)."""
    if not _enabled:
        return
    if not _init_done:
        init()

    coin = market.replace("-EUR", "")
    emoji = "✅" if profit_eur > 0 else "🔴"
    sign = "+" if profit_eur >= 0 else ""

    lines = [f"{emoji} <b>SELL SIGNAL: {coin}</b>"]

    if _include_price:
        lines.append(f"📍 Entry: €{entry_price:.4f} → Exit: €{exit_price:.4f}")

    lines.append(f"💰 Resultaat: {sign}€{profit_eur:.2f} ({sign}{profit_pct:.1f}%)")

    reason_labels = {
        "trailing_stop": "🎯 Trailing Stop",
        "trailing_tp": "🎯 Trailing TP",
        "stop_loss": "🛑 Stop Loss",
        "hard_sl": "🛑 Hard Stop Loss",
        "risk_stop": "🛑 Risk Stop",
        "manual": "👤 Handmatig",
        "timeout": "⏰ Timeout",
    }
    reason_label = reason_labels.get(reason, f"📋 {reason}")
    lines.append(f"📋 Reden: {reason_label}")

    if hold_time_hours is not None:
        if hold_time_hours < 1:
            lines.append(f"⏱ Duur: {hold_time_hours * 60:.0f} min")
        elif hold_time_hours < 24:
            lines.append(f"⏱ Duur: {hold_time_hours:.1f} uur")
        else:
            lines.append(f"⏱ Duur: {hold_time_hours / 24:.1f} dagen")

    if dca_count > 0:
        lines.append(f"📥 DCA buys: {dca_count}x")

    lines.append(f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}")
    lines.append(_footer())

    _send_delayed("\n".join(lines))


def publish_dca(
    market: str,
    dca_number: int,
    price: float,
    amount_eur: float,
    new_avg_price: float,
    drop_pct: float,
) -> None:
    """Publiceer een DCA signaal."""
    if not _enabled:
        return
    if not _init_done:
        init()

    coin = market.replace("-EUR", "")
    lines = [f"📥 <b>DCA #{dca_number}: {coin}</b>"]

    if _include_price:
        lines.append(f"📍 Prijs: €{price:.4f}")
        lines.append(f"💰 Extra: €{amount_eur:.2f}")
        lines.append(f"📊 Nieuwe gem. prijs: €{new_avg_price:.4f}")

    lines.append(f"📉 Drop: {drop_pct:.1f}%")
    lines.append(f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}")
    lines.append(_footer())

    _send_delayed("\n".join(lines))


def publish_partial_tp(
    market: str,
    level: int,
    sell_pct: float,
    price: float,
    profit_eur: float,
) -> None:
    """Publiceer een Partial Take Profit signaal."""
    if not _enabled:
        return
    if not _init_done:
        init()

    coin = market.replace("-EUR", "")
    lines = [
        f"💰 <b>PARTIAL TP L{level}: {coin}</b>",
        f"📍 Prijs: €{price:.4f}",
        f"📤 Verkocht: {sell_pct * 100:.0f}%",
        f"✅ Winst: +€{profit_eur:.2f}",
        f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}",
        _footer(),
    ]

    _send_delayed("\n".join(lines))


def publish_regime_change(
    old_regime: str,
    new_regime: str,
    confidence: float,
) -> None:
    """Publiceer een regime-wijziging."""
    if not _enabled or not _include_regime:
        return
    if not _init_done:
        init()

    regime_emoji = {
        "trending_up": "📈",
        "ranging": "↔️",
        "high_volatility": "⚡",
        "bearish": "📉",
    }
    old_e = regime_emoji.get(old_regime, "❓")
    new_e = regime_emoji.get(new_regime, "❓")

    lines = [
        "🔄 <b>REGIME WIJZIGING</b>",
        f"{old_e} {old_regime.replace('_', ' ').title()} → {new_e} {new_regime.replace('_', ' ').title()}",
        f"📊 Confidence: {confidence:.0%}",
    ]

    # Actiepunten per regime
    advice = {
        "trending_up": "💡 Overweeg long trades — markt in uptrend",
        "ranging": "💡 Voorzichtig — zijwaartse markt, kleinere posities",
        "high_volatility": "⚠️ Hoge volatiliteit — reduceer exposure",
        "bearish": "🛑 Bearish — vermijd nieuwe posities",
    }
    if new_regime in advice:
        lines.append(advice[new_regime])

    lines.append(f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}")
    lines.append(_footer())

    _send_delayed("\n".join(lines))


def publish_daily_summary(
    total_trades: int,
    wins: int,
    losses: int,
    total_profit_eur: float,
    best_trade: Optional[str] = None,
    worst_trade: Optional[str] = None,
    regime: Optional[str] = None,
) -> None:
    """Publiceer dagelijks performance overzicht."""
    if not _enabled:
        return
    if not _init_done:
        init()

    sign = "+" if total_profit_eur >= 0 else ""
    emoji = "✅" if total_profit_eur > 0 else ("⚠️" if total_profit_eur == 0 else "🔴")
    wr = f"{wins / total_trades * 100:.0f}%" if total_trades > 0 else "N/A"

    lines = [
        "📊 <b>DAGELIJKS OVERZICHT</b>",
        "",
        f"{emoji} Resultaat: {sign}€{total_profit_eur:.2f}",
        f"📈 Trades: {total_trades} (W: {wins} / L: {losses})",
        f"🎯 Win ratio: {wr}",
    ]

    if best_trade:
        lines.append(f"🏆 Beste: {best_trade}")
    if worst_trade:
        lines.append(f"💀 Slechtste: {worst_trade}")
    if regime and _include_regime:
        regime_emoji = {"trending_up": "📈", "ranging": "↔️", "high_volatility": "⚡", "bearish": "📉"}
        lines.append(f"{regime_emoji.get(regime, '❓')} Regime: {regime.replace('_', ' ').title()}")

    lines.append(f"\n⏰ {time.strftime('%d-%m-%Y %H:%M')}")
    lines.append(_footer())

    _send_delayed("\n".join(lines))


def test_signal() -> bool:
    """Stuur een test signaal om te verifiëren dat alles werkt."""
    if not _init_done:
        init()

    return _send(
        "🧪 <b>TEST SIGNAAL</b>\n\n"
        "Signal Publisher is succesvol geconfigureerd!\n"
        "Je ontvangt hier voortaan BUY/SELL/DCA signalen.\n\n"
        f"⏰ {time.strftime('%d-%m-%Y %H:%M')}"
        f"{_footer()}"
    )
