"""
Supervisor Memory — bridges ai_supervisor.py to modules.ai.bot_memory.BotMemory.

Two responsibilities:
  1. Log every AI suggestion (applied or not) with a snapshot of equity, regime,
     and recent perf so we have ground-truth for later evaluation.
  2. Before emitting a new suggestion, search memory for prior similar
     suggestions (same param, same direction, same regime) and attach a
     "history_hint" so the dashboard / auto-apply can deprioritise repeats
     that historically failed.

Outcome evaluation (whether a past suggestion "worked") runs separately
via `evaluate_pending_outcomes()` which can be called every few hours.

Storage: data/bot_memory.json (user_id="ai_supervisor")
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

try:
    from modules.ai.bot_memory import get_memory
except Exception:  # pragma: no cover

    def get_memory():  # type: ignore
        return None


USER_ID = "ai_supervisor"
SIMILAR_THRESHOLD = 0.20  # token-overlap score above which we count a "match"
PENDING_GRACE_HOURS = 24  # don't evaluate outcome until this old
PENDING_MAX_AGE_HOURS = 96  # if still no clear outcome, mark "inconclusive"


def _now() -> float:
    return time.time()


def _score(md: Dict[str, Any]) -> float:
    """Safely coerce outcome_score (may be None) to float."""
    v = md.get("outcome_score")
    try:
        return float(v) if v is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _direction(from_v: Any, to_v: Any) -> str:
    try:
        a = float(from_v)
        b = float(to_v)
        if b > a:
            return "up"
        if b < a:
            return "down"
        return "flat"
    except Exception:
        return "set"


def _make_text(suggestion: Dict[str, Any]) -> str:
    p = suggestion.get("param", "?")
    fr = suggestion.get("from", suggestion.get("current", "?"))
    to = suggestion.get("to", suggestion.get("new_value", suggestion.get("recommended", "?")))
    rsn = suggestion.get("reason", "")[:100]
    return f"AI suggestion: {p} {fr}->{to} | reason: {rsn}"


def log_suggestion(
    suggestion: Dict[str, Any],
    *,
    applied: bool,
    snapshot: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Persist a suggestion. Returns the memory id (or None on failure)."""
    mem = get_memory()
    if mem is None:
        return None
    try:
        param = suggestion.get("param", "?")
        meta = {
            "category": "ai_suggestion",
            "param": param,
            "from": suggestion.get("from"),
            "to": suggestion.get("to", suggestion.get("new_value")),
            "direction": _direction(suggestion.get("from"), suggestion.get("to", suggestion.get("new_value"))),
            "regime": (snapshot or {}).get("regime", "unknown"),
            "applied": bool(applied),
            "outcome": "pending",  # set later by evaluate_pending_outcomes
            "outcome_score": None,  # +1 good, -1 bad, 0 neutral
            "snapshot": snapshot or {},
            "logged_at": _now(),
        }
        entry = mem.add(_make_text(suggestion), user_id=USER_ID, metadata=meta)
        return entry.get("id")
    except Exception:
        return None


def search_history_hint(suggestion: Dict[str, Any]) -> Dict[str, Any]:
    """Look up similar prior suggestions and summarise outcomes.

    Returns dict like:
      {"matches": 3, "good": 0, "bad": 2, "pending": 1,
       "advice": "block"|"warn"|"ok",
       "samples": [...top 3 entries...]}
    """
    mem = get_memory()
    if mem is None:
        return {"matches": 0, "advice": "ok", "good": 0, "bad": 0, "pending": 0, "samples": []}
    try:
        param = suggestion.get("param", "")
        direction = _direction(suggestion.get("from"), suggestion.get("to", suggestion.get("new_value")))
        results = mem.search(_make_text(suggestion), user_id=USER_ID, limit=10, category="ai_suggestion")

        relevant = []
        for r in results:
            md = r.get("metadata") or {}
            if md.get("param") != param:
                continue
            if md.get("direction") not in (direction, "set"):
                continue
            if r.get("score", 0) < SIMILAR_THRESHOLD:
                continue
            relevant.append(r)

        good = sum(1 for r in relevant if _score(r.get("metadata") or {}) > 0)
        bad = sum(1 for r in relevant if _score(r.get("metadata") or {}) < 0)
        pending = sum(1 for r in relevant if (r.get("metadata") or {}).get("outcome") == "pending")
        n = len(relevant)

        if n == 0:
            advice = "ok"
        elif bad >= 3 and good == 0:
            advice = "block"
        elif bad > good:
            advice = "warn"
        else:
            advice = "ok"

        return {
            "matches": n,
            "good": good,
            "bad": bad,
            "pending": pending,
            "advice": advice,
            "samples": [
                {
                    "id": r.get("id"),
                    "outcome": (r.get("metadata") or {}).get("outcome"),
                    "outcome_score": (r.get("metadata") or {}).get("outcome_score"),
                    "regime": (r.get("metadata") or {}).get("regime"),
                    "logged_at": (r.get("metadata") or {}).get("logged_at"),
                }
                for r in relevant[:3]
            ],
        }
    except Exception:
        return {"matches": 0, "advice": "ok", "good": 0, "bad": 0, "pending": 0, "samples": []}


