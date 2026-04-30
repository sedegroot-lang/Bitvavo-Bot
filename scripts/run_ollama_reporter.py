"""Ollama-driven Telegram reporter (analyzer mode, never a decider).

Runs forever and sends a Dutch executive summary to Telegram on a schedule
(default 08:00, 14:00, 20:00 local time). Pure read-only: analyses
trade_log + archive + heartbeat + shadow log, asks the local Ollama model
to write a short Dutch report, pushes it via notifier.send_telegram.

Launch:
    .\\.venv\\Scripts\\python.exe scripts/run_ollama_reporter.py

Stop with Ctrl+C.

Config (in %LOCALAPPDATA%\\BotConfig\\bot_config_local.json):
    OLLAMA_REPORTER_HOURS: list[int] = [8, 14, 20]
    OLLAMA_REPORTER_MODEL: str       = "llama3.2:3b"
    OLLAMA_REPORTER_TIMEOUT: float   = 60.0
    OLLAMA_REPORTER_ENABLED: bool    = true
    OLLAMA_REPORTER_FORCE_ONCE: bool = false   # send one immediately on start (debug)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from modules.config import load_config  # noqa: E402
from notifier import send_telegram  # noqa: E402

OLLAMA_URL = "http://localhost:11434/api/generate"
LAST_RUN_PATH = PROJECT_ROOT / "data" / "last_ollama_report.json"


def _load_json(path: Path, default):
    try:
        if path.exists():
            with path.open("r", encoding="utf-8-sig") as f:
                return json.load(f)
    except Exception:
        pass
    return default


def _safe_ts(t: Dict[str, Any]) -> float:
    """Robust timestamp parse — handles float, int, ISO strings, '2026-04-10 20:12:20'."""
    for key in ("opened_ts", "timestamp", "closed_ts"):
        v = t.get(key)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except ValueError:
                pass
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    return datetime.strptime(v[:19], fmt).timestamp()
                except Exception:
                    continue
    return 0.0


def _gather_24h_stats() -> Dict[str, Any]:
    cutoff = time.time() - 24 * 3600
    closed: List[Dict[str, Any]] = []

    tl = _load_json(PROJECT_ROOT / "data" / "trade_log.json", {})
    open_trades = tl.get("open", {}) if isinstance(tl, dict) else {}
    for t in (tl.get("closed") or []) if isinstance(tl, dict) else []:
        if isinstance(t, dict) and _safe_ts(t) >= cutoff:
            closed.append(t)

    arc = _load_json(PROJECT_ROOT / "data" / "trade_archive.json", {})
    arc_list = arc.get("trades", []) if isinstance(arc, dict) else (arc if isinstance(arc, list) else [])
    for t in arc_list:
        if isinstance(t, dict) and _safe_ts(t) >= cutoff:
            closed.append(t)

    profits = [float(t.get("profit") or 0) for t in closed]
    wins = sum(1 for p in profits if p > 0)
    losses = sum(1 for p in profits if p <= 0)
    by_reason: Dict[str, int] = {}
    for t in closed:
        r = str(t.get("reason") or "unknown")
        by_reason[r] = by_reason.get(r, 0) + 1

    biggest_win = max(closed, key=lambda x: float(x.get("profit") or 0), default=None)
    biggest_loss = min(closed, key=lambda x: float(x.get("profit") or 0), default=None)

    hb = _load_json(PROJECT_ROOT / "data" / "heartbeat.json", {})
    hb_age_min = (time.time() - float(hb.get("ts") or 0)) / 60.0 if hb.get("ts") else None

    open_summary = []
    for m, t in (open_trades or {}).items():
        if not isinstance(t, dict):
            continue
        open_summary.append({
            "market": m,
            "invested_eur": round(float(t.get("invested_eur") or 0), 2),
            "buy_price": float(t.get("buy_price") or 0),
            "highest_price": float(t.get("highest_price") or 0),
            "trailing_activated": bool(t.get("trailing_activated")),
            "dca_buys": int(t.get("dca_buys") or 0),
            "opened_regime": str(t.get("opened_regime") or "unknown"),
        })

    # shadow stats
    shadow_path = PROJECT_ROOT / "data" / "shadow_rotation.jsonl"
    shadow_count = 0
    shadow_outcomes_winrate = None
    if shadow_path.exists():
        try:
            rows = []
            with shadow_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            rows.append(json.loads(line))
                        except Exception:
                            continue
            shadow_count = sum(1 for r in rows if float(r.get("ts") or 0) >= cutoff)
            outs = [r for r in rows if isinstance(r.get("outcome_pct"), (int, float))]
            if outs:
                wins_o = sum(1 for r in outs if float(r["outcome_pct"]) > 0)
                shadow_outcomes_winrate = round(wins_o / len(outs), 3)
        except Exception:
            pass

    return {
        "window_hours": 24,
        "closed_count": len(closed),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(closed) * 100, 1) if closed else 0.0,
        "total_pnl_eur": round(sum(profits), 2),
        "avg_pnl_eur": round(sum(profits) / len(profits), 2) if profits else 0.0,
        "exit_reasons": by_reason,
        "biggest_win": {
            "market": biggest_win.get("market") if biggest_win else None,
            "profit_eur": round(float(biggest_win.get("profit") or 0), 2) if biggest_win else 0,
        },
        "biggest_loss": {
            "market": biggest_loss.get("market") if biggest_loss else None,
            "profit_eur": round(float(biggest_loss.get("profit") or 0), 2) if biggest_loss else 0,
        },
        "open_trades": open_summary,
        "open_count": len(open_summary),
        "regime": (hb.get("regime") or {}).get("name") if isinstance(hb.get("regime"), dict) else hb.get("regime"),
        "min_score_threshold": (hb.get("scan_stats") or {}).get("min_score_threshold"),
        "heartbeat_age_min": round(hb_age_min, 1) if hb_age_min is not None else None,
        "shadow_evals_24h": shadow_count,
        "shadow_outcomes_winrate": shadow_outcomes_winrate,
    }


def _ask_ollama(stats: Dict[str, Any], model: str, timeout: float) -> str:
    prompt = (
        "Je bent een crypto-trading analist. Schrijf een KORTE Nederlandse "
        "telegram-update (max 12 regels, gebruik regels en bullets, geen tabellen).\n"
        "Doel: de eigenaar in 30 seconden bijpraten over de afgelopen 24 uur en "
        "1 concrete observatie geven. Geen disclaimers, geen 'als analyst kan ik niet...'.\n"
        "Format:\n"
        "  Regel 1: 1 zin met de hoofdconclusie (winst/verlies, sentiment).\n"
        "  Bullets: 3-5 punten met concrete cijfers (open trades, win rate, biggest move, regime).\n"
        "  Slot: 1 observatie of vraag voor de eigenaar.\n\n"
        f"Stats JSON:\n{json.dumps(stats, indent=2, ensure_ascii=False)}\n"
    )
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.3, "num_predict": 500},
    }
    r = requests.post(OLLAMA_URL, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    return str(data.get("response") or "").strip()


def _build_message(stats: Dict[str, Any], ai_text: str) -> str:
    header = f"*AI samenvatting* — {datetime.now().strftime('%H:%M %d-%m')}\n"
    body = ai_text or "(geen AI-tekst)"
    footer = (
        f"\n_PnL 24h: €{stats['total_pnl_eur']:+.2f} | "
        f"trades {stats['closed_count']} (W{stats['wins']}/L{stats['losses']}) | "
        f"open {stats['open_count']}_"
    )
    return header + body + footer


def _send_report(cfg: Dict[str, Any]) -> bool:
    model = str(cfg.get("OLLAMA_REPORTER_MODEL", "llama3.2:3b"))
    timeout = float(cfg.get("OLLAMA_REPORTER_TIMEOUT", 240.0))
    stats = _gather_24h_stats()
    try:
        ai_text = _ask_ollama(stats, model, timeout)
    except Exception as exc:
        ai_text = f"[ollama unavailable: {exc}]"
    msg = _build_message(stats, ai_text)
    ok = send_telegram(msg)
    print(f"[reporter] sent={ok} closed={stats['closed_count']} pnl={stats['total_pnl_eur']:+.2f}")
    return bool(ok)


def _next_trigger_ts(hours: List[int]) -> float:
    now = datetime.now()
    today_secs = now.hour * 3600 + now.minute * 60 + now.second
    today_ts0 = time.time() - today_secs
    candidates = sorted({int(h) % 24 for h in hours})
    for h in candidates:
        ts = today_ts0 + h * 3600
        if ts > time.time() + 5:
            return ts
    # all of today's slots passed -> first slot tomorrow
    return today_ts0 + 24 * 3600 + candidates[0] * 3600


def _record_run() -> None:
    try:
        LAST_RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAST_RUN_PATH.write_text(json.dumps({"ts": time.time()}), encoding="utf-8")
    except Exception:
        pass


def _last_run_ts() -> float:
    try:
        if LAST_RUN_PATH.exists():
            return float(json.loads(LAST_RUN_PATH.read_text(encoding="utf-8")).get("ts", 0))
    except Exception:
        pass
    return 0.0


def main() -> None:
    cfg = load_config()
    if not bool(cfg.get("OLLAMA_REPORTER_ENABLED", True)):
        print("[reporter] disabled via OLLAMA_REPORTER_ENABLED=false")
        return
    hours = cfg.get("OLLAMA_REPORTER_HOURS") or [8, 14, 20]
    if not isinstance(hours, list):
        hours = [8, 14, 20]
    print(f"[reporter] starting — model={cfg.get('OLLAMA_REPORTER_MODEL', 'llama3.2:3b')} hours={hours}")

    if bool(cfg.get("OLLAMA_REPORTER_FORCE_ONCE", False)):
        print("[reporter] FORCE_ONCE=true → sending immediately")
        _send_report(cfg)
        _record_run()

    while True:
        try:
            cfg = load_config()
            hours = cfg.get("OLLAMA_REPORTER_HOURS") or [8, 14, 20]
            if not isinstance(hours, list):
                hours = [8, 14, 20]
            next_ts = _next_trigger_ts([int(h) for h in hours])
            sleep_s = max(30.0, next_ts - time.time())
            print(f"[reporter] next report at {datetime.fromtimestamp(next_ts).strftime('%H:%M %d-%m')} (sleep {sleep_s/60:.1f} min)")
            # sleep in 60s chunks so a config change is picked up reasonably fast
            end = time.time() + sleep_s
            while time.time() < end:
                time.sleep(min(60.0, end - time.time()))
            # avoid double-send within same hour-slot
            if time.time() - _last_run_ts() < 30 * 60:
                continue
            _send_report(cfg)
            _record_run()
        except KeyboardInterrupt:
            print("[reporter] stopping (ctrl+c)")
            return
        except Exception as exc:
            print(f"[reporter] error: {exc}")
            time.sleep(60)


if __name__ == "__main__":
    main()
