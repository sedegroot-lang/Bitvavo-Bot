"""
Dashboard V2 — FastAPI backend.

Fast, async, cached. Reads from the same JSON files as the legacy Flask
dashboard, but exposes a clean JSON API and serves a single-page modern
frontend (Tailwind + Alpine.js + Chart.js, no build step).

Endpoints:
    GET  /api/health              — basic alive
    GET  /api/portfolio           — totals, equity, weekly/monthly PnL, regime
    GET  /api/trades              — open + recently closed
    GET  /api/ai                  — AI insights, supervisor stats, model accuracy
    GET  /api/memory              — BotMemory snapshot
    GET  /api/shadow              — shadow rotation suggestions analysis
    GET  /api/regime              — current regime + last N detections
    GET  /api/heartbeat           — bot liveness
    GET  /api/all                 — composite payload (one round-trip)

Static frontend served from ./static.

Run:
    uvicorn tools.dashboard_v2.backend.main:app --host 0.0.0.0 --port 5002 --reload
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA = PROJECT_ROOT / "data"
STATIC = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Bitvavo Bot Dashboard V2", version="2.0.0")

# Permissive CORS — local network + tunnel use
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tiny TTL cache — enough to absorb spamming dashboards
_cache: TTLCache = TTLCache(maxsize=64, ttl=5)


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    key = f"json::{path}::{path.stat().st_mtime_ns}"
    if key in _cache:
        return _cache[key]
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        _cache[key] = data
        return data
    except Exception:
        return default


def _read_jsonl(path: Path, max_lines: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    key = f"jsonl::{path}::{path.stat().st_mtime_ns}::{max_lines}"
    if key in _cache:
        return _cache[key]
    rows: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as f:
            lines = f.readlines()
        if max_lines and len(lines) > max_lines:
            lines = lines[-max_lines:]
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    except Exception:
        pass
    _cache[key] = rows
    return rows


# -------------------------------------------------------------------- Data accessors


def _portfolio() -> Dict[str, Any]:
    overview = _read_json(DATA / "account_overview.json", {}) or {}
    heartbeat = _read_json(DATA / "heartbeat.json", {}) or {}
    pnl_rows = _read_jsonl(DATA / "trade_pnl_history.jsonl", max_lines=5000)

    # Group PnL by ISO week
    weekly: Dict[str, Dict[str, float]] = {}
    monthly: Dict[str, Dict[str, float]] = {}
    daily: Dict[str, Dict[str, float]] = {}
    total_pnl = 0.0
    total_fees = 0.0
    for r in pnl_rows:
        try:
            pnl = float(r.get("net_pnl_eur", r.get("profit_eur", 0)) or 0)
            fees = float(r.get("fees_eur", 0) or 0)
            ts = float(r.get("ts") or r.get("closed_ts") or 0)
            if ts <= 0:
                continue
            t = time.gmtime(ts)
            wk = f"{t.tm_year}-W{time.strftime('%V', t)}"
            mo = f"{t.tm_year}-{t.tm_mon:02d}"
            dy = time.strftime("%Y-%m-%d", t)
            for bucket, key in ((weekly, wk), (monthly, mo), (daily, dy)):
                b = bucket.setdefault(key, {"pnl": 0.0, "trades": 0, "fees": 0.0})
                b["pnl"] += pnl
                b["fees"] += fees
                b["trades"] += 1
            total_pnl += pnl
            total_fees += fees
        except (TypeError, ValueError):
            continue

    weekly_list = [{"week": k, **v} for k, v in sorted(weekly.items())]
    monthly_list = [{"month": k, **v} for k, v in sorted(monthly.items())]
    daily_list = [{"day": k, **v} for k, v in sorted(daily.items())[-90:]]

    return {
        "total_account_value_eur": overview.get("total_account_value_eur"),
        "eur_balance": heartbeat.get("eur_balance"),
        "asset_value_eur": overview.get("asset_value_eur"),
        "open_positions": overview.get("open_positions"),
        "total_realised_pnl_eur": round(total_pnl, 2),
        "total_fees_eur": round(total_fees, 2),
        "weekly": weekly_list,
        "monthly": monthly_list,
        "daily": daily_list,
        "trade_count": len(pnl_rows),
        "last_update": heartbeat.get("last_update"),
    }


def _trades() -> Dict[str, Any]:
    log = _read_json(DATA / "trade_log.json", {"open": {}, "closed": []}) or {}
    open_trades = log.get("open") or {}
    closed = log.get("closed") or []
    if isinstance(closed, list):
        closed_recent = sorted(closed, key=lambda t: t.get("closed_ts", 0) or t.get("timestamp", 0), reverse=True)[:50]
    else:
        closed_recent = []
    return {
        "open": open_trades if isinstance(open_trades, dict) else {},
        "closed_recent": closed_recent,
        "open_count": len(open_trades) if isinstance(open_trades, dict) else 0,
        "closed_total": len(closed) if isinstance(closed, list) else 0,
    }


def _ai() -> Dict[str, Any]:
    suggestions = _read_json(DATA / "ai_suggestions.json", {}) or {}
    metrics_path = PROJECT_ROOT / "ai" / "ai_model_metrics_enhanced.json"
    metrics = _read_json(metrics_path, {}) or {}
    return {
        "suggestions": suggestions.get("suggestions") or [],
        "insights": suggestions.get("insights") or [],
        "supervisor_run": suggestions.get("ts"),
        "model_metrics": metrics,
    }


def _memory() -> Dict[str, Any]:
    mem = _read_json(DATA / "bot_memory.json", {}) or {}
    facts = mem.get("facts") or []
    suggestions_log = mem.get("suggestion_history") or []
    return {
        "fact_count": len(facts),
        "facts_recent": facts[-30:] if isinstance(facts, list) else [],
        "suggestion_log_count": len(suggestions_log),
        "suggestion_log_recent": suggestions_log[-30:] if isinstance(suggestions_log, list) else [],
    }


def _shadow() -> Dict[str, Any]:
    try:
        from bot.shadow_rotation import analyse  # lazy import
        return analyse(window_days=14)
    except Exception as e:
        return {"error": str(e), "total": 0}


def _regime() -> Dict[str, Any]:
    rj = _read_json(DATA / "current_regime.json", {}) or {}
    history = _read_jsonl(DATA / "regime_history.jsonl", max_lines=200)
    return {"current": rj, "history_recent": history[-50:]}


def _heartbeat() -> Dict[str, Any]:
    hb = _read_json(DATA / "heartbeat.json", {}) or {}
    last_ts = hb.get("last_update_ts") or hb.get("ts") or 0
    age = max(0.0, time.time() - float(last_ts)) if last_ts else None
    return {**hb, "age_seconds": age}


# -------------------------------------------------------------------- Routes


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "ts": time.time(), "version": "2.0.0"}


@app.get("/api/portfolio")
def portfolio() -> Dict[str, Any]:
    return _portfolio()


@app.get("/api/trades")
def trades() -> Dict[str, Any]:
    return _trades()


@app.get("/api/ai")
def ai() -> Dict[str, Any]:
    return _ai()


@app.get("/api/memory")
def memory() -> Dict[str, Any]:
    return _memory()


@app.get("/api/shadow")
def shadow() -> Dict[str, Any]:
    return _shadow()


@app.get("/api/regime")
def regime() -> Dict[str, Any]:
    return _regime()


@app.get("/api/heartbeat")
def heartbeat() -> Dict[str, Any]:
    return _heartbeat()


@app.get("/api/all")
def all_payload() -> Dict[str, Any]:
    """Composite endpoint — single round-trip for full dashboard refresh."""
    return {
        "ts": time.time(),
        "portfolio": _portfolio(),
        "trades": _trades(),
        "ai": _ai(),
        "memory": _memory(),
        "shadow": _shadow(),
        "regime": _regime(),
        "heartbeat": _heartbeat(),
    }


# -------------------------------------------------------------------- Static


if STATIC.exists():
    # Mount whole frontend dir at root so /sw.js, /manifest.webmanifest, /assets/* all work.
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html")

    app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
else:
    @app.get("/")
    def fallback() -> JSONResponse:
        return JSONResponse({"error": "frontend not built", "static_dir": str(STATIC)})


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("DASH_V2_PORT", "5002"))
    uvicorn.run("tools.dashboard_v2.backend.main:app", host="0.0.0.0", port=port, reload=False)
