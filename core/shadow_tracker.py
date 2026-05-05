"""Shadow Tracker — parallel evaluation of new trading strategies.

Runs alongside the live bot without affecting trades. Logs what new
strategies (timing filter, velocity filter, DMS) WOULD have done,
so we can compare after 1 week.

Data files:
  data/shadow_log.jsonl       — append-only log of every shadow decision
  data/shadow_phantom.json    — active phantom trades (DMS) being tracked
  data/shadow_dms_watchlist.json — DMS top-50 opportunity markets
"""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable, Dict, List, Optional, Sequence, Tuple

_ROOT = Path(__file__).resolve().parent.parent
_DATA = _ROOT / "data"
_LOG_PATH = _DATA / "shadow_log.jsonl"
_PHANTOM_PATH = _DATA / "shadow_phantom.json"
_DMS_PATH = _DATA / "shadow_dms_watchlist.json"

# Phantom trade simulation parameters
_TRAILING_STOP_PCT = 5.0  # close if price drops 5% from peak
_TRAILING_TIGHT_PCT = 3.5  # tighten to 3.5% when +5% above entry
_TRAILING_TIGHTER_PCT = 2.5  # tighten to 2.5% when +10% above entry
_STOP_LOSS_PCT = 8.0  # hard stop loss at -8%
_MAX_HOLD_HOURS = 72  # force close after 72 hours
_MIN_LOG_SCORE = 3.0  # only log evaluations where score >= this


@dataclass
class ShadowDecision:
    """One shadow evaluation result."""

    market: str
    timestamp: float
    score: float
    price: float
    bot_decision: str  # "buy" or "skip"
    shadow_decision: str  # "buy", "block_timing", "block_velocity", "skip"
    timing_filter: str  # "boost", "block", "neutral"
    velocity_filter: str  # "ok", "soft_block"
    is_dms: bool  # True if from DMS scan (not in bot whitelist)
    score_with_filters: float  # score after timing + velocity adjustments
    reason: str

    def to_dict(self) -> dict:
        return {
            "market": self.market,
            "ts": round(self.timestamp, 1),
            "score": round(self.score, 2),
            "price": self.price,
            "bot": self.bot_decision,
            "shadow": self.shadow_decision,
            "timing": self.timing_filter,
            "velocity": self.velocity_filter,
            "dms": self.is_dms,
            "adj_score": round(self.score_with_filters, 2),
            "reason": self.reason,
        }


