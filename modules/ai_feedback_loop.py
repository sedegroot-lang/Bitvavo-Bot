# ai_feedback_loop.py
"""
Self-Learning Feedback Loop Module
Tracks which AI suggestions actually improve performance and learns from outcomes
"""

import json

# Project imports
import sys
import time
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.json_compat import write_json_compat
from modules.logging_utils import log

# Data paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FEEDBACK_FILE = PROJECT_ROOT / "data" / "ai_feedback_loop.json"
AI_CHANGES_FILE = PROJECT_ROOT / "data" / "ai_changes.json"
TRADE_LOG_FILE = PROJECT_ROOT / "data" / "trade_log.json"
CONFIG_FILE = PROJECT_ROOT / "config" / "bot_config.json"


def _load_feedback() -> dict:
    """Load feedback data from disk."""
    try:
        if FEEDBACK_FILE.exists():
            with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "suggestion_outcomes": [],
        "parameter_effectiveness": {},
        "learning_weights": {},
        "version": 2,
        "created_at": time.time(),
    }


def _save_feedback(data: dict):
    """Save feedback data to disk."""
    try:
        FEEDBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        write_json_compat(str(FEEDBACK_FILE), data)
    except Exception as e:
        log(f"[FEEDBACK] Save error: {e}", level="warning")


