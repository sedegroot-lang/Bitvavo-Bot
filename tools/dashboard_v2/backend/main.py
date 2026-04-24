"""
Dashboard V2 — FastAPI backend (full rebuild).

Reads the same JSON/JSONL files as the legacy Flask dashboard but exposes a
clean JSON API that powers a single-page Tailwind/Alpine frontend.

All file reads are cached on `mtime_ns` so repeat calls are sub-millisecond.

Endpoints (read):
    GET  /api/health
    GET  /api/portfolio
    GET  /api/trades
    GET  /api/performance
    GET  /api/balance-history?period=1d|7d|30d|90d|all
    GET  /api/deposits
    GET  /api/ai
    GET  /api/memory
    GET  /api/shadow
    GET  /api/regime
    GET  /api/heartbeat
    GET  /api/grid
    GET  /api/hodl
    GET  /api/parameters
    GET  /api/markets
    GET  /api/roadmap
    GET  /api/all
Endpoints (write — limited, safe):
    POST /api/parameters       body={"key": "...", "value": ...}
    POST /api/refresh          clears server cache
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cachetools import TTLCache
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA = PROJECT_ROOT / "data"
CONFIG_DIR = PROJECT_ROOT / "config"
METRICS_DIR = PROJECT_ROOT / "metrics"
STATIC = Path(__file__).resolve().parent.parent / "frontend"

LOCAL_CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "BotConfig" / "bot_config_local.json"

app = FastAPI(title="Bitvavo Bot Dashboard V2", version="2.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_cache: TTLCache = TTLCache(maxsize=128, ttl=5)


# -------------------------------------------------------------------- Helpers


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        key = f"json::{path}::{path.stat().st_mtime_ns}"
        if key in _cache:
            return _cache[key]
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _cache[key] = data
        return data
    except Exception:
        return default


def _read_jsonl(path: Path, max_lines: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        key = f"jsonl::{path}::{path.stat().st_mtime_ns}::{max_lines}"
        if key in _cache:
            return _cache[key]
        rows: List[Dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as f:
            # tail-read for big files
            if max_lines and path.stat().st_size > 2_000_000:
                # Read last ~2MB chunk for big files
                f.seek(max(0, path.stat().st_size - 2_000_000))
                f.readline()  # discard partial
                lines = f.readlines()
            else:
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
        _cache[key] = rows
        return rows
    except Exception:
        return []


def _merged_config() -> Dict[str, Any]:
    """3-layer merge: base → overrides → local. Local wins."""
    base = _read_json(CONFIG_DIR / "bot_config.json", {}) or {}
    overrides = _read_json(CONFIG_DIR / "bot_config_overrides.json", {}) or {}
    local = _read_json(LOCAL_CONFIG, {}) or {}
    merged = {**base, **overrides, **local}
    return merged


def _safe_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Strip secret-ish keys."""
    bad = {"SECRET", "KEY", "PASSWORD", "TOKEN", "API"}
    out = {}
    for k, v in cfg.items():
        upper = k.upper()
        if any(b in upper for b in bad):
            continue
        out[k] = v
    return out


# -------------------------------------------------------------------- Domain accessors


def _heartbeat() -> Dict[str, Any]:
    hb = _read_json(DATA / "heartbeat.json", {}) or {}
    last_ts = hb.get("last_update_ts") or hb.get("ts") or hb.get("timestamp") or 0
    age = max(0.0, time.time() - float(last_ts)) if last_ts else None
    ai_hb = _read_json(DATA / "ai_heartbeat.json", {}) or {}
    ai_ts = ai_hb.get("ts") or ai_hb.get("timestamp") or 0
    ai_age = max(0.0, time.time() - float(ai_ts)) if ai_ts else None
    return {
        **hb,
        "age_seconds": age,
        "ai_age_seconds": ai_age,
        "bot_online": age is not None and age < 180,
        "ai_online": ai_age is not None and ai_age < 600,
    }