class ShadowTracker:
    """Track what timing filter, velocity filter, and DMS would have done."""

    def __init__(self):
        self._lock = Lock()
        self._phantom_trades: Dict[str, dict] = {}
        self._dms_watchlist: List[dict] = []
        self._dms_last_refresh: float = 0
        self._dms_scan_index: int = 0
        self._velocity_cache: Dict[str, float] = {}
        self._velocity_cache_ts: float = 0
        self._eval_count: int = 0
        self._load_phantom()

    # ═══════════════════════════════════════════════════════════════════
    # Timing Filter
    # ═══════════════════════════════════════════════════════════════════

    @staticmethod
    def timing_filter(hour_utc: int) -> Tuple[str, float]:
        """Return (label, score_modifier) based on hour of day (UTC).

        Block 13:00-17:00 UTC → score penalty -3.0
        Boost 00:00-06:00 UTC → score bonus  +0.5
        """
        if 13 <= hour_utc <= 16:  # 13:00-16:59
            return "block", -3.0
        elif 0 <= hour_utc <= 5:  # 00:00-05:59
            return "boost", +0.5
        return "neutral", 0.0

    # ═══════════════════════════════════════════════════════════════════
    # Velocity Filter (30-day rolling P&L per market)
    # ═══════════════════════════════════════════════════════════════════

    def _refresh_velocity_cache(self, closed_trades: Sequence):
        """Compute 30-day rolling P&L per market from closed trades."""
        now = time.time()
        if now - self._velocity_cache_ts < 3600:
            return
        cutoff = now - 30 * 86400
        pnl: Dict[str, float] = {}
        for t in closed_trades:
            ts = _parse_ts(t.get("timestamp") or t.get("opened_ts") or 0)
            if ts < cutoff:
                continue
            m = t.get("market", "")
            p = float(t.get("profit") or 0)
            pnl[m] = pnl.get(m, 0.0) + p
        self._velocity_cache = pnl
        self._velocity_cache_ts = now

    def velocity_filter(self, market: str, closed_trades: Sequence) -> Tuple[str, float]:
        """Return (label, score_modifier) based on 30-day rolling P&L.

        Markets with negative rolling P&L get a -2.0 score penalty (soft block).
        """
        self._refresh_velocity_cache(closed_trades)
        pnl = self._velocity_cache.get(market, 0.0)
        if pnl < 0:
            return "soft_block", -2.0
        return "ok", 0.0

    # ═══════════════════════════════════════════════════════════════════
    # Main evaluation
    # ═══════════════════════════════════════════════════════════════════

    def evaluate_entry(
        self,
        market: str,
        score: float,
        price: float,
        min_score_threshold: float,
        closed_trades: Sequence,
        bot_would_buy: bool,
        is_dms: bool = False,
    ) -> Optional[ShadowDecision]:
        """Evaluate a market with shadow filters and log the decision.

        Returns the ShadowDecision if logged, None if skipped (low score).
        """
        self._eval_count += 1
        now = time.time()
        hour_utc = int(time.strftime("%H", time.gmtime(now)))

        # Apply filters
        timing_label, timing_mod = self.timing_filter(hour_utc)
        velocity_label, velocity_mod = self.velocity_filter(market, closed_trades)

        adj_score = score + timing_mod + velocity_mod
        shadow_would_buy = adj_score >= min_score_threshold

        # Decide shadow label
        if shadow_would_buy:
            shadow_label = "buy"
        elif timing_mod < 0 and (score + velocity_mod) >= min_score_threshold:
            shadow_label = "block_timing"
        elif velocity_mod < 0 and (score + timing_mod) >= min_score_threshold:
            shadow_label = "block_velocity"
        else:
            shadow_label = "skip"

        # Only log interesting evaluations (score near threshold, or decisions differ)
        dominated_by_noise = (
            score < _MIN_LOG_SCORE and adj_score < _MIN_LOG_SCORE and not bot_would_buy and not shadow_would_buy
        )
        if dominated_by_noise and not is_dms:
            return None

        # Build reason string
        reasons = []
        if timing_mod != 0:
            reasons.append(f"timing:{timing_label}({timing_mod:+.1f})")
        if velocity_mod != 0:
            pnl = self._velocity_cache.get(market, 0.0)
            reasons.append(f"velocity:{velocity_label}(30d={pnl:+.1f}€,mod={velocity_mod:+.1f})")
        if is_dms:
            reasons.append("dms_market")
        reason = ", ".join(reasons) if reasons else "no_filter_impact"

        decision = ShadowDecision(
            market=market,
            timestamp=now,
            score=score,
            price=price,
            bot_decision="buy" if bot_would_buy else "skip",
            shadow_decision=shadow_label,
            timing_filter=timing_label,
            velocity_filter=velocity_label,
            is_dms=is_dms,
            score_with_filters=adj_score,
            reason=reason,
        )

        # Append to JSONL log
        _append_jsonl(decision.to_dict(), _LOG_PATH)

        # Track phantom trades (DMS: shadow buys, bot doesn't scan)
        if shadow_would_buy and not bot_would_buy and is_dms:
            self._open_phantom(market, price, adj_score, "dms_opportunity", now)

        # Track avoided trades (bot buys, shadow blocks)
        if bot_would_buy and not shadow_would_buy:
            _append_jsonl(
                {
                    "type": "avoided",
                    "market": market,
                    "ts": round(now, 1),
                    "entry_price": price,
                    "score": round(score, 2),
                    "adj_score": round(adj_score, 2),
                    "block_reason": shadow_label,
                    "timing": timing_label,
                    "velocity": velocity_label,
                },
                _LOG_PATH,
            )

        return decision

    # ═══════════════════════════════════════════════════════════════════
    # Phantom Trade Tracking (DMS paper trades)
    # ═══════════════════════════════════════════════════════════════════

    def _open_phantom(self, market: str, price: float, score: float, reason: str, ts: float):
        """Open a phantom trade (shadow would buy, bot didn't scan this market)."""
        with self._lock:
            if market in self._phantom_trades:
                existing = self._phantom_trades[market]
                if existing.get("status") == "open":
                    return  # already tracking
            self._phantom_trades[market] = {
                "market": market,
                "entry_price": price,
                "entry_score": round(score, 2),
                "entry_ts": ts,
                "reason": reason,
                "peak_price": price,
                "current_price": price,
                "phantom_pnl_pct": 0.0,
                "last_updated": ts,
                "status": "open",
            }
            self._save_phantom()

    def update_phantom_prices(self, get_price_fn: Callable[[str], Optional[float]]):
        """Update current prices for all open phantom trades.

        Simulates simplified trailing stop exits:
        - 5% trailing stop (tightens to 3.5%/2.5% at higher profits)
        - 8% hard stop loss
        - 72h max hold time
        """
        with self._lock:
            changed = False
            for m, pt in list(self._phantom_trades.items()):
                if pt.get("status") != "open":
                    continue
                try:
                    price = get_price_fn(m)
                    if not price or price <= 0:
                        continue

                    pt["current_price"] = price
                    pt["peak_price"] = max(pt["peak_price"], price)
                    entry = pt["entry_price"]
                    if entry > 0:
                        pt["phantom_pnl_pct"] = round((price - entry) / entry * 100, 2)
                    pt["last_updated"] = time.time()
                    changed = True

                    # Determine trailing distance based on profit level
                    profit_pct = (price - entry) / entry * 100 if entry > 0 else 0
                    if profit_pct >= 10:
                        trail_pct = _TRAILING_TIGHTER_PCT
                    elif profit_pct >= 5:
                        trail_pct = _TRAILING_TIGHT_PCT
                    else:
                        trail_pct = _TRAILING_STOP_PCT

                    # Trailing stop: price dropped X% from peak while in profit
                    peak = pt["peak_price"]
                    if peak > 0 and peak > entry:
                        drop_from_peak = (peak - price) / peak * 100
                        if drop_from_peak >= trail_pct:
                            self._close_phantom(pt, price, "trailing_stop")
                            continue

                    # Hard stop loss
                    if pt["phantom_pnl_pct"] <= -_STOP_LOSS_PCT:
                        self._close_phantom(pt, price, "stop_loss")
                        continue

                    # Max hold time
                    hold_hours = (time.time() - pt["entry_ts"]) / 3600
                    if hold_hours >= _MAX_HOLD_HOURS:
                        self._close_phantom(pt, price, "max_hold")
                        continue

                except Exception:
                    pass

            if changed:
                self._save_phantom()

    @staticmethod
    def _close_phantom(pt: dict, price: float, reason: str):
        """Close a phantom trade with final stats."""
        pt["status"] = f"closed_{reason}"
        pt["exit_price"] = price
        pt["exit_ts"] = time.time()
        entry = pt["entry_price"]
        pt["final_pnl_pct"] = round((price - entry) / entry * 100, 2) if entry > 0 else 0.0

    # ═══════════════════════════════════════════════════════════════════
    # DMS — Dynamic Market Scanner
    # ═══════════════════════════════════════════════════════════════════

    def refresh_dms_watchlist(self, bitvavo_client, current_whitelist: list) -> List[dict]:
        """Refresh DMS watchlist every 4 hours from Bitvavo ticker24h.

        Calculates opportunity score = volatility × sqrt(volume_eur)
        for all EUR markets not in current whitelist. Returns top 50.
        """
        now = time.time()
        if now - self._dms_last_refresh < 4 * 3600:
            return self._dms_watchlist

        try:
            ticker24h = bitvavo_client.ticker24h({})
        except Exception:
            return self._dms_watchlist

        if not ticker24h:
            return self._dms_watchlist

        whitelist_set = set(current_whitelist or [])
        candidates = []

        for t in ticker24h:
            m = t.get("market", "")
            if not m.endswith("-EUR"):
                continue
            if m in whitelist_set:
                continue  # already scanned by bot

            # Use volumeQuote (EUR volume) if available, else estimate
            vol_eur = float(t.get("volumeQuote") or 0)
            if vol_eur <= 0:
                vol_base = float(t.get("volume") or 0)
                last_price = float(t.get("last") or 0)
                vol_eur = vol_base * last_price

            if vol_eur < 1000:
                continue  # skip micro-cap

            high = float(t.get("high") or 0)
            low = float(t.get("low") or 0)
            if high <= 0 or low <= 0:
                continue
            volatility = (high - low) / low * 100  # 24h range %

            # Opportunity = volatility × sqrt(volume_eur / 10000)
            opportunity = volatility * math.sqrt(vol_eur / 10000)

            candidates.append(
                {
                    "market": m,
                    "volume_eur": round(vol_eur),
                    "volatility_pct": round(volatility, 1),
                    "opportunity": round(opportunity, 1),
                    "price": float(t.get("last") or 0),
                }
            )

        candidates.sort(key=lambda x: x["opportunity"], reverse=True)
        self._dms_watchlist = candidates[:50]
        self._dms_last_refresh = now

        # Persist watchlist
        try:
            _DATA.mkdir(parents=True, exist_ok=True)
            tmp = str(_DMS_PATH) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"updated": now, "markets": self._dms_watchlist}, f, indent=2)
            os.replace(tmp, str(_DMS_PATH))
        except Exception:
            pass

        return self._dms_watchlist

    def get_dms_markets_to_evaluate(self, count: int = 3) -> List[dict]:
        """Get next batch of DMS markets to evaluate (rotating through list)."""
        if not self._dms_watchlist:
            return []
        n = len(self._dms_watchlist)
        start = self._dms_scan_index % n
        batch = []
        for i in range(min(count, n)):
            idx = (start + i) % n
            batch.append(self._dms_watchlist[idx])
        self._dms_scan_index = (start + count) % max(1, n)
        return batch

    # ═══════════════════════════════════════════════════════════════════
    # Persistence
    # ═══════════════════════════════════════════════════════════════════

    def _save_phantom(self):
        """Save phantom trades (atomic write)."""
        try:
            _DATA.mkdir(parents=True, exist_ok=True)
            tmp = str(_PHANTOM_PATH) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._phantom_trades, f, indent=2)
            os.replace(tmp, str(_PHANTOM_PATH))
        except Exception:
            pass

    def _load_phantom(self):
        """Load phantom trades from disk."""
        try:
            if _PHANTOM_PATH.exists():
                with open(str(_PHANTOM_PATH), "r", encoding="utf-8") as f:
                    self._phantom_trades = json.load(f)
        except Exception:
            self._phantom_trades = {}

    # ═══════════════════════════════════════════════════════════════════
    # Stats (for logging / dashboard)
    # ═══════════════════════════════════════════════════════════════════

    def get_stats(self) -> dict:
        """Get summary stats for periodic logging."""
        with self._lock:
            open_ph = [p for p in self._phantom_trades.values() if p.get("status") == "open"]
            closed_ph = [p for p in self._phantom_trades.values() if p.get("status", "").startswith("closed")]
            phantom_pnl_sum = sum(p.get("phantom_pnl_pct", 0) for p in open_ph)

        # Count from log file
        blocks_timing = 0
        blocks_velocity = 0
        dms_buys = 0
        avoided = 0
        try:
            if _LOG_PATH.exists():
                with open(str(_LOG_PATH), "r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            e = json.loads(line.strip())
                            if e.get("type") == "avoided":
                                avoided += 1
                            elif e.get("shadow") == "block_timing":
                                blocks_timing += 1
                            elif e.get("shadow") == "block_velocity":
                                blocks_velocity += 1
                            if e.get("dms") and e.get("shadow") == "buy":
                                dms_buys += 1
                        except Exception:
                            pass
        except Exception:
            pass

        return {
            "evals": self._eval_count,
            "timing_blocks": blocks_timing,
            "velocity_blocks": blocks_velocity,
            "avoided_trades": avoided,
            "dms_phantom_buys": dms_buys,
            "open_phantoms": len(open_ph),
            "closed_phantoms": len(closed_ph),
            "phantom_pnl_sum_pct": round(phantom_pnl_sum, 2),
            "dms_watchlist": len(self._dms_watchlist),
        }


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════


def _append_jsonl(entry: dict, path: Path):
    """Append a single JSON line to a JSONL file."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(path), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        pass


def _parse_ts(val) -> float:
    """Parse a timestamp that may be a float, int, or ISO date string."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except ValueError:
            pass
        # Try common datetime formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                import datetime

                dt = datetime.datetime.strptime(val, fmt)
                return dt.timestamp()
            except ValueError:
                continue
    return 0.0


# ═══════════════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════════════

_tracker: Optional[ShadowTracker] = None


def get_shadow_tracker() -> ShadowTracker:
    """Get or create the module-level ShadowTracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = ShadowTracker()
    return _tracker
