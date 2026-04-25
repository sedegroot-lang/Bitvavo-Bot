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

_cache: TTLCache = TTLCache(maxsize=128, ttl=2)
_long_cache: TTLCache = TTLCache(maxsize=64, ttl=30)


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


def _compute_trailing_stop(buy_price: float, highest_price: float, trailing_activated: bool, cfg: Dict[str, Any]) -> Optional[float]:
    """Mirror bot.trailing logic for dashboard display."""
    if not (trailing_activated and highest_price and highest_price > buy_price > 0):
        return None
    try:
        default_trail = float(cfg.get("DEFAULT_TRAILING", 0.04) or 0.04)
        stepped_raw = cfg.get("STEPPED_TRAILING_LEVELS", []) or []
        stepped = []
        for s in stepped_raw:
            if isinstance(s, (list, tuple)) and len(s) >= 2:
                stepped.append({"profit_pct": float(s[0]), "trailing_pct": float(s[1])})
            elif isinstance(s, dict):
                stepped.append({"profit_pct": float(s.get("profit_pct", 0)), "trailing_pct": float(s.get("trailing_pct", default_trail))})
        profit_pct = (highest_price - buy_price) / buy_price
        trail_pct = default_trail
        for lvl in reversed(sorted(stepped, key=lambda x: x["profit_pct"])):
            if profit_pct >= lvl["profit_pct"]:
                trail_pct = min(trail_pct, lvl["trailing_pct"])
                break
        return highest_price * (1 - trail_pct)
    except Exception:
        return None