def _portfolio() -> Dict[str, Any]:
    overview = _read_json(DATA / "account_overview.json", {}) or {}
    hb = _heartbeat()
    pnl_rows = _read_jsonl(DATA / "trade_pnl_history.jsonl", max_lines=5000)
    deposits = _read_json(CONFIG_DIR / "deposits.json", {}) or {}

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

    total_deposited = float(deposits.get("total_deposited_eur") or 0)
    total_value = float(overview.get("total_account_value_eur") or 0)
    realised = round(total_pnl, 2)

    return {
        "total_account_value_eur": total_value,
        "eur_balance": overview.get("eur_available", hb.get("eur_balance")),
        "eur_in_orders": overview.get("eur_in_orders", 0),
        "asset_value_eur": overview.get("open_trade_value_eur"),
        "open_positions": overview.get("open_trade_count"),
        "total_deposited_eur": total_deposited,
        "total_realised_pnl_eur": realised,
        "total_fees_eur": round(total_fees, 2),
        "net_change_eur": round(total_value - total_deposited, 2) if total_deposited else None,
        "net_change_pct": round((total_value - total_deposited) / total_deposited * 100, 2) if total_deposited else None,
        "weekly": weekly_list,
        "monthly": monthly_list,
        "daily": daily_list,
        "trade_count": len(pnl_rows),
        "last_update": overview.get("updated_at"),
    }


def _trades() -> Dict[str, Any]:
    log = _read_json(DATA / "trade_log.json", {"open": {}, "closed": []}) or {}
    open_trades = log.get("open") or {}
    closed = log.get("closed") or []
    if isinstance(closed, list):
        closed_recent = sorted(
            closed,
            key=lambda t: t.get("closed_ts", 0) or t.get("timestamp", 0),
            reverse=True,
        )[:200]
    else:
        closed_recent = []

    # Live prices from price cache
    prices = _read_json(DATA / "price_cache.json", {}) or {}

    # Enrich open trades with current price + unrealised PnL
    enriched = {}
    for mkt, tr in (open_trades.items() if isinstance(open_trades, dict) else []):
        cur = None
        try:
            pinfo = prices.get(mkt) or prices.get(mkt.replace("-EUR", ""))
            if isinstance(pinfo, dict):
                cur = float(pinfo.get("price") or pinfo.get("last") or 0) or None
            elif isinstance(pinfo, (int, float)):
                cur = float(pinfo)
        except Exception:
            cur = None
        invested = float(tr.get("initial_invested_eur") or tr.get("invested_eur") or 0)
        amount = float(tr.get("amount") or 0)
        buy_p = float(tr.get("buy_price") or 0)
        unrealised = None
        unrealised_pct = None
        if cur and amount > 0 and invested > 0:
            cur_value = cur * amount
            unrealised = round(cur_value - invested, 2)
            unrealised_pct = round((cur / buy_p - 1) * 100, 2) if buy_p else None
        enriched[mkt] = {
            **tr,
            "current_price": cur,
            "current_value_eur": round(cur * amount, 2) if (cur and amount) else None,
            "unrealised_pnl_eur": unrealised,
            "unrealised_pnl_pct": unrealised_pct,
        }

    return {
        "open": enriched,
        "closed_recent": closed_recent,
        "open_count": len(enriched),
        "closed_total": len(closed) if isinstance(closed, list) else 0,
    }