def annotate_suggestions(suggestions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach `history_hint` to each suggestion in-place and return the list."""
    if not isinstance(suggestions, list):
        return suggestions
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        try:
            s["history_hint"] = search_history_hint(s)
        except Exception:
            s["history_hint"] = {"matches": 0, "advice": "ok"}
    return suggestions


def evaluate_pending_outcomes(current_pnl_24h_eur: float, current_equity_eur: float) -> Dict[str, int]:
    """Walk all pending suggestions older than PENDING_GRACE_HOURS and assign
    outcome_score based on portfolio movement since logging.

    Heuristic (intentionally crude — better than nothing):
      - applied == True  AND pnl_24h > 0   → +1 (good)
      - applied == True  AND pnl_24h < -1% equity → -1 (bad)
      - applied == False AND no major move → 0 (neutral, inconclusive)
      - older than PENDING_MAX_AGE_HOURS still pending → 0 (inconclusive)
    """
    mem = get_memory()
    if mem is None:
        return {"evaluated": 0, "good": 0, "bad": 0, "neutral": 0}

    counts = {"evaluated": 0, "good": 0, "bad": 0, "neutral": 0}
    now = _now()
    grace_secs = PENDING_GRACE_HOURS * 3600
    max_secs = PENDING_MAX_AGE_HOURS * 3600

    try:
        all_entries = mem.get_all(USER_ID)
        bad_threshold = -0.01 * current_equity_eur if current_equity_eur > 0 else -10.0

        for e in all_entries:
            md = e.get("metadata") or {}
            if md.get("category") != "ai_suggestion":
                continue
            if md.get("outcome") != "pending":
                continue
            age = now - float(md.get("logged_at", now))
            if age < grace_secs:
                continue

            applied = bool(md.get("applied"))
            if not applied:
                # User/auto didn't apply: we can't credit/blame the suggestion
                if age >= max_secs:
                    md["outcome"] = "inconclusive"
                    md["outcome_score"] = 0
                    mem.update(e["id"], e["text"], user_id=USER_ID)
                    counts["neutral"] += 1
                    counts["evaluated"] += 1
                continue

            # Applied: judge by pnl_24h
            if current_pnl_24h_eur > 0:
                md["outcome"] = "good"
                md["outcome_score"] = 1
                counts["good"] += 1
            elif current_pnl_24h_eur < bad_threshold:
                md["outcome"] = "bad"
                md["outcome_score"] = -1
                counts["bad"] += 1
            else:
                md["outcome"] = "neutral"
                md["outcome_score"] = 0
                counts["neutral"] += 1
            mem.update(e["id"], e["text"], user_id=USER_ID)
            counts["evaluated"] += 1
    except Exception:
        pass

    return counts


def stats() -> Dict[str, Any]:
    """Return a summary of supervisor memory contents for dashboard display."""
    mem = get_memory()
    if mem is None:
        return {"total": 0, "good": 0, "bad": 0, "pending": 0, "neutral": 0}
    try:
        entries = [e for e in mem.get_all(USER_ID) if (e.get("metadata") or {}).get("category") == "ai_suggestion"]
        good = sum(1 for e in entries if _score(e.get("metadata") or {}) > 0)
        bad = sum(1 for e in entries if _score(e.get("metadata") or {}) < 0)
        pending = sum(1 for e in entries if (e.get("metadata") or {}).get("outcome") == "pending")
        neutral = sum(1 for e in entries if (e.get("metadata") or {}).get("outcome") in ("neutral", "inconclusive"))
        return {"total": len(entries), "good": good, "bad": bad, "pending": pending, "neutral": neutral}
    except Exception:
        return {"total": 0, "good": 0, "bad": 0, "pending": 0, "neutral": 0}
