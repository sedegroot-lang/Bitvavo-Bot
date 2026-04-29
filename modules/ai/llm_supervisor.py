"""
LLM Supervisor — extra entry-gate naast XGBoost ensemble.

Werkt als pluggable backend:
- Backend "rule" (default fallback): deterministische heuristiek o.b.v.
  RSI / MACD / regime / volatility / volume. Werkt zonder externe deps.
- Backend "ollama": stuurt prompt naar lokale Ollama HTTP API
  (http://localhost:11434) en parseert JSON-respons.

Output is altijd een SupervisorVerdict dataclass:
    {
      "veto": bool,          # True = entry blokkeren
      "confidence": float,   # 0.0..1.0
      "regime": str,         # bull/bear/range/unknown
      "reasoning": str,      # korte uitleg (voor logging/audit)
      "backend": str,        # "rule" of "ollama"
    }

Gebruik:
    from modules.ai.llm_supervisor import evaluate_entry, SupervisorContext

    ctx = SupervisorContext(
        market="SOL-EUR",
        rsi=58.2, macd=-0.04, regime="neutral",
        volatility=0.0028, volume_24h_eur=2_500_000,
        score=12.5,
    )
    v = evaluate_entry(ctx)
    if v.veto:
        log(f"[LLM-supervisor] entry geblokkeerd: {v.reasoning}")
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

# ── Configurable knobs (kunnen via bot_config_local.json worden overschreven) ──
DEFAULT_BACKEND = os.getenv("LLM_SUPERVISOR_BACKEND", "rule")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "10"))

LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "llm_supervisor_log.jsonl"


@dataclass(slots=True)
class SupervisorContext:
    market: str
    rsi: float = 50.0
    macd: float = 0.0
    regime: str = "unknown"
    volatility: float = 0.0
    volume_24h_eur: float = 0.0
    score: float = 0.0
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SupervisorVerdict:
    veto: bool
    confidence: float
    regime: str
    reasoning: str
    backend: str
    latency_ms: float = 0.0


# ─── Rule-based backend (always available) ───────────────────────────────
def _rule_backend(ctx: SupervisorContext) -> SupervisorVerdict:
    """
    Heuristiek getuned op observatie van 868 closed trades:
    - 148 stop-loss verliezen kwamen vaak bij high-RSI + bearish MACD entries.
    - 'unknown' regime had hogere loss-rate dan 'neutral'.
    Deze rules zijn een conservatieve veto-laag (precision > recall):
      * Veto only when meerdere signalen samen wijzen op risk.
    """
    reasons = []
    risk_score = 0.0

    # CORE RULE (uit threshold-sweep over 57 historical trades met features):
    #   "marginale score AND RSI in [52,60]" → +€6.31 (+12.5%) delta vs baseline.
    #   Reden: dit zijn lage-conviction entries in RSI-danger-zone waar
    #   alle 5 historische verliezers in vielen.
    # FIX (29-04-2026): drempel was hardcoded op 14, terwijl effectieve
    #   entry-drempel adaptief is (~8). Score 12.9 = HOGE conviction maar werd
    #   ten onrechte als "low" gelabeld. Nu absoluut + configureerbaar.
    #   Default cutoff = 11.0: alles boven 11 is conviction, alleen 0..11
    #   wordt als marginaal beschouwd in de RSI danger-zone.
    try:
        from modules.config import CONFIG as _CFG
        _low_cutoff = float(_CFG.get("LLM_SUP_LOW_SCORE_CUTOFF", 11.0))
    except Exception:
        _low_cutoff = 11.0
    if 0 < ctx.score < _low_cutoff and 52 <= ctx.rsi <= 60:
        reasons.append(
            f"marginal score {ctx.score:.1f} (<{_low_cutoff:.1f}) + RSI {ctx.rsi:.1f} danger-zone"
        )
        risk_score += 0.55  # auto-veto

    # Aanvullende risk-bumpers (kunnen veto triggeren bij combinaties):
    if ctx.rsi >= 70:
        reasons.append(f"RSI {ctx.rsi:.1f} extreme overbought")
        risk_score += 0.40

    if ctx.macd < -0.10:
        reasons.append(f"MACD {ctx.macd:+.3f} strongly bearish")
        risk_score += 0.30

    if ctx.regime == "bearish":
        reasons.append("regime=bearish")
        risk_score += 0.25

    if ctx.volume_24h_eur and ctx.volume_24h_eur < 250_000:
        reasons.append(f"very low liquidity €{ctx.volume_24h_eur:,.0f}")
        risk_score += 0.30

    veto = risk_score >= 0.50
    confidence = min(0.95, max(0.05, risk_score))
    derived_regime = ctx.regime if ctx.regime != "unknown" else (
        "bearish" if ctx.macd < 0 else "bullish" if ctx.macd > 0.05 else "range"
    )
    reasoning = "; ".join(reasons) if reasons else "no risk signals"
    return SupervisorVerdict(
        veto=veto,
        confidence=confidence,
        regime=derived_regime,
        reasoning=reasoning,
        backend="rule",
    )


# ─── Ollama backend (optional, requires local Ollama) ────────────────────
def _build_ollama_prompt(ctx: SupervisorContext) -> str:
    return f"""You are a crypto trading risk supervisor. Decide if a buy-entry
should be VETOED (too risky) or APPROVED.

Market: {ctx.market}
Current indicators:
- RSI(14): {ctx.rsi:.2f}
- MACD: {ctx.macd:+.4f}
- Regime: {ctx.regime}
- Volatility: {ctx.volatility:.4f}
- 24h volume EUR: {ctx.volume_24h_eur:,.0f}
- XGBoost ensemble score: {ctx.score:.2f}

Reply ONLY with valid JSON, no prose:
{{"veto": true|false, "confidence": 0.0-1.0, "regime": "bull|bear|range|unknown", "reasoning": "<one sentence>"}}
"""


def _ollama_backend(ctx: SupervisorContext) -> Optional[SupervisorVerdict]:
    try:
        import requests
    except ImportError:
        return None
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": _build_ollama_prompt(ctx),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2, "num_predict": 200},
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=OLLAMA_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        raw = data.get("response", "{}")
        parsed = json.loads(raw)
        return SupervisorVerdict(
            veto=bool(parsed.get("veto", False)),
            confidence=float(parsed.get("confidence", 0.5)),
            regime=str(parsed.get("regime", "unknown")),
            reasoning=str(parsed.get("reasoning", ""))[:300],
            backend="ollama",
        )
    except Exception as e:
        # Fail-open: bij Ollama-storing geen veto, return None zodat caller fallback doet
        return None


# ─── Public API ──────────────────────────────────────────────────────────
def evaluate_entry(ctx: SupervisorContext, backend: Optional[str] = None) -> SupervisorVerdict:
    """Hoofdfunctie. Probeert configured backend, valt terug op 'rule' bij fout."""
    backend = (backend or DEFAULT_BACKEND).lower()
    t0 = time.perf_counter()
    verdict: Optional[SupervisorVerdict] = None

    if backend == "ollama":
        verdict = _ollama_backend(ctx)

    if verdict is None:
        verdict = _rule_backend(ctx)

    verdict.latency_ms = (time.perf_counter() - t0) * 1000.0

    # Audit log (best-effort, never raises)
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            entry = {
                "ts": time.time(),
                "ctx": asdict(ctx),
                "verdict": asdict(verdict),
            }
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass

    return verdict


__all__ = ["SupervisorContext", "SupervisorVerdict", "evaluate_entry"]