def _performance() -> Dict[str, Any]:
    log = _read_json(DATA / "trade_log.json", {"open": {}, "closed": []}) or {}
    closed = log.get("closed") or []
    archive = _read_json(DATA / "trade_archive.json", []) or []
    if isinstance(archive, dict):
        archive = archive.get("closed") or []
    all_closed = list(closed) + list(archive) if isinstance(closed, list) else list(archive)

    wins = [t for t in all_closed if (t.get("profit") or 0) > 0]
    losses = [t for t in all_closed if (t.get("profit") or 0) <= 0]
    total_profit = sum(float(t.get("profit") or 0) for t in all_closed)
    avg_win = (sum(float(t.get("profit") or 0) for t in wins) / len(wins)) if wins else 0
    avg_loss = (sum(float(t.get("profit") or 0) for t in losses) / len(losses)) if losses else 0
    win_rate = (len(wins) / len(all_closed) * 100) if all_closed else 0
    expectancy = total_profit / len(all_closed) if all_closed else 0

    # Top / bottom — derive pct if missing, only show actual losers in bottom
    def _row(t: Dict[str, Any]) -> Dict[str, Any]:
        p = float(t.get("profit") or 0)
        pct = t.get("profit_pct")
        if pct is None:
            inv = float(t.get("initial_invested_eur") or t.get("invested_eur") or 0)
            pct = (p / inv * 100) if inv else None
        return {"market": t.get("market"), "profit": round(p, 2), "pct": round(pct, 2) if pct is not None else None, "ts": t.get("timestamp")}

    sorted_by_p = sorted(all_closed, key=lambda t: float(t.get("profit") or 0), reverse=True)
    top = [_row(t) for t in sorted_by_p[:10]]
    losers_only = [t for t in sorted_by_p if float(t.get("profit") or 0) < 0]
    bottom = [_row(t) for t in losers_only[-10:][::-1]] if losers_only else []

    # Per-market PnL
    by_market: Dict[str, Dict[str, Any]] = {}
    for t in all_closed:
        m = t.get("market") or "?"
        b = by_market.setdefault(m, {"pnl": 0.0, "trades": 0, "wins": 0})
        b["pnl"] += float(t.get("profit") or 0)
        b["trades"] += 1
        if (t.get("profit") or 0) > 0:
            b["wins"] += 1
    market_perf = sorted(
        [{"market": k, **{kk: round(vv, 2) if isinstance(vv, float) else vv for kk, vv in v.items()}} for k, v in by_market.items()],
        key=lambda x: x["pnl"],
        reverse=True,
    )

    return {
        "total_trades": len(all_closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "total_profit_eur": round(total_profit, 2),
        "avg_win_eur": round(avg_win, 2),
        "avg_loss_eur": round(avg_loss, 2),
        "expectancy_eur": round(expectancy, 2),
        "top_trades": top,
        "bottom_trades": bottom,
        "per_market": market_perf,
    }


def _balance_history(period: str = "30d") -> Dict[str, Any]:
    rows = _read_jsonl(DATA / "balance_history.jsonl", max_lines=20000)
    if not rows:
        return {"labels": [], "values": [], "current": None, "min": None, "max": None, "change_pct": None}
    now = time.time()
    cutoffs = {"1d": 86400, "7d": 86400 * 7, "30d": 86400 * 30, "90d": 86400 * 90, "all": None}
    cutoff = cutoffs.get(period, 86400 * 30)
    if cutoff is not None:
        rows = [r for r in rows if (r.get("ts") or 0) >= now - cutoff]
    if not rows:
        return {"labels": [], "values": [], "current": None}
    # Downsample if too many points
    max_points = 500
    if len(rows) > max_points:
        step = len(rows) // max_points
        rows = rows[::step]
    labels = [time.strftime("%Y-%m-%d %H:%M", time.gmtime(r.get("ts") or 0)) for r in rows]
    values = [float(r.get("total_eur") or 0) for r in rows]
    return {
        "labels": labels,
        "values": values,
        "current": values[-1] if values else None,
        "min": min(values) if values else None,
        "max": max(values) if values else None,
        "change_pct": round((values[-1] / values[0] - 1) * 100, 2) if values and values[0] else None,
    }


def _deposits() -> Dict[str, Any]:
    d = _read_json(CONFIG_DIR / "deposits.json", {"deposits": [], "total_deposited_eur": 0}) or {}
    deps = d.get("deposits") or []
    return {
        "deposits": deps,
        "total": float(d.get("total_deposited_eur") or sum(float(x.get("amount") or 0) for x in deps)),
        "count": len(deps),
    }


def _ai() -> Dict[str, Any]:
    suggestions = _read_json(DATA / "ai_suggestions.json", {}) or {}
    metrics_path = PROJECT_ROOT / "ai" / "ai_model_metrics_enhanced.json"
    metrics = _read_json(metrics_path, {}) or {}
    feedback = _read_json(DATA / "ai_feedback_loop.json", {}) or {}
    health = _read_json(DATA / "ai_health_report.json", {}) or {}
    walkforward = _read_json(DATA / "xgb_walkforward.json", {}) or {}
    return {
        "suggestions": suggestions.get("suggestions") or [],
        "insights": suggestions.get("insights") or [],
        "supervisor_run": suggestions.get("ts"),
        "model_metrics": metrics,
        "walkforward": walkforward,
        "feedback_loop": feedback if isinstance(feedback, dict) else {},
        "health_report": health,
    }


def _memory() -> Dict[str, Any]:
    mem = _read_json(DATA / "bot_memory.json", {}) or {}
    facts = mem.get("facts") or []
    suggestions_log = mem.get("suggestion_history") or []
    return {
        "fact_count": len(facts),
        "facts_recent": facts[-50:] if isinstance(facts, list) else [],
        "suggestion_log_count": len(suggestions_log),
        "suggestion_log_recent": suggestions_log[-30:] if isinstance(suggestions_log, list) else [],
    }


def _shadow() -> Dict[str, Any]:
    try:
        from bot.shadow_rotation import analyse  # lazy
        return analyse(window_days=14)
    except Exception as e:
        return {"error": str(e), "total": 0}


def _regime() -> Dict[str, Any]:
    rj = _read_json(DATA / "current_regime.json", {}) or {}
    markov = _read_json(DATA / "markov_regime.json", {}) or {}
    history = _read_jsonl(DATA / "regime_history.jsonl", max_lines=200)
    return {"current": rj, "markov": markov, "history_recent": history[-50:]}


def _grid() -> Dict[str, Any]:
    states = _read_json(DATA / "grid_states.json", {}) or {}
    fills_log = _read_json(DATA / "grid_fills_log.json", []) or []
    if isinstance(fills_log, dict):
        fills_log = fills_log.get("fills") or []
    summary = []
    for market, st in states.items():
        cfg = st.get("config", {})
        levels = st.get("levels", []) or []
        placed = sum(1 for L in levels if L.get("status") == "placed")
        filled = sum(1 for L in levels if L.get("status") == "filled")
        summary.append({
            "market": market,
            "enabled": cfg.get("enabled"),
            "lower_price": cfg.get("lower_price"),
            "upper_price": cfg.get("upper_price"),
            "num_grids": cfg.get("num_grids"),
            "investment": cfg.get("total_investment"),
            "mode": cfg.get("grid_mode"),
            "placed": placed,
            "filled": filled,
            "total_levels": len(levels),
        })
    fills_recent = sorted(
        [f for f in fills_log if isinstance(f, dict)],
        key=lambda f: f.get("ts") or f.get("timestamp") or 0,
        reverse=True,
    )[:50]
    return {"markets": summary, "fills_recent": fills_recent, "fills_total": len(fills_log)}


def _hodl() -> Dict[str, Any]:
    sched = _read_json(DATA / "hodl_schedule.json", {}) or {}
    cfg = _merged_config()
    targets = cfg.get("HODL_TARGETS") or cfg.get("HODL_PLAN") or {}
    prices = _read_json(DATA / "price_cache.json", {}) or {}
    items = []
    if isinstance(targets, dict):
        for market, tgt in targets.items():
            cur = None
            try:
                pinfo = prices.get(market)
                if isinstance(pinfo, dict):
                    cur = float(pinfo.get("price") or 0) or None
                elif isinstance(pinfo, (int, float)):
                    cur = float(pinfo)
            except Exception:
                pass
            entry = (sched.get("entries") or {}).get(market, {})
            items.append({
                "market": market,
                "target": tgt,
                "current_price": cur,
                "last_run": entry.get("last_run"),
                "status": entry.get("status"),
            })
    return {"items": items, "schedule": sched, "updated_at": sched.get("updated_at")}


def _parameters() -> Dict[str, Any]:
    cfg = _merged_config()
    safe = _safe_config(cfg)
    # Highlight commonly tuned keys
    sections = {
        "Entry": ["MIN_SCORE_TO_BUY", "MAX_OPEN_TRADES", "BASE_AMOUNT_EUR", "MIN_VOLUME_24H_EUR", "MIN_PRICE_EUR"],
        "DCA": ["DCA_ENABLED", "DCA_MAX_BUYS", "DCA_MAX_ORDERS", "DCA_DROP_PCT", "DCA_AMOUNT_EUR", "DCA_AMOUNT_RATIO", "DCA_SIZE_MULTIPLIER", "DCA_STEP_MULTIPLIER", "DCA_MIN_AMOUNT_EUR", "DCA_PYRAMID_UP", "DCA_HYBRID", "DCA_DYNAMIC", "SMART_DCA_ENABLED", "RSI_DCA_THRESHOLD"],
        "Trailing": ["TRAILING_ACTIVATION_PCT", "DEFAULT_TRAILING", "STEPPED_TRAILING_LEVELS", "BREAKEVEN_LOCK_PCT"],
        "Risk": ["MAX_TOTAL_EXPOSURE_EUR", "ENABLE_STOP_LOSS", "STOP_LOSS_ENABLED", "STOP_LOSS_PERCENT", "STOP_LOSS_HARD_PCT", "MAX_DAILY_LOSS_EUR", "REGIME_RISK_OVERRIDE"],
        "AI": ["AI_AUTO_APPLY", "AI_MIN_CONFIDENCE", "AI_REGIME_RECOMMENDATIONS", "USE_ML_FILTER", "ML_FILTER_THRESHOLD"],
        "Grid": ["GRID_TRADING", "GRID_ENABLED", "GRID_INVESTMENT", "GRID_MODE", "GRID_AUTO_REBALANCE", "AVELLANEDA_STOIKOV_GRID"],
        "HODL": ["HODL_ENABLED", "HODL_TARGETS", "HODL_PLAN", "HODL_SCHEDULER"],
    }
    section_data = {}
    used = set()
    for sect, keys in sections.items():
        section_data[sect] = {k: safe.get(k) for k in keys if k in safe}
        used.update(k for k in keys if k in safe)
    other = {k: v for k, v in safe.items() if k not in used}
    return {
        "sections": section_data,
        "other": other,
        "total_keys": len(safe),
        "local_path": str(LOCAL_CONFIG),
    }


def _markets() -> Dict[str, Any]:
    mm = _read_json(DATA / "market_metrics.json", {}) or {}
    rows = []
    if isinstance(mm, dict):
        for market, data in mm.items():
            if isinstance(data, dict):
                rows.append({"market": market, **data})
    rows.sort(key=lambda r: float(r.get("score") or r.get("volume_24h_eur") or 0), reverse=True)
    return {"markets": rows[:200], "total": len(rows)}


def _roadmap() -> Dict[str, Any]:
    """Pull current phase from PORTFOLIO_ROADMAP_V2.md if present."""
    md_path = PROJECT_ROOT / "docs" / "PORTFOLIO_ROADMAP_V2.md"
    phase = None
    next_phase = None
    if md_path.exists():
        try:
            text = md_path.read_text(encoding="utf-8", errors="ignore")
            # Heuristic: first heading "Phase ..." that isn't marked done
            import re
            for m in re.finditer(r"#+\s*(Phase[^\n]*)", text):
                title = m.group(1).strip()
                if "✅" in title or "DONE" in title.upper():
                    continue
                if phase is None:
                    phase = title
                else:
                    next_phase = title
                    break
        except Exception:
            pass
    cfg = _merged_config()
    return {
        "current_phase": phase,
        "next_phase": next_phase,
        "max_open_trades": cfg.get("MAX_OPEN_TRADES"),
        "base_amount_eur": cfg.get("BASE_AMOUNT_EUR"),
        "min_score_to_buy": cfg.get("MIN_SCORE_TO_BUY"),
        "dca_order_eur": cfg.get("DCA_AMOUNT_EUR") or cfg.get("DCA_ORDER_EUR"),
        "dca_max_buys": cfg.get("DCA_MAX_BUYS"),
        "grid_investment": (cfg.get("GRID_TRADING") or {}).get("investment_eur") if isinstance(cfg.get("GRID_TRADING"), dict) else cfg.get("GRID_INVESTMENT"),
    }


# -------------------------------------------------------------------- Routes


@app.get("/api/health")
def health() -> Dict[str, Any]:
    hb = _heartbeat()
    return {
        "ok": True,
        "ts": time.time(),
        "version": "2.1.0",
        "bot_online": hb.get("bot_online"),
        "ai_online": hb.get("ai_online"),
        "heartbeat_age_s": hb.get("age_seconds"),
    }


@app.get("/api/portfolio")
def portfolio() -> Dict[str, Any]:
    return _portfolio()


@app.get("/api/trades")
def trades() -> Dict[str, Any]:
    return _trades()


@app.get("/api/performance")
def performance() -> Dict[str, Any]:
    return _performance()


@app.get("/api/balance-history")
def balance_history(period: str = "30d") -> Dict[str, Any]:
    return _balance_history(period)


@app.get("/api/deposits")
def deposits() -> Dict[str, Any]:
    return _deposits()


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


@app.get("/api/grid")
def grid() -> Dict[str, Any]:
    return _grid()


@app.get("/api/hodl")
def hodl() -> Dict[str, Any]:
    return _hodl()


@app.get("/api/parameters")
def parameters() -> Dict[str, Any]:
    return _parameters()


@app.get("/api/markets")
def markets() -> Dict[str, Any]:
    return _markets()


@app.get("/api/roadmap")
def roadmap() -> Dict[str, Any]:
    return _roadmap()


@app.get("/api/all")
def all_payload() -> Dict[str, Any]:
    return {
        "ts": time.time(),
        "health": health(),
        "portfolio": _portfolio(),
        "trades": _trades(),
        "performance": _performance(),
        "balance_history": _balance_history("30d"),
        "deposits": _deposits(),
        "ai": _ai(),
        "memory": _memory(),
        "shadow": _shadow(),
        "regime": _regime(),
        "heartbeat": _heartbeat(),
        "grid": _grid(),
        "hodl": _hodl(),
        "parameters": _parameters(),
        "roadmap": _roadmap(),
    }


# ---- Write endpoints ----


class ParamUpdate(BaseModel):
    key: str
    value: Any


@app.post("/api/parameters")
def update_parameter(body: ParamUpdate) -> Dict[str, Any]:
    """Write a single key into LOCAL_CONFIG (the layer-3 override)."""
    if not body.key or not body.key.replace("_", "").isalnum() or not body.key.isupper():
        raise HTTPException(status_code=400, detail="Key must be UPPER_SNAKE_CASE")
    LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    current = _read_json(LOCAL_CONFIG, {}) or {}
    current[body.key] = body.value
    tmp = LOCAL_CONFIG.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LOCAL_CONFIG)
    _cache.clear()
    return {"ok": True, "key": body.key, "value": body.value, "path": str(LOCAL_CONFIG)}


@app.post("/api/refresh")
def refresh() -> Dict[str, Any]:
    _cache.clear()
    return {"ok": True, "ts": time.time()}


# -------------------------------------------------------------------- Static


if STATIC.exists():
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