def _trades() -> Dict[str, Any]:
    log = _read_json(DATA / "trade_log.json", {"open": {}, "closed": []}) or {}
    archive = _read_json(DATA / "trade_archive.json", []) or []
    if isinstance(archive, dict):
        archive = archive.get("closed") or archive.get("trades") or []
    open_trades = log.get("open") or {}
    closed_live = log.get("closed") or []
    closed_all = list(closed_live) + list(archive) if isinstance(closed_live, list) else list(archive)

    # Dedup by (market, sell_price, profit) — log.closed and archive overlap when bot rotates
    _seen = set()
    _deduped: List[Dict[str, Any]] = []
    for t in closed_all:
        if not isinstance(t, dict):
            continue
        try:
            key = (t.get("market"), round(float(t.get("sell_price") or 0), 8), round(float(t.get("profit") or 0), 4))
        except Exception:
            key = (t.get("market"), str(t.get("sell_price")), str(t.get("profit")))
        if key in _seen:
            continue
        _seen.add(key)
        _deduped.append(t)
    closed_all = _deduped

    def _ts_key(t: Dict[str, Any]) -> float:
        for k in ("closed_ts", "timestamp", "archived_at"):
            v = t.get(k)
            if v is None:
                continue
            if isinstance(v, (int, float)):
                return float(v)
            if isinstance(v, str):
                try:
                    import datetime as _dt
                    return _dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
                except Exception:
                    continue
        return 0.0
    closed_recent = sorted(closed_all, key=_ts_key, reverse=True)[:300]

    prices = _read_json(DATA / "price_cache.json", {}) or {}
    cfg = _merged_config()

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
        # honour partial TPs: amount on log might be original; partial_tp_events.last.remaining_amount wins
        ptp = tr.get("partial_tp_events") or []
        if ptp and isinstance(ptp, list):
            try:
                rem = float(ptp[-1].get("remaining_amount") or 0)
                if rem > 0:
                    amount = rem
            except Exception:
                pass

        cur_value = (cur * amount) if (cur and amount) else None
        unrealised = round(cur_value - invested, 2) if (cur_value is not None and invested) else None
        unrealised_pct = round((cur / buy_p - 1) * 100, 2) if (cur and buy_p) else None

        # Trailing
        trailing_activated = bool(tr.get("trailing_activated"))
        activation_price = float(tr.get("activation_price") or 0) or None
        if not activation_price and buy_p:
            try:
                activation_price = buy_p * (1 + float(tr.get("trailing_activation_pct") or cfg.get("TRAILING_ACTIVATION_PCT", 0.02)))
            except Exception:
                activation_price = None
        highest_price = float(tr.get("highest_price") or tr.get("highest_since_activation") or 0) or None
        trailing_stop = _compute_trailing_stop(buy_p, highest_price or buy_p, trailing_activated, cfg)
        # progress (current → activation)
        trailing_progress_pct = None
        if cur and buy_p and activation_price and activation_price > buy_p:
            trailing_progress_pct = max(0.0, min(100.0, (cur - buy_p) / (activation_price - buy_p) * 100))

        # DCA
        dca_max = int(tr.get("dca_max") or cfg.get("DCA_MAX_BUYS") or 0)
        dca_buys = min(int(tr.get("dca_buys") or 0), dca_max if dca_max else 999)
        dca_next_price = float(tr.get("dca_next_price") or 0) or None
        if not dca_next_price and buy_p and dca_buys < dca_max:
            try:
                drop = float(tr.get("dca_drop_pct") or cfg.get("DCA_DROP_PCT") or 0.06)
                dca_next_price = buy_p * (1 - drop * (dca_buys + 1))
            except Exception:
                pass
        dca_distance_pct = None
        if cur and dca_next_price:
            dca_distance_pct = max(0.0, (cur - dca_next_price) / cur * 100)

        # Status
        if trailing_activated and (unrealised_pct or 0) >= 0:
            status = "TRAILING ACTIEF"
        elif trailing_activated:
            status = "TRAILING WACHT"
        elif (unrealised_pct or 0) <= -10:
            status = "HOOG VERLIES"
        elif (unrealised_pct or 0) >= 5:
            status = "WINST"
        else:
            status = "ACTIEF"

        opened_ts = float(tr.get("opened_ts") or tr.get("timestamp") or 0)
        time_in_trade_h = (time.time() - opened_ts) / 3600 if opened_ts else None

        enriched[mkt] = {
            **tr,
            "symbol": mkt.replace("-EUR", ""),
            "amount_remaining": amount,
            "current_price": cur,
            "current_value_eur": round(cur_value, 2) if cur_value is not None else None,
            "unrealised_pnl_eur": unrealised,
            "unrealised_pnl_pct": unrealised_pct,
            "activation_price": activation_price,
            "trailing_stop": trailing_stop,
            "trailing_progress_pct": round(trailing_progress_pct, 1) if trailing_progress_pct is not None else None,
            "highest_price": highest_price,
            "dca_level": dca_buys,
            "dca_max_levels": dca_max,
            "dca_next_price": dca_next_price,
            "dca_distance_pct": round(dca_distance_pct, 2) if dca_distance_pct is not None else None,
            "dca_buy_amount": float(tr.get("dca_amount_eur") or cfg.get("DCA_AMOUNT_EUR") or 5),
            "status_label": status,
            "time_in_trade_h": round(time_in_trade_h, 2) if time_in_trade_h else None,
            "stop_loss_distance_pct": round((buy_p - trailing_stop) / buy_p * 100, 2) if (trailing_stop and buy_p) else None,
        }

    return {
        "open": enriched,
        "closed_recent": closed_recent,
        "open_count": len(enriched),
        "closed_total": len(closed_recent),
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

    # Detect actually-active grids by querying open orders (best-effort, cached 30s)
    open_order_counts: Dict[str, int] = {}
    try:
        bv_key = "bv_client::dashboard"
        if bv_key in _long_cache:
            bv = _long_cache[bv_key]
        else:
            try:
                from dotenv import load_dotenv  # type: ignore
                load_dotenv()
            except Exception:
                pass
            try:
                from python_bitvavo_api.bitvavo import Bitvavo  # type: ignore
                ak = os.environ.get("BITVAVO_API_KEY", "")
                sk = os.environ.get("BITVAVO_API_SECRET", "")
                bv = Bitvavo({"APIKEY": ak, "APISECRET": sk}) if ak and sk else None
                _long_cache[bv_key] = bv
            except Exception:
                bv = None
        if bv is not None:
            for market in states.keys():
                ck = f"grid_open::{market}"
                if ck in _long_cache:
                    open_order_counts[market] = _long_cache[ck]
                    continue
                try:
                    oo = bv.ordersOpen({"market": market})
                    n = len(oo) if isinstance(oo, list) else 0
                    open_order_counts[market] = n
                    _long_cache[ck] = n
                except Exception:
                    pass
    except Exception:
        pass

    summary = []
    for market, st in states.items():
        cfg = st.get("config", {})
        levels = st.get("levels", []) or []
        placed = sum(1 for L in levels if L.get("status") == "placed")
        filled = sum(1 for L in levels if L.get("status") == "filled")
        live_orders = open_order_counts.get(market)
        # "actief" = enabled in config AND at least 1 live open order on Bitvavo (if we could check)
        cfg_enabled = bool(cfg.get("enabled"))
        if live_orders is not None:
            is_active = cfg_enabled and live_orders > 0
            status_label = "ACTIEF" if is_active else ("GEPAUZEERD" if cfg_enabled else "UIT")
        else:
            is_active = cfg_enabled and placed > 0
            status_label = "ACTIEF (state)" if is_active else ("GEPAUZEERD" if cfg_enabled else "UIT")
        summary.append({
            "market": market,
            "enabled": cfg_enabled,
            "is_active": is_active,
            "status_label": status_label,
            "live_open_orders": live_orders,
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


def _signal_status() -> Dict[str, Any]:
    """Mirror V1 trade-readiness: explain WHY no new trade is starting (or why it would).

    Returns:
        status: 'green'|'yellow'|'red'
        label/message/icon/color
        scan_stats: total_markets, evaluated, passed_min_score, min_score_threshold,
                    effective_min_score, regime, regime_score_adj, adaptive_bump,
                    adaptive_reason, cooldown_active_count, pending_reservations
        blocks/warnings/details: human-readable reasons
        filters: active config thresholds (min_score, rsi range, volume, spread)
        capacity: open/max trades + EUR available
    """
    try:
        cfg = _merged_config()
        hb = _read_json(DATA / "heartbeat.json", {}) or {}
        log = _read_json(DATA / "trade_log.json", {"open": {}}) or {}
        open_trades = log.get("open") or {}

        scan = hb.get("last_scan_stats") or {}
        total_markets = int(scan.get("total_markets") or 0)
        evaluated = int(scan.get("evaluated") or 0)
        skipped = int(scan.get("skipped") or 0)
        passed = int(scan.get("passed_min_score") or 0)
        min_score_threshold = float(scan.get("min_score_threshold") or cfg.get("MIN_SCORE_TO_BUY", 7) or 7)
        regime = scan.get("regime") or ""
        regime_score_adj = float(scan.get("regime_score_adj") or 0)
        scan_ts = float(scan.get("timestamp") or 0)
        scan_age_sec = max(0.0, time.time() - scan_ts) if scan_ts else None

        # Adaptive score bump (best-effort lazy import)
        adaptive_bump = 0.0
        adaptive_reason = ""
        try:
            from bot.adaptive_score import get_instance as _get_as  # type: ignore
            adaptive_bump, adaptive_reason = _get_as().adjustment(cfg=cfg)
            adaptive_bump = float(adaptive_bump or 0)
        except Exception:
            pass

        # Post-loss cooldown
        cooldown_active_count = 0
        cooldown_preview: List[str] = []
        try:
            from bot.post_loss_cooldown import get_instance as _get_cd  # type: ignore
            _cd = _get_cd()
            _now = time.time()
            for _m, _entry in list(getattr(_cd, "_state", {}).items())[:50]:
                _until = _entry.get("cooldown_until", 0)
                if _until and _until > _now:
                    cooldown_active_count += 1
                    if len(cooldown_preview) < 3:
                        cooldown_preview.append(f"{_m} ({int((_until - _now) / 60)}m)")
        except Exception:
            pass

        max_trades = int(cfg.get("MAX_OPEN_TRADES", 5) or 5)
        open_count = len(open_trades) if isinstance(open_trades, dict) else 0
        eur_balance = float(hb.get("eur_balance") or 0)
        base_amount = float(cfg.get("BASE_AMOUNT_EUR", 12) or 12)
        min_balance = float(cfg.get("MIN_BALANCE_RESERVE", 10) or 10)
        pending_res = int(hb.get("pending_reservations") or 0)
        regime_blocking = (regime or "").lower() == "bearish" or regime_score_adj > 50
        effective_min_score = round(min_score_threshold + adaptive_bump, 2)

        rsi_min = float(cfg.get("RSI_MIN_BUY", 35) or 35)
        rsi_max = float(cfg.get("RSI_MAX_BUY", 65) or 65)
        min_volume = float(cfg.get("MIN_AVG_VOLUME_1M", 5.0) or 5.0)
        max_spread = float(cfg.get("MAX_SPREAD_PCT", 0.005) or 0.005)

        blocks: List[str] = []
        warnings: List[str] = []
        details: List[str] = []

        if regime_blocking:
            blocks.append(f"Regime {(regime or 'BEARISH').upper()}: nieuwe entries geblokkeerd (+{regime_score_adj:.0f})")
        if open_count >= max_trades:
            blocks.append(f"Max trades bereikt: {open_count}/{max_trades}")
        elif open_count >= max_trades - 1:
            warnings.append(f"Bijna max trades: {open_count}/{max_trades}")
        available = eur_balance - min_balance
        if available < base_amount:
            blocks.append(f"Onvoldoende saldo: €{eur_balance:.2f} (nodig: €{base_amount + min_balance:.2f})")
        elif available < base_amount * 2:
            warnings.append(f"Laag saldo: €{eur_balance:.2f} — slechts 1 trade-slot")

        # Reason lines
        if total_markets > 0:
            if passed == 0:
                details.append(f"⚠️ {evaluated}/{total_markets} markets gescand — niemand scoort ≥ {effective_min_score:.1f}")
            else:
                details.append(f"✅ {passed} market(s) voldoen aan min score {effective_min_score:.1f}")
            if skipped > 0:
                details.append(f"⏭️ {skipped} market(s) overgeslagen (al open / cooldown / filter)")
        else:
            details.append("⏳ Eerste market-scan loopt nog (geen scan-stats in heartbeat)")
        if abs(adaptive_bump) >= 0.01:
            arrow = "↑" if adaptive_bump > 0 else "↓"
            details.append(f"🎯 Adaptive MIN_SCORE {arrow} {adaptive_bump:+.1f} — {adaptive_reason or 'WR-aanpassing'}")
        if cooldown_active_count > 0:
            extra = f" (+{cooldown_active_count - len(cooldown_preview)} meer)" if cooldown_active_count > len(cooldown_preview) else ""
            details.append(f"⏸️ {cooldown_active_count} market(s) in post-loss cooldown: {', '.join(cooldown_preview)}{extra}")
        if pending_res > 0:
            details.append(f"🔒 {pending_res} reservering(en) worden verwerkt")
        slots_free = max(0, max_trades - open_count)
        details.append(f"💰 Saldo €{eur_balance:.2f} · {slots_free} slot(s) vrij · ~{int(available / base_amount) if base_amount > 0 else 0} trade(s) mogelijk")

        if blocks:
            status, color, icon, label = "red", "#ef4444", "🔴", "GEBLOKKEERD"
            message = blocks[0]
        elif warnings:
            status, color, icon, label = "yellow", "#f59e0b", "🟡", "BEPERKT"
            if passed == 0 and total_markets > 0:
                message = f"Wacht op signaal — geen market scoort ≥ {effective_min_score:.1f}"
            elif total_markets == 0:
                message = "Wacht op eerste market-scan"
            else:
                message = warnings[0]
        else:
            status, color, icon, label = "green", "#10b981", "🟢", "GEREED"
            if passed == 0 and total_markets > 0:
                label = "GEREED (wacht)"
                message = f"Wacht op signaal — geen market scoort ≥ {effective_min_score:.1f}"
            elif total_markets == 0:
                message = "Wacht op eerste market-scan"
            else:
                message = f"{slots_free} slot(s) vrij · {passed} kandidaat(en) ≥ {effective_min_score:.1f}"

        return {
            "status": status,
            "color": color,
            "icon": icon,
            "label": label,
            "message": message,
            "blocks": blocks,
            "warnings": warnings,
            "details": details,
            "scan_stats": {
                "total_markets": total_markets,
                "evaluated": evaluated,
                "skipped": skipped,
                "passed_min_score": passed,
                "min_score_threshold": min_score_threshold,
                "effective_min_score": effective_min_score,
                "adaptive_bump": adaptive_bump,
                "adaptive_reason": adaptive_reason,
                "regime": regime,
                "regime_score_adj": regime_score_adj,
                "cooldown_active_count": cooldown_active_count,
                "cooldown_preview": cooldown_preview,
                "pending_reservations": pending_res,
                "scan_age_sec": scan_age_sec,
                "scan_ts": scan_ts,
            },
            "filters": {
                "min_score": min_score_threshold,
                "rsi_min": rsi_min,
                "rsi_max": rsi_max,
                "min_volume_1m_keur": min_volume,
                "max_spread_pct": max_spread * 100,
            },
            "capacity": {
                "open_trades": open_count,
                "max_trades": max_trades,
                "slots_free": slots_free,
                "eur_balance": eur_balance,
                "eur_reserve": min_balance,
                "eur_available": available,
                "base_amount": base_amount,
                "possible_trades": int(available / base_amount) if base_amount > 0 else 0,
            },
        }
    except Exception as e:
        return {
            "status": "unknown", "color": "#64748b", "icon": "⚪", "label": "STATUS ONBEKEND",
            "message": f"signal-status fout: {e}", "blocks": [], "warnings": [], "details": [],
            "scan_stats": {}, "filters": {}, "capacity": {},
        }


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
    """Per-market historical performance + live price (rich enough for sorting/filtering)."""
    mm = _read_json(DATA / "market_metrics.json", {}) or {}
    prices = _read_json(DATA / "price_cache.json", {}) or {}
    rows = []
    if isinstance(mm, dict):
        for market, data in mm.items():
            if not isinstance(data, dict):
                continue
            cur = None
            try:
                pinfo = prices.get(market)
                if isinstance(pinfo, dict):
                    cur = float(pinfo.get("price") or 0) or None
                elif isinstance(pinfo, (int, float)):
                    cur = float(pinfo)
            except Exception:
                pass
            trades = int(data.get("trades") or 0)
            wins = int(data.get("wins") or 0)
            wr = (wins / trades * 100) if trades > 0 else 0.0
            rows.append({
                "market": market,
                "symbol": market.replace("-EUR", ""),
                "current_price": cur,
                "trades": trades,
                "wins": wins,
                "losses": int(data.get("losses") or 0),
                "win_rate_pct": round(wr, 1),
                "total_profit_eur": round(float(data.get("total_profit") or 0), 2),
                "avg_profit_eur": round(float(data.get("avg_profit") or 0), 2),
                "avg_roi_pct": round(float(data.get("avg_roi_pct") or 0) * 100, 2),
                "avg_hold_h": round(float(data.get("avg_hold_seconds") or 0) / 3600, 1),
                "consecutive_losses": int(data.get("consecutive_losses") or 0),
                "last_reason": data.get("last_reason") or "",
                "last_profit_eur": round(float(data.get("last_profit") or 0), 2),
                "last_closed_ts": data.get("last_closed_ts"),
            })
    rows.sort(key=lambda r: r["total_profit_eur"], reverse=True)
    return {"markets": rows, "total": len(rows)}


def _roadmap() -> Dict[str, Any]:
    """Rich data-driven growth plan from current value to €10.000.

    Mirrors the V1 Flask roadmap: milestones with ETA, weekly profits, performance,
    smart advice, golden rules, deposit scenarios, passive income table.
    """
    cfg = _merged_config()
    overview = _read_json(DATA / "account_overview.json", {}) or {}
    hb = _heartbeat()

    current_value = float(overview.get("total_account_value_eur") or 0)
    if current_value <= 0:
        current_value = float(hb.get("eur_balance") or 0)

    deposits_data = _read_json(CONFIG_DIR / "deposits.json", {}) or {}
    total_deposited = float(deposits_data.get("total_deposited_eur") or 0)

    # Milestones (matches V1)
    milestones = [
        {"value": 465,   "label": "€465",    "action": "V1 Start (11 mrt 2026)", "icon": "✅", "star": False},
        {"value": 700,   "label": "€700",    "action": "V1: DCA Hybrid F_CONSERVATIEF", "icon": "✅", "star": False},
        {"value": 1000,  "label": "€1.000",  "action": "V1: Grid BTC aan", "icon": "✅", "star": False},
        {"value": 1240,  "label": "€1.240",  "action": "V2 START: BASE 150, 4 trades, DCA max 6", "icon": "✅", "star": False},
        {"value": 1450,  "label": "€1.450",  "action": "V3: BASE 320, MAX 4, DCA 20×2 — full edge stack", "icon": "⭐", "star": True},
        {"value": 1700,  "label": "€1.700",  "action": "BASE 380, MAX 4, DCA 25×2", "icon": "📍", "star": False},
        {"value": 2000,  "label": "€2.000",  "action": "BASE 400, MAX 5, DCA 25×2", "icon": "⭐", "star": True},
        {"value": 2500,  "label": "€2.500",  "action": "BASE 480, MAX 5, DCA 30×2", "icon": "📍", "star": False},
        {"value": 3000,  "label": "€3.000",  "action": "BASE 550, MAX 5, DCA 35×2", "icon": "⭐", "star": True},
        {"value": 4000,  "label": "€4.000",  "action": "BASE 700, MAX 5, DCA 50×2", "icon": "📍", "star": False},
        {"value": 5000,  "label": "€5.000",  "action": "BASE 850, MAX 5, DCA 70×2", "icon": "⭐", "star": True},
        {"value": 7500,  "label": "€7.500",  "action": "BASE 1.250, MAX 6, DCA 100×2", "icon": "📍", "star": False},
        {"value": 10000, "label": "€10.000", "action": "BASE 1.500, MAX 6, DCA 150×2 — Passief Inkomen", "icon": "🏆", "star": True},
    ]
    current_idx = 0
    for i, m in enumerate(milestones):
        if current_value >= m["value"]:
            current_idx = i
    progress_pct = min(100.0, max(0.0, (current_value / 10000.0) * 100))

    # Sparkline (last 30 days)
    sparkline: List[Dict[str, Any]] = []
    try:
        from datetime import datetime as _dt
        cutoff = time.time() - 30 * 86400
        daily_vals: Dict[str, float] = {}
        bh_rows = _read_jsonl(DATA / "balance_history.jsonl", max_lines=20000)
        for entry in bh_rows:
            ts = float(entry.get("ts") or 0)
            if ts < cutoff:
                continue
            day = _dt.fromtimestamp(ts).strftime("%Y-%m-%d")
            daily_vals[day] = float(entry.get("total_eur") or 0)
        for day in sorted(daily_vals.keys()):
            sparkline.append({"date": day, "value": round(daily_vals[day], 2)})
    except Exception:
        pass

    # Weekly profits (last 8 full weeks)
    weekly_profits: List[Dict[str, Any]] = []
    try:
        from datetime import datetime as _dt
        from collections import defaultdict as _dd
        weekly_raw = _dd(lambda: {"profit": 0.0, "trades": 0, "wins": 0})
        pnl_rows = _read_jsonl(DATA / "trade_pnl_history.jsonl", max_lines=5000)
        for entry in pnl_rows:
            ts = float(entry.get("ts") or entry.get("closed_ts") or 0)
            if ts == 0:
                continue
            wk = _dt.fromtimestamp(ts).strftime("%Y-W%W")
            p = float(entry.get("profit_eur") or entry.get("net_pnl_eur") or 0)
            weekly_raw[wk]["profit"] += p
            weekly_raw[wk]["trades"] += 1
            if p > 0:
                weekly_raw[wk]["wins"] += 1
        for wk in sorted(weekly_raw.keys())[-8:]:
            w = weekly_raw[wk]
            wr = round(w["wins"] / w["trades"] * 100) if w["trades"] > 0 else 0
            weekly_profits.append({"week": wk, "profit": round(w["profit"], 2),
                                   "trades": w["trades"], "wins": w["wins"], "winrate": wr})
    except Exception:
        pass

    # Perf stats
    perf_stats = {
        "total_profit": 0, "total_trades": 0, "win_rate": 0, "avg_profit": 0,
        "avg_hold_hrs": 0, "best_market": "-", "best_market_profit": 0,
        "worst_market": "-", "worst_market_profit": 0, "recent_win_rate": 0,
    }
    try:
        exp_rows = _read_jsonl(DATA / "expectancy_history.jsonl", max_lines=200)
        if exp_rows:
            exp = exp_rows[-1]
            perf_stats["total_trades"] = int(exp.get("sample_size") or 0)
            perf_stats["win_rate"] = round(float(exp.get("win_rate") or 0) * 100, 1)
            perf_stats["total_profit"] = round(float(exp.get("net_profit") or 0), 2)
            avg_win = float(exp.get("avg_win") or 0)
            avg_loss = float(exp.get("avg_loss") or 0)
            wr = float(exp.get("win_rate") or 0)
            perf_stats["avg_profit"] = round(avg_win * wr + avg_loss * (1 - wr), 2)
        mm = _read_json(DATA / "market_metrics.json", {}) or {}
        if isinstance(mm, dict) and mm:
            best = max(mm.items(), key=lambda x: float((x[1] or {}).get("total_profit", 0) or 0))
            worst = min(mm.items(), key=lambda x: float((x[1] or {}).get("total_profit", 0) or 0))
            perf_stats["best_market"] = best[0].replace("-EUR", "")
            perf_stats["best_market_profit"] = round(float(best[1].get("total_profit", 0) or 0), 2)
            perf_stats["worst_market"] = worst[0].replace("-EUR", "")
            perf_stats["worst_market_profit"] = round(float(worst[1].get("total_profit", 0) or 0), 2)
            total_hold = sum(float(v.get("avg_hold_seconds", 0) or 0) * float(v.get("trades", 0) or 0) for v in mm.values() if isinstance(v, dict))
            total_t = sum(float(v.get("trades", 0) or 0) for v in mm.values() if isinstance(v, dict))
            if total_t > 0:
                perf_stats["avg_hold_hrs"] = round(total_hold / total_t / 3600, 1)
        if len(weekly_profits) >= 2:
            recent = weekly_profits[-2:]
            r_wins = sum(w["wins"] for w in recent)
            r_trades = sum(w["trades"] for w in recent)
            perf_stats["recent_win_rate"] = round(r_wins / r_trades * 100) if r_trades > 0 else 0
        elif weekly_profits:
            perf_stats["recent_win_rate"] = weekly_profits[-1]["winrate"]
    except Exception:
        pass

    # Growth rate from sparkline (excl. deposits)
    monthly_deposit = 100.0
    deposit_per_week = monthly_deposit / 4.33
    growth_per_week = 0.0
    growth_per_week_pct = 0.0
    try:
        if len(sparkline) >= 7:
            span_days = min(14, len(sparkline))
            recent = sparkline[-span_days:]
            v0 = recent[0]["value"]
            v1 = recent[-1]["value"]
            if v0 > 0:
                deposits_in_span = (monthly_deposit / 30.0) * span_days
                pure = (v1 - v0) - deposits_in_span
                growth_per_week = pure / span_days * 7
                growth_per_week_pct = (growth_per_week / v0) * 100
    except Exception:
        pass

    # ETA per milestone
    growth_factor = 1 + (growth_per_week_pct / 100.0)
    for m in milestones:
        if current_value >= m["value"]:
            m["eta"] = ""
            m["eta_weeks"] = 0
            continue
        if growth_per_week_pct <= 0 and deposit_per_week <= 0:
            m["eta"] = "?"
            m["eta_weeks"] = 0
            continue
        simv = current_value
        weeks = 0
        while simv < m["value"] and weeks < 520:
            simv = simv * growth_factor + deposit_per_week
            weeks += 1
        m["eta_weeks"] = weeks
        if weeks >= 520:
            m["eta"] = "> 10 jaar"
        else:
            from datetime import datetime as _dt, timedelta as _td
            eta_date = _dt.now() + _td(weeks=weeks)
            m["eta"] = eta_date.strftime("%b %Y") if weeks > 12 else eta_date.strftime("%d %b %Y")

    # Next milestone detail
    next_milestone = None
    if current_idx + 1 < len(milestones):
        nm = milestones[current_idx + 1]
        gap = nm["value"] - current_value
        eur_free = current_value - float(hb.get("total_exposure_eur") or 0)
        buffer_pct = (eur_free / current_value * 100) if current_value > 0 else 0
        checklist = [
            {"label": "Winrate ≥ 60% (laatste 2 weken)", "ok": perf_stats["recent_win_rate"] >= 60,
             "detail": f"{perf_stats['recent_win_rate']}%"},
            {"label": "Buffer ≥ 20%", "ok": buffer_pct >= 20,
             "detail": f"{buffer_pct:.0f}% (€{eur_free:.0f} vrij)"},
            {"label": "Config stabiel ≥ 2 weken", "ok": True, "detail": "auto"},
        ]
        next_milestone = {
            "label": nm["label"], "action": nm["action"],
            "gap": round(gap, 0), "eta": nm.get("eta", "?"),
            "eta_weeks": nm.get("eta_weeks", 0), "checklist": checklist,
        }

    # Smart advice
    advice_items: List[Dict[str, str]] = []
    rwr = perf_stats["recent_win_rate"]
    if rwr >= 60:
        advice_items.append({"type": "success", "icon": "✅", "text": f"Winrate {rwr}% — boven 60% drempel"})
    elif rwr > 0:
        advice_items.append({"type": "danger", "icon": "⚠️", "text": f"Winrate {rwr}% — onder 60% drempel! Overweeg voorzichtiger config"})
    eur_avail = float(hb.get("eur_balance") or 0)
    if current_value > 0:
        buf = eur_avail / current_value * 100
        if buf >= 20:
            advice_items.append({"type": "success", "icon": "✅", "text": f"Buffer {buf:.0f}% — boven 20% minimum"})
        else:
            advice_items.append({"type": "danger", "icon": "🔴", "text": f"Buffer {buf:.0f}% — ONDER 20%! Verlaag exposure"})
    if growth_per_week > 0:
        advice_items.append({"type": "info", "icon": "📈",
                             "text": f"Groei: €{growth_per_week:.0f}/week trading + €{deposit_per_week:.0f}/week stortingen"})
    elif growth_per_week < -10:
        advice_items.append({"type": "danger", "icon": "📉",
                             "text": f"Portfolio krimpt: €{growth_per_week:.0f}/week — check bear protocol"})
    if weekly_profits:
        wp = weekly_profits[-1]
        if wp["trades"] > 0:
            advice_items.append({"type": "info", "icon": "📊",
                                 "text": f"Deze week: {wp['trades']} trades, €{wp['profit']:.2f} winst, {wp['winrate']}% winrate"})
    if next_milestone:
        advice_items.append({"type": "info", "icon": "🎯",
                             "text": f"Volgende mijlpaal ({next_milestone['label']}): nog €{next_milestone['gap']:.0f} — geschat {next_milestone['eta']}"})

    # Golden rules
    golden_rules = [
        "Minimaal 2 weken evalueren na elke config-wijziging",
        "Winrate check: moet ≥ 60% zijn over laatste 2 weken",
        "EUR buffer: houd ALTIJD minimaal 20% van portfoliowaarde vrij",
        "Bij 15% drawdown: verlaag BASE met 30% en ga naar vorige fase",
        "DCA_MAX_BUYS nooit boven 8 — meer DCA = geld vastzetten",
        "Grid pas uitbreiden bij bewezen positieve PnL op bestaande grids",
        "MAX_TRADES verhogen = BASE verlagen — nooit beide tegelijk omhoog",
    ]

    # Bear protocol
    bear_protocol = [
        {"trigger": "Trigger 1: Portfolio −8% in 1 week", "action": "BASE −30%, MIN_SCORE +0,5"},
        {"trigger": "Trigger 2: Portfolio −15% in 2 weken", "action": "Terug naar 2 mijlpalen eerder + halveer grid budget"},
        {"trigger": "Trigger 3: Portfolio −25%+ (crash)", "action": "Noodconfig: 3 trades, €50 BASE, Grid uit. Wacht op stabilisatie."},
    ]

    # Deposit scenarios
    SCENARIOS = [0, 100, 200, 300, 500, 1000]
    TARGETS = [2000, 5000, 10000, 25000, 50000]
    deposit_scenarios = []
    for dep in SCENARIOS:
        weekly_dep = dep / 4.33
        etas = []
        for t in TARGETS:
            if current_value >= t:
                etas.append("✅"); continue
            if growth_per_week_pct <= 0 and weekly_dep <= 0:
                etas.append("∞"); continue
            simv = current_value; w = 0
            while simv < t and w < 1040:
                simv = simv * growth_factor + weekly_dep
                w += 1
            if w >= 1040:
                etas.append("> 20j")
            else:
                from datetime import datetime as _dt, timedelta as _td
                d = _dt.now() + _td(weeks=w)
                etas.append(d.strftime("%b %Y") if w > 12 else d.strftime("%d %b"))
        deposit_scenarios.append({"monthly": dep, "etas": etas, "is_current": dep == int(monthly_deposit)})

    # Active phase from current config
    active_config = {
        "max_open_trades": cfg.get("MAX_OPEN_TRADES"),
        "base_amount_eur": cfg.get("BASE_AMOUNT_EUR"),
        "min_score_to_buy": cfg.get("MIN_SCORE_TO_BUY"),
        "dca_amount_eur": cfg.get("DCA_AMOUNT_EUR") or cfg.get("DCA_ORDER_EUR"),
        "dca_max_buys": cfg.get("DCA_MAX_BUYS"),
        "grid_investment": (cfg.get("GRID_TRADING") or {}).get("investment_eur") if isinstance(cfg.get("GRID_TRADING"), dict) else cfg.get("GRID_INVESTMENT"),
    }

    # ── Realistische Verwachting (passive_income table) ──
    # Compute week-yield distribution (P25/median/P75) from real weekly_profits,
    # then compound month (4.33w) + year (52w) projections per capital step.
    passive_income_stats = {
        "sample_weeks": 0, "has_data": False,
        "p25_week_pct": 0.0, "median_week_pct": 0.0, "p75_week_pct": 0.0,
        "max_dd_pct": 0.0, "total_realised_pnl": 0.0, "cap_note": "",
        "p25_day_eur": 0.0, "med_day_eur": 0.0, "p75_day_eur": 0.0,
    }
    passive_income_table: List[Dict[str, Any]] = []
    try:
        # MaxDD over sparkline (last 30d)
        if sparkline and len(sparkline) >= 3:
            vals = [p["value"] for p in sparkline if p.get("value", 0) > 0]
            if vals:
                peak = vals[0]
                worst = 0.0
                for v in vals:
                    if v > peak:
                        peak = v
                    dd = (v - peak) / peak * 100 if peak > 0 else 0
                    if dd < worst:
                        worst = dd
                passive_income_stats["max_dd_pct"] = round(worst, 2)

        # Distribution from full weeks (excl. current)
        from datetime import datetime as _dt3
        now_wk = _dt3.now().strftime("%Y-W%W")
        full_weeks = [w for w in weekly_profits if w["week"] != now_wk and w["trades"] > 0]
        if full_weeks and current_value > 0 and len(full_weeks) >= 3:
            pcts = sorted([(w["profit"] / current_value) * 100 for w in full_weeks])
            n = len(pcts)
            def _pct(arr, q):
                if not arr:
                    return 0.0
                k = (len(arr) - 1) * q
                f = int(k)
                c = min(f + 1, len(arr) - 1)
                if f == c:
                    return arr[f]
                return arr[f] + (arr[c] - arr[f]) * (k - f)
            p25 = _pct(pcts, 0.25)
            med = _pct(pcts, 0.50)
            p75 = _pct(pcts, 0.75)
            passive_income_stats.update({
                "sample_weeks": n, "has_data": True,
                "p25_week_pct": round(p25, 3),
                "median_week_pct": round(med, 3),
                "p75_week_pct": round(p75, 3),
                "total_realised_pnl": round(sum(w["profit"] for w in full_weeks), 2),
                "cap_note": (f"Slechts {n} volledige weken data — projecties zijn ruw"
                             if n < 6 else f"{n} weken realtime data"),
                # Daily yield in € for current_value (informative)
                "p25_day_eur": round(current_value * p25 / 100.0 / 7.0, 2),
                "med_day_eur": round(current_value * med / 100.0 / 7.0, 2),
                "p75_day_eur": round(current_value * p75 / 100.0 / 7.0, 2),
            })

            # Compound projections
            def _comp(weekly_pct: float, weeks: float) -> float:
                if weekly_pct == 0:
                    return 0.0
                return ((1 + weekly_pct / 100.0) ** weeks - 1) * 100.0

            m_p25, m_med, m_p75 = _comp(p25, 4.33), _comp(med, 4.33), _comp(p75, 4.33)
            y_p25, y_med, y_p75 = _comp(p25, 52), _comp(med, 52), _comp(p75, 52)

            for cap in [1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000, 25000, 50000]:
                passive_income_table.append({
                    "capital": cap,
                    "day_p25": round(cap * p25 / 100.0 / 7.0, 2),
                    "day_med": round(cap * med / 100.0 / 7.0, 2),
                    "day_p75": round(cap * p75 / 100.0 / 7.0, 2),
                    "week_p25": round(cap * p25 / 100.0, 2),
                    "week_med": round(cap * med / 100.0, 2),
                    "week_p75": round(cap * p75 / 100.0, 2),
                    "month_p25": round(cap * m_p25 / 100.0, 0),
                    "month_med": round(cap * m_med / 100.0, 0),
                    "month_p75": round(cap * m_p75 / 100.0, 0),
                    "year_p25": round(cap * y_p25 / 100.0, 0),
                    "year_med": round(cap * y_med / 100.0, 0),
                    "year_p75": round(cap * y_p75 / 100.0, 0),
                    "is_current": (cap <= current_value < cap * 1.5) if cap < 50000 else (current_value >= cap),
                })
        else:
            passive_income_stats["cap_note"] = (
                f"Slechts {len(full_weeks)} volledige week(en) data — minimaal 3 nodig"
            )
    except Exception:
        pass

    return {
        "current_value": round(current_value, 2),
        "current_idx": current_idx,
        "progress_pct": round(progress_pct, 2),
        "milestones": milestones,
        "total_deposited": round(total_deposited, 2),
        "sparkline": sparkline,
        "weekly_profits": weekly_profits,
        "perf_stats": perf_stats,
        "next_milestone": next_milestone,
        "advice_items": advice_items,
        "growth_per_week": round(growth_per_week, 2),
        "growth_per_week_pct": round(growth_per_week_pct, 3),
        "monthly_deposit": int(monthly_deposit),
        "golden_rules": golden_rules,
        "bear_protocol": bear_protocol,
        "deposit_scenarios": deposit_scenarios,
        "scenario_targets": TARGETS,
        "active_config": active_config,
        "passive_income_stats": passive_income_stats,
        "passive_income_table": passive_income_table,
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


@app.get("/api/signal-status")
def signal_status() -> Dict[str, Any]:
    return _signal_status()


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
        "signal_status": _signal_status(),
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