def _load_ai_changes() -> List[dict]:
    """Load AI change history."""
    try:
        if AI_CHANGES_FILE.exists():
            with open(AI_CHANGES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def _load_trades() -> List[dict]:
    """Load closed trades from trade log."""
    try:
        if TRADE_LOG_FILE.exists():
            with open(TRADE_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data.get("closed", [])
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def record_suggestion_outcome(
    param: str,
    from_value: float,
    to_value: float,
    reason: str,
    trades_before: int,
    pnl_before: float,
    win_rate_before: float,
):
    """
    Record a suggestion application for later evaluation.
    Called when AI applies a suggestion.
    """
    feedback = _load_feedback()

    outcome = {
        "param": param,
        "from_value": from_value,
        "to_value": to_value,
        "reason": reason,
        "applied_at": time.time(),
        "trades_before": trades_before,
        "pnl_before": pnl_before,
        "win_rate_before": win_rate_before,
        "evaluated": False,
        "outcome": None,
    }

    feedback["suggestion_outcomes"].append(outcome)

    # Keep last 200 outcomes
    feedback["suggestion_outcomes"] = feedback["suggestion_outcomes"][-200:]

    _save_feedback(feedback)
    log(f"[FEEDBACK] Recorded suggestion: {param} {from_value} → {to_value}", level="debug")


def evaluate_pending_suggestions():
    """
    Evaluate suggestions that were applied and have enough trades after.
    Requires at least 10 trades after the change to evaluate.
    """
    feedback = _load_feedback()
    trades = _load_trades()

    if len(trades) < 10:
        return {"evaluated": 0, "message": "Not enough trades"}

    evaluated_count = 0

    for outcome in feedback["suggestion_outcomes"]:
        if outcome.get("evaluated"):
            continue

        applied_at = outcome.get("applied_at", 0)
        trades_before = outcome.get("trades_before", 0)

        # Find trades after the change was applied
        trades_after = [t for t in trades if t.get("close_time", t.get("sell_time", 0)) > applied_at]

        if len(trades_after) < 10:
            continue  # Not enough data yet

        # Calculate metrics after the change
        trades_after = trades_after[:20]  # Use first 20 trades after change
        pnl_after = sum(t.get("profit", t.get("pnl", 0)) for t in trades_after)
        wins_after = sum(1 for t in trades_after if t.get("profit", t.get("pnl", 0)) > 0)
        win_rate_after = wins_after / len(trades_after)

        # Compare with before
        pnl_improvement = pnl_after - (outcome.get("pnl_before", 0) or 0)
        wr_improvement = win_rate_after - (outcome.get("win_rate_before", 0.5) or 0.5)

        # Determine if the suggestion was positive, negative, or neutral
        if pnl_improvement > 5 and wr_improvement > 0.05:
            verdict = "POSITIVE"
            score = 1.0
        elif pnl_improvement < -5 or wr_improvement < -0.1:
            verdict = "NEGATIVE"
            score = -1.0
        elif pnl_improvement > 0 or wr_improvement > 0:
            verdict = "SLIGHTLY_POSITIVE"
            score = 0.3
        elif pnl_improvement < 0 or wr_improvement < 0:
            verdict = "SLIGHTLY_NEGATIVE"
            score = -0.3
        else:
            verdict = "NEUTRAL"
            score = 0.0

        outcome["evaluated"] = True
        outcome["outcome"] = {
            "verdict": verdict,
            "score": score,
            "pnl_after": round(pnl_after, 2),
            "win_rate_after": round(win_rate_after, 3),
            "pnl_improvement": round(pnl_improvement, 2),
            "wr_improvement": round(wr_improvement, 3),
            "trades_evaluated": len(trades_after),
            "evaluated_at": time.time(),
        }

        evaluated_count += 1

        # Update parameter effectiveness
        param = outcome["param"]
        if param not in feedback["parameter_effectiveness"]:
            feedback["parameter_effectiveness"][param] = {
                "total_suggestions": 0,
                "positive": 0,
                "negative": 0,
                "neutral": 0,
                "total_score": 0,
                "avg_pnl_impact": 0,
            }

        eff = feedback["parameter_effectiveness"][param]
        eff["total_suggestions"] += 1
        eff["total_score"] += score

        if verdict in ["POSITIVE", "SLIGHTLY_POSITIVE"]:
            eff["positive"] += 1
        elif verdict in ["NEGATIVE", "SLIGHTLY_NEGATIVE"]:
            eff["negative"] += 1
        else:
            eff["neutral"] += 1

        # Rolling average PnL impact
        eff["avg_pnl_impact"] = (eff["avg_pnl_impact"] * (eff["total_suggestions"] - 1) + pnl_improvement) / eff[
            "total_suggestions"
        ]

        log(
            f"[FEEDBACK] Evaluated {param}: {verdict} (PnL: {pnl_improvement:+.2f}€, WR: {wr_improvement:+.1%})",
            level="info" if verdict.startswith("POSITIVE") else "warning",
        )

    _save_feedback(feedback)

    return {
        "evaluated": evaluated_count,
        "pending": sum(1 for o in feedback["suggestion_outcomes"] if not o.get("evaluated")),
    }


def get_parameter_effectiveness() -> dict:
    """
    Get effectiveness scores for each parameter the AI has adjusted.
    """
    feedback = _load_feedback()
    effectiveness = feedback.get("parameter_effectiveness", {})

    # Calculate success rate for each parameter
    results = {}
    for param, data in effectiveness.items():
        total = data.get("total_suggestions", 0)
        if total == 0:
            continue

        positive = data.get("positive", 0)
        negative = data.get("negative", 0)

        success_rate = positive / total if total > 0 else 0
        avg_score = data.get("total_score", 0) / total if total > 0 else 0

        results[param] = {
            "success_rate": round(success_rate, 3),
            "avg_score": round(avg_score, 3),
            "avg_pnl_impact": round(data.get("avg_pnl_impact", 0), 2),
            "total_suggestions": total,
            "positive": positive,
            "negative": negative,
            "neutral": data.get("neutral", 0),
            "recommendation": "TRUST" if success_rate > 0.6 else ("CAUTION" if success_rate > 0.4 else "DISTRUST"),
        }

    # Sort by success rate
    sorted_results = dict(sorted(results.items(), key=lambda x: x[1]["success_rate"], reverse=True))

    return {
        "parameters": sorted_results,
        "most_effective": [p for p, d in sorted_results.items() if d["recommendation"] == "TRUST"][:5],
        "least_effective": [p for p, d in sorted_results.items() if d["recommendation"] == "DISTRUST"],
        "timestamp": time.time(),
    }


def calculate_learning_weights() -> dict:
    """
    Calculate weights for each parameter based on historical effectiveness.
    These weights can be used to boost or suppress AI suggestions.
    """
    effectiveness = get_parameter_effectiveness()

    if not effectiveness.get("parameters"):
        return {"weights": {}, "message": "No effectiveness data yet"}

    weights = {}

    for param, data in effectiveness["parameters"].items():
        # Weight based on success rate and sample size
        base_weight = data["success_rate"] * 2 - 1  # Scale to -1 to 1

        # Confidence based on sample size (more samples = more confident)
        confidence = min(1.0, data["total_suggestions"] / 10)

        # Final weight = base_weight * confidence
        final_weight = base_weight * confidence

        weights[param] = {
            "weight": round(final_weight, 3),
            "confidence": round(confidence, 3),
            "should_suggest": final_weight > -0.3,  # Don't suggest if historically bad
            "boost_factor": max(0.5, min(1.5, 1 + final_weight)),  # 0.5x to 1.5x
        }

    # Save weights
    feedback = _load_feedback()
    feedback["learning_weights"] = weights
    _save_feedback(feedback)

    return {"weights": weights, "timestamp": time.time()}


def should_apply_suggestion(param: str, confidence: float = 0.5) -> dict:
    """
    Determine if a suggestion for a parameter should be applied
    based on historical effectiveness.

    Returns:
        dict with decision and reasoning
    """
    feedback = _load_feedback()
    weights = feedback.get("learning_weights", {})

    if param not in weights:
        # No historical data, allow with default confidence
        return {
            "should_apply": True,
            "confidence": confidence,
            "reason": "No historical data - using default",
            "boost_factor": 1.0,
        }

    weight_data = weights[param]

    # Check if historically effective
    if not weight_data.get("should_suggest", True):
        return {
            "should_apply": False,
            "confidence": weight_data.get("confidence", 0.5),
            "reason": f"Parameter {param} historically ineffective (weight: {weight_data['weight']:.2f})",
            "boost_factor": weight_data.get("boost_factor", 1.0),
        }

    # Apply with adjusted confidence
    adjusted_confidence = confidence * weight_data.get("boost_factor", 1.0)

    return {
        "should_apply": True,
        "confidence": min(1.0, adjusted_confidence),
        "reason": f"Historical effectiveness: {weight_data['weight']:.2f}",
        "boost_factor": weight_data.get("boost_factor", 1.0),
        "historical_success_rate": feedback.get("parameter_effectiveness", {}).get(param, {}).get("success_rate", 0.5),
    }


def get_ai_performance_summary() -> dict:
    """
    Get overall AI performance summary.
    """
    feedback = _load_feedback()
    outcomes = feedback.get("suggestion_outcomes", [])

    # Count evaluated outcomes
    evaluated = [o for o in outcomes if o.get("evaluated")]

    if not evaluated:
        return {
            "message": "No evaluated suggestions yet",
            "total_suggestions": len(outcomes),
            "pending_evaluation": len(outcomes),
        }

    # Calculate overall stats
    positive = sum(1 for o in evaluated if o.get("outcome", {}).get("verdict", "").startswith("POSITIVE"))
    negative = sum(1 for o in evaluated if o.get("outcome", {}).get("verdict", "").startswith("NEGATIVE"))

    total_pnl_impact = sum(o.get("outcome", {}).get("pnl_improvement", 0) for o in evaluated)
    avg_pnl_impact = total_pnl_impact / len(evaluated)

    overall_success_rate = positive / len(evaluated)

    return {
        "total_suggestions_applied": len(outcomes),
        "evaluated": len(evaluated),
        "pending_evaluation": len(outcomes) - len(evaluated),
        "positive_outcomes": positive,
        "negative_outcomes": negative,
        "neutral_outcomes": len(evaluated) - positive - negative,
        "overall_success_rate": round(overall_success_rate, 3),
        "total_pnl_impact": round(total_pnl_impact, 2),
        "avg_pnl_impact": round(avg_pnl_impact, 2),
        "ai_quality": "EXCELLENT"
        if overall_success_rate > 0.7
        else (
            "GOOD"
            if overall_success_rate > 0.55
            else ("MODERATE" if overall_success_rate > 0.45 else "NEEDS_IMPROVEMENT")
        ),
        "timestamp": time.time(),
    }


def run_feedback_cycle():
    """
    Run a complete feedback cycle:
    1. Evaluate pending suggestions
    2. Update learning weights
    3. Return summary
    """
    log("[FEEDBACK] Running feedback cycle...", level="info")

    # Evaluate any pending suggestions
    eval_result = evaluate_pending_suggestions()

    # Update learning weights
    weights = calculate_learning_weights()

    # Get performance summary
    summary = get_ai_performance_summary()

    log(
        f"[FEEDBACK] Cycle complete: {eval_result['evaluated']} evaluated, "
        f"success rate: {summary.get('overall_success_rate', 0):.1%}",
        level="info",
    )

    return {"evaluation": eval_result, "weights": weights, "summary": summary, "timestamp": time.time()}


# Integration function for AI supervisor
def get_feedback_adjusted_confidence(param: str, base_confidence: float) -> float:
    """
    Adjust AI suggestion confidence based on historical feedback.
    """
    decision = should_apply_suggestion(param, base_confidence)

    if not decision["should_apply"]:
        return 0.0  # Suppress this suggestion

    return decision["confidence"]


def register_ai_change(change: dict):
    """
    Called when AI applies a change - registers it for feedback tracking.
    """
    trades = _load_trades()

    # Calculate current metrics
    recent_trades = trades[-20:] if len(trades) >= 20 else trades
    if recent_trades:
        total_pnl = sum(t.get("profit", t.get("pnl", 0)) for t in recent_trades)
        wins = sum(1 for t in recent_trades if t.get("profit", t.get("pnl", 0)) > 0)
        win_rate = wins / len(recent_trades)
    else:
        total_pnl = 0
        win_rate = 0.5

    record_suggestion_outcome(
        param=change.get("param", "unknown"),
        from_value=change.get("from", 0),
        to_value=change.get("to", 0),
        reason=change.get("reason", ""),
        trades_before=len(trades),
        pnl_before=total_pnl,
        win_rate_before=win_rate,
    )


if __name__ == "__main__":
    print("=== AI Feedback Loop Analysis ===\n")

    # Run feedback cycle
    result = run_feedback_cycle()

    print("--- Evaluation ---")
    print(f"  Evaluated: {result['evaluation']['evaluated']}")
    print(f"  Pending: {result['evaluation'].get('pending', 0)}")

    print("\n--- AI Performance Summary ---")
    summary = result["summary"]
    if "message" not in summary:
        print(f"  Success Rate: {summary['overall_success_rate']:.1%}")
        print(f"  Total PnL Impact: €{summary['total_pnl_impact']:.2f}")
        print(f"  AI Quality: {summary['ai_quality']}")
        print(f"  Positive/Negative: {summary['positive_outcomes']}/{summary['negative_outcomes']}")
    else:
        print(f"  {summary['message']}")

    print("\n--- Parameter Effectiveness ---")
    effectiveness = get_parameter_effectiveness()
    for param, data in list(effectiveness.get("parameters", {}).items())[:5]:
        print(
            f"  {param}: {data['success_rate']:.1%} success, €{data['avg_pnl_impact']:.2f} avg impact - {data['recommendation']}"
        )

    print("\n--- Learning Weights ---")
    weights = result.get("weights", {}).get("weights", {})
    for param, data in list(weights.items())[:5]:
        emoji = "✅" if data["should_suggest"] else "❌"
        print(f"  {emoji} {param}: weight={data['weight']:+.2f}, boost={data['boost_factor']:.2f}x")
