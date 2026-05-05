import json
import math
import os
import time
from typing import Dict, List, Optional, Tuple

from modules.logging_utils import log

try:
    import xgboost as xgb  # optional
except Exception:
    xgb = None

import numpy as np
from dotenv import load_dotenv
from python_bitvavo_api.bitvavo import Bitvavo

FEATURE_NAMES = [
    "rsi14",
    "macd_hist",
    "bb_width",
    "atr_pct",
    "ret_5",
    "ret_15",
    "slope_30",
    "volume_ratio",
    "volume_trend",
    "spread_pct",
    "liquidity_score",
]


class AIEngine:
    """
    Advanced AI helper providing:
    - Market data fetch (candles)
    - Feature extraction (RSI, MACD, BB width, ATR%, momentum, volume ratio)
    - Simple market regime classification (bull/bear/chop)
    - Optional XGBoost-based market scoring if model is available
    - Parameter recommendations based on regime and volatility
    - Portfolio optimization (NEW): balance tracking, position sizing, risk management
    """

    def __init__(self, config_path: str = None, model_path: str = None):
        self.config_path = config_path or os.path.join("config", "bot_config.json")
        self.model_path = model_path or os.path.join("ai", "ai_xgb_model.json")
        self._cfg = self._load_json(self.config_path, {})
        load_dotenv()
        self._bv = Bitvavo({"APIKEY": os.getenv("BITVAVO_API_KEY"), "APISECRET": os.getenv("BITVAVO_API_SECRET")})
        self._model = None
        if xgb is not None:
            try:
                if os.path.exists(self.model_path):
                    m = xgb.XGBClassifier()
                    m.load_model(self.model_path)
                    self._model = m
                    log(f"AIEngine: geladen XGBoost model uit {self.model_path}")
            except Exception as e:
                log(f"AIEngine: laden model mislukt: {e}", level="warning")

    @staticmethod
    def _load_json(path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _safe_call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            # one quick retry
            time.sleep(0.3)
            try:
                return fn(*args, **kwargs)
            except Exception as e2:
                log(f"AIEngine API fout: {e2}", level="warning")
                return None

    def get_whitelist(self) -> List[str]:
        wl = self._cfg.get("WHITELIST_MARKETS", [])
        if isinstance(wl, list):
            return [m for m in wl if isinstance(m, str) and m.endswith("-EUR")]
        return []

    def candles(self, market: str, interval="1m", limit=180) -> List[List]:
        c = self._safe_call(self._bv.candles, market, interval, {"limit": limit}) or []
        return c

    @staticmethod
    def _closes(candles: List[List]) -> List[float]:
        vals = []
        for x in candles or []:
            try:
                if len(x) > 4:
                    vals.append(float(x[4]))
            except Exception:
                continue
        return vals

    @staticmethod
    def _highs(candles: List[List]) -> List[float]:
        return [float(x[2]) for x in candles if len(x) > 2]

    @staticmethod
    def _lows(candles: List[List]) -> List[float]:
        return [float(x[3]) for x in candles if len(x) > 3]

    @staticmethod
    def _volumes(candles: List[List]) -> List[float]:
        vols = []
        for x in candles or []:
            try:
                vols.append(float(x[5]))
            except Exception:
                continue
        return vols

    @staticmethod
    def sma(vals: List[float], w: int) -> Optional[float]:
        return float(np.mean(vals[-w:])) if len(vals) >= w else None

    @staticmethod
    def rsi(vals: List[float], period: int = 14) -> Optional[float]:
        if len(vals) < period + 1:
            return None
        deltas = np.diff(vals)
        gains = deltas[deltas > 0].sum() / period
        losses = -deltas[deltas < 0].sum() / period
        if losses == 0:
            return 100.0
        rs = gains / losses
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(
        vals: List[float], fast: int = 12, slow: int = 26, signal: int = 9
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        if len(vals) < slow + signal:
            return None, None, None

        def ema(v, n):
            k = 2 / (n + 1)
            e = [v[0]]
            for x in v[1:]:
                e.append(x * k + e[-1] * (1 - k))
            return e

        ef, es = ema(vals, fast), ema(vals, slow)
        macd_line = [f - s for f, s in zip(ef[-len(es) :], es)]
        sig = ema(macd_line, signal)
        return macd_line[-1], sig[-1], macd_line[-1] - sig[-1]

    @staticmethod
    def atr(h: List[float], l: List[float], c: List[float], window: int = 14) -> Optional[float]:
        if len(h) < window + 1:
            return None
        trs = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
        return float(np.mean(trs[-window:]))

    def extract_features(self, market: str, interval="1m", limit=180) -> Optional[Dict[str, float]]:
        c = self.candles(market, interval, limit)
        return self.compute_features_from_candles(c)

    def compute_features_from_candles(self, candles: List[List]) -> Optional[Dict[str, float]]:
        if not candles:
            return None
        closes = self._closes(candles)
        if len(closes) < 60:
            return None
        highs = self._highs(candles)
        lows = self._lows(candles)
        volumes = self._volumes(candles)
        rsi14 = self.rsi(closes, 14) or 0.0
        macd_line, macd_sig, macd_hist = self.macd(closes)
        macd_hist = macd_hist if macd_hist is not None else 0.0
        bb_w = 0.0
        try:
            w = 20
            ma = np.mean(closes[-w:])
            std = np.std(closes[-w:])
            bb_w = float(2 * std / ma) if ma else 0.0
        except Exception:
            bb_w = 0.0
        atr_val = self.atr(highs, lows, closes, 14) or 0.0
        atr_pct = float(atr_val / closes[-1]) if closes[-1] else 0.0
        ret_5 = float((closes[-1] / closes[-6] - 1) if len(closes) >= 6 else 0.0)
        ret_15 = float((closes[-1] / closes[-16] - 1) if len(closes) >= 16 else 0.0)
        slope_30 = 0.0
        try:
            y = np.array(closes[-30:])
            x = np.arange(len(y))
            m, _ = np.polyfit(x, y, 1)
            slope_30 = float(m / (y.mean() or 1.0))
        except Exception:
            slope_30 = 0.0

        volume_ratio = 1.0
        volume_trend = 0.0
        liquidity_score = 0.0
        spread_pct = 0.0
        try:
            if len(volumes) >= 30:
                recent_vol = np.mean(volumes[-5:]) if len(volumes) >= 5 else np.mean(volumes[-30:])
                base_vol = np.mean(volumes[-30:])
                volume_ratio = float((recent_vol + 1e-8) / (base_vol + 1e-8))
                mid_vol_window = volumes[-30:-5] if len(volumes) >= 35 else volumes[:-5]
                prev_avg = np.mean(mid_vol_window) if len(mid_vol_window) else base_vol
                volume_trend = float((recent_vol - prev_avg) / (base_vol + 1e-8))
                avg_quote_vol = float(base_vol * closes[-1])
                liquidity_score = float(math.log1p(max(avg_quote_vol, 0.0)))
            spreads = []
            span = min(len(highs), len(lows), len(closes))
            for idx in range(max(0, span - 10), span):
                c = closes[idx]
                if c:
                    spreads.append((highs[idx] - lows[idx]) / c)
            if spreads:
                spread_pct = float(np.mean(spreads))
        except Exception:
            volume_ratio = 1.0
            volume_trend = 0.0
            liquidity_score = 0.0
            spread_pct = 0.0
        return {
            "rsi14": float(rsi14),
            "macd_hist": float(macd_hist),
            "bb_width": float(bb_w),
            "atr_pct": float(atr_pct),
            "ret_5": float(ret_5),
            "ret_15": float(ret_15),
            "slope_30": float(slope_30),
            "volume_ratio": float(volume_ratio),
            "volume_trend": float(volume_trend),
            "spread_pct": float(spread_pct),
            "liquidity_score": float(liquidity_score),
        }

    def classify_regime(self, sample_markets: Optional[List[str]] = None) -> Tuple[str, Dict[str, float]]:
        markets = sample_markets or self.get_whitelist()[:10]
        if not markets:
            return "unknown", {}
        feats = []
        for m in markets:
            f = self.extract_features(m)
            if f:
                feats.append(f)
        if not feats:
            return "unknown", {}
        avg_rsi = float(np.mean([f["rsi14"] for f in feats]))
        avg_ret15 = float(np.mean([f["ret_15"] for f in feats]))
        avg_vol = float(np.mean([f["atr_pct"] for f in feats]))
        # Simple rules for regime
        if avg_rsi >= 55 and avg_ret15 > 0.01:
            regime = "bull"
        elif avg_rsi <= 45 and avg_ret15 < -0.01:
            regime = "bear"
        else:
            regime = "chop"
        return regime, {"avg_rsi": avg_rsi, "avg_ret15": avg_ret15, "avg_vol": avg_vol}

    def score_markets(self, markets: Optional[List[str]] = None) -> List[Dict[str, object]]:
        markets = markets or self.get_whitelist()[:10]
        scores = []
        for m in markets:
            f = self.extract_features(m)
            if not f:
                continue
            if self._model is not None:
                try:
                    arr = np.array([[f[name] for name in FEATURE_NAMES]], dtype=float)
                    probas = self._model.predict_proba(arr)[0][1]
                    p = float(probas)
                    factors = self._explain(arr)
                except Exception:
                    p = 0.0
                    factors = []
            else:
                # heuristic score
                p = 0.0
                p += max(0.0, (f["rsi14"] - 40) / 60)  # higher RSI helps up to a point
                p += max(0.0, f["ret_15"] * 5)
                p += max(0.0, f["slope_30"] * 10)
                p -= max(0.0, (f["atr_pct"] - 0.02) * 10)  # penalize high vol
                p += max(0.0, (f["volume_ratio"] - 1.0) * 2)
                p += max(0.0, f["volume_trend"] * 5)
                p -= max(0.0, (f["spread_pct"] - 0.004) * 50)
                p += max(0.0, (f["liquidity_score"] - 9.0) * 0.5)
                p = float(1 / (1 + np.exp(-p)))  # squashed
                factors = sorted(
                    [
                        {"feature": "rsi14", "impact": round((f["rsi14"] - 50) / 50, 3)},
                        {"feature": "ret_15", "impact": round(f["ret_15"], 3)},
                        {"feature": "slope_30", "impact": round(f["slope_30"], 3)},
                        {"feature": "atr_pct", "impact": round(-f["atr_pct"], 3)},
                        {"feature": "volume_ratio", "impact": round(f["volume_ratio"] - 1.0, 3)},
                        {"feature": "volume_trend", "impact": round(f["volume_trend"], 3)},
                        {"feature": "spread_pct", "impact": round(-f["spread_pct"], 3)},
                        {"feature": "liquidity_score", "impact": round(f["liquidity_score"] - 9.0, 3)},
                    ],
                    key=lambda item: abs(item["impact"]),
                    reverse=True,
                )[:3]
            # optional filtering for illiquid markets or wide spreads
            if f.get("liquidity_score", 0.0) < 7.5 or f.get("spread_pct", 0.0) > 0.015:
                factors.append({"feature": "filter", "impact": -1.0, "reason": "low liquidity or wide spread"})
                p *= 0.5
            scores.append(
                {
                    "market": m,
                    "score": p,
                    "factors": factors,
                    "spread_pct": round(float(f.get("spread_pct", 0.0)), 5),
                    "liquidity_score": round(float(f.get("liquidity_score", 0.0)), 3),
                    "volume_ratio": round(float(f.get("volume_ratio", 0.0)), 3),
                    "volume_trend": round(float(f.get("volume_trend", 0.0)), 3),
                }
            )
        return sorted(scores, key=lambda x: x["score"], reverse=True)

    def _explain(self, features: np.ndarray) -> List[Dict[str, object]]:
        if self._model is None or xgb is None:
            return []
        try:
            booster = self._model.get_booster()
            dmat = xgb.DMatrix(features, feature_names=booster.feature_names)
            contribs = booster.predict(dmat, pred_contribs=True)[0]
            # last entry is bias term, ignore
            feature_contribs = []
            for idx, val in enumerate(contribs[:-1]):
                name = FEATURE_NAMES[idx] if idx < len(FEATURE_NAMES) else booster.feature_names[idx]
                feature_contribs.append({"feature": name, "impact": float(val)})
            feature_contribs.sort(key=lambda item: abs(item["impact"]), reverse=True)
            return feature_contribs[:3]
        except Exception as exc:
            log(f"AIEngine explainability failed: {exc}", level="warning")
            return []

    def recommend_params(self, cfg: Dict, hb: Dict, trades: List[Dict]) -> Dict[str, object]:
        """Return structured recommendations including parameter adjustments, market insights, and regime stats."""
        recs: List[Dict[str, object]] = []
        regime, stats = self.classify_regime()
        avg_vol = stats.get("avg_vol", 0.02)
        # Current settings snapshot
        default_trailing = float(cfg.get("DEFAULT_TRAILING", 0.012))
        trailing_activation = float(cfg.get("TRAILING_ACTIVATION_PCT", 0.025))
        rsi_min_buy = float(cfg.get("RSI_MIN_BUY", 30))
        base_amount = float(cfg.get("BASE_AMOUNT_EUR", 15))
        dca_mult = float(cfg.get("DCA_SIZE_MULTIPLIER", 1.0))

        exposure = float(hb.get("open_exposure_eur", 0.0) or 0.0)
        max_total = float(cfg.get("MAX_TOTAL_EXPOSURE_EUR", 0.0) or 0.0)
        exposure_ratio = (exposure / max_total) if max_total else 0.0

        if regime == "bull":
            recs.append(
                {
                    "param": "TRAILING_ACTIVATION_PCT",
                    "from": trailing_activation,
                    "to": max(0.01, trailing_activation - 0.003),
                    "reason": "bull regime: activate sooner",
                }
            )
            recs.append(
                {
                    "param": "RSI_MIN_BUY",
                    "from": rsi_min_buy,
                    "to": rsi_min_buy - 1,
                    "reason": "bull regime: slightly more aggressive",
                }
            )
            recs.append(
                {
                    "param": "BASE_AMOUNT_EUR",
                    "from": base_amount,
                    "to": min(100.0, base_amount + 2.0),
                    "reason": "bull regime: scale in a bit",
                }
            )
        elif regime == "bear":
            recs.append(
                {
                    "param": "DEFAULT_TRAILING",
                    "from": default_trailing,
                    "to": default_trailing + 0.002,
                    "reason": "bear regime: tighter trailing",
                }
            )
            if exposure_ratio >= 0.7:
                recs.append(
                    {
                        "param": "RSI_MIN_BUY",
                        "from": rsi_min_buy,
                        "to": rsi_min_buy + 3,
                        "reason": "bear regime & high exposure: tighten entries",
                    }
                )
                recs.append(
                    {
                        "param": "BASE_AMOUNT_EUR",
                        "from": base_amount,
                        "to": max(5.0, base_amount - 3.0),
                        "reason": "bear regime & high exposure: cut size",
                    }
                )
                cooldown = int(cfg.get("OPEN_TRADE_COOLDOWN_SECONDS", 0) or 0)
                target_cooldown = max(cooldown, 900)
                recs.append(
                    {
                        "param": "OPEN_TRADE_COOLDOWN_SECONDS",
                        "from": cooldown,
                        "to": min(3600, target_cooldown),
                        "reason": "bear regime & high exposure: pause new trades",
                    }
                )
            else:
                recs.append(
                    {
                        "param": "RSI_MIN_BUY",
                        "from": rsi_min_buy,
                        "to": rsi_min_buy + 2,
                        "reason": "bear regime: avoid weak momentum",
                    }
                )
                recs.append(
                    {
                        "param": "BASE_AMOUNT_EUR",
                        "from": base_amount,
                        "to": max(5.0, base_amount - 2.0),
                        "reason": "bear regime: reduce risk",
                    }
                )
        else:  # chop
            recs.append(
                {
                    "param": "TRAILING_ACTIVATION_PCT",
                    "from": trailing_activation,
                    "to": trailing_activation,
                    "reason": "chop regime: steady",
                }
            )

        if avg_vol >= 0.03:
            recs.append(
                {
                    "param": "DCA_SIZE_MULTIPLIER",
                    "from": dca_mult,
                    "to": max(0.5, dca_mult - 0.05),
                    "reason": "high volatility: reduce DCA size",
                }
            )
        elif avg_vol <= 0.015:
            recs.append(
                {
                    "param": "DCA_SIZE_MULTIPLIER",
                    "from": dca_mult,
                    "to": min(1.5, dca_mult + 0.05),
                    "reason": "low volatility: slightly increase DCA size",
                }
            )

        insights: List[Dict[str, object]] = []
        try:
            top = self.score_markets(self.get_whitelist()[:10])[:5]
            insights = [
                {
                    "market": item.get("market"),
                    "score": round(float(item.get("score", 0.0)), 3),
                    "factors": item.get("factors", []),
                    "spread_pct": item.get("spread_pct"),
                    "liquidity_score": item.get("liquidity_score"),
                    "volume_ratio": item.get("volume_ratio"),
                    "volume_trend": item.get("volume_trend"),
                }
                for item in top
            ]
        except Exception:
            insights = []

        return {"suggestions": recs, "insights": insights, "regime": regime, "regime_stats": stats}

    def get_portfolio_status(self) -> Dict[str, object]:
        """Get complete portfolio overview: balance, positions, allocation."""
        try:
            balance = self._safe_call(self._bv.balance, {})
            if not balance:
                return {"error": "Could not fetch balance"}

            total_eur = 0.0
            positions = []

            for asset in balance:
                symbol = asset.get("symbol", "")
                available = float(asset.get("available", 0.0))
                in_order = float(asset.get("inOrder", 0.0))
                total = available + in_order

                if total < 1e-8:
                    continue

                if symbol == "EUR":
                    total_eur += total
                    positions.append(
                        {
                            "symbol": "EUR",
                            "amount": total,
                            "value_eur": total,
                            "allocation_pct": 0.0,  # Will calculate later
                        }
                    )
                else:
                    # Get current price
                    market = f"{symbol}-EUR"
                    ticker = self._safe_call(self._bv.tickerPrice, {"market": market})
                    if ticker and "price" in ticker:
                        price = float(ticker["price"])
                        value_eur = total * price
                        total_eur += value_eur
                        positions.append(
                            {
                                "symbol": symbol,
                                "amount": total,
                                "price_eur": price,
                                "value_eur": value_eur,
                                "allocation_pct": 0.0,  # Will calculate later
                            }
                        )

            # Calculate allocation percentages
            if total_eur > 0:
                for pos in positions:
                    pos["allocation_pct"] = (pos["value_eur"] / total_eur) * 100

            # Sort by value
            positions.sort(key=lambda x: x["value_eur"], reverse=True)

            return {
                "total_value_eur": round(total_eur, 2),
                "positions": positions,
                "num_positions": len([p for p in positions if p["symbol"] != "EUR"]),
                "cash_pct": round(
                    (positions[0]["value_eur"] / total_eur * 100)
                    if positions and positions[0]["symbol"] == "EUR"
                    else 0.0,
                    2,
                ),
            }
        except Exception as e:
            log(f"AIEngine: portfolio status error: {e}", level="error")
            return {"error": str(e)}

    def calculate_optimal_position_size(
        self, market: str, portfolio: Dict, risk_tolerance: float = 0.05
    ) -> Dict[str, float]:
        """
        Calculate optimal position size based on:
        - Portfolio value
        - Market volatility (ATR)
        - Current allocation
        - Risk tolerance (default 5% of portfolio per position)
        """
        try:
            total_value = portfolio.get("total_value_eur", 0.0)
            if total_value < 10:
                return {"recommended_eur": 0.0, "reason": "Portfolio too small"}

            # Get market features for volatility
            features = self.extract_features(market)
            if not features:
                return {"recommended_eur": 0.0, "reason": "Could not analyze market"}

            atr_pct = features.get("atr_pct", 0.02)

            # Base position size: risk_tolerance% of portfolio
            base_size = total_value * risk_tolerance

            # Adjust for volatility: higher vol = smaller position
            # ATR 1% = normal, ATR 3% = reduce by 50%, ATR 5%+ = reduce by 70%
            vol_factor = 1.0
            if atr_pct > 0.05:
                vol_factor = 0.3
            elif atr_pct > 0.03:
                vol_factor = 0.5
            elif atr_pct > 0.02:
                vol_factor = 0.8

            adjusted_size = base_size * vol_factor

            # Check current allocation to this asset
            symbol = market.split("-")[0]
            current_allocation = 0.0
            for pos in portfolio.get("positions", []):
                if pos["symbol"] == symbol:
                    current_allocation = pos["allocation_pct"]
                    break

            # Don't let single position exceed 20% of portfolio
            max_size = total_value * 0.20
            if current_allocation >= 20:
                return {
                    "recommended_eur": 0.0,
                    "reason": f"Already {current_allocation:.1f}% allocated to {symbol}",
                    "max_allocation_reached": True,
                }

            final_size = min(adjusted_size, max_size)
            final_size = max(5.0, final_size)  # Minimum 5 EUR

            return {
                "recommended_eur": round(final_size, 2),
                "base_size": round(base_size, 2),
                "vol_factor": round(vol_factor, 2),
                "atr_pct": round(atr_pct * 100, 2),
                "current_allocation_pct": round(current_allocation, 2),
                "reason": f"Volatility-adjusted size (ATR: {atr_pct * 100:.1f}%)",
            }
        except Exception as e:
            log(f"AIEngine: position size calculation error: {e}", level="error")
            return {"recommended_eur": 0.0, "reason": str(e)}

    def analyze_portfolio_risk(self, portfolio: Dict) -> Dict[str, object]:
        """
        Analyze portfolio risk:
        - Concentration risk (too much in one asset)
        - Correlation risk (similar assets moving together)
        - Volatility risk
        """
        try:
            positions = portfolio.get("positions", [])
            total_value = portfolio.get("total_value_eur", 0.0)

            if not positions or total_value < 10:
                return {"risk_level": "unknown", "warnings": []}

            warnings = []
            risk_score = 0.0

            # Concentration risk
            crypto_positions = [p for p in positions if p["symbol"] != "EUR"]
            if crypto_positions:
                max_allocation = max(p["allocation_pct"] for p in crypto_positions)
                if max_allocation > 30:
                    warnings.append(
                        {
                            "type": "concentration",
                            "severity": "high",
                            "message": f"Te veel concentratie: {max_allocation:.1f}% in één asset",
                        }
                    )
                    risk_score += 30
                elif max_allocation > 20:
                    warnings.append(
                        {
                            "type": "concentration",
                            "severity": "medium",
                            "message": f"Hoge concentratie: {max_allocation:.1f}% in één asset",
                        }
                    )
                    risk_score += 15

            # Number of positions risk
            num_crypto = len(crypto_positions)
            if num_crypto >= 10:
                warnings.append(
                    {
                        "type": "diversification",
                        "severity": "medium",
                        "message": f"Te veel posities ({num_crypto}): moeilijk te beheren",
                    }
                )
                risk_score += 10
            elif num_crypto == 1:
                warnings.append(
                    {"type": "diversification", "severity": "high", "message": "Geen diversificatie: slechts 1 positie"}
                )
                risk_score += 20

            # Cash allocation
            cash_pct = portfolio.get("cash_pct", 0.0)
            if cash_pct < 10:
                warnings.append(
                    {"type": "liquidity", "severity": "high", "message": f"Weinig cash reserve: {cash_pct:.1f}% EUR"}
                )
                risk_score += 20
            elif cash_pct > 70:
                warnings.append(
                    {
                        "type": "opportunity",
                        "severity": "low",
                        "message": f"Veel cash: {cash_pct:.1f}% niet geïnvesteerd",
                    }
                )

            # Calculate volatility for each position
            high_vol_positions = []
            for pos in crypto_positions:
                market = f"{pos['symbol']}-EUR"
                features = self.extract_features(market)
                if features:
                    atr_pct = features.get("atr_pct", 0.0)
                    if atr_pct > 0.04:  # >4% daily volatility
                        high_vol_positions.append(
                            {
                                "symbol": pos["symbol"],
                                "atr_pct": round(atr_pct * 100, 2),
                                "allocation_pct": round(pos["allocation_pct"], 1),
                            }
                        )

            if high_vol_positions:
                total_high_vol_allocation = sum(p["allocation_pct"] for p in high_vol_positions)
                if total_high_vol_allocation > 40:
                    warnings.append(
                        {
                            "type": "volatility",
                            "severity": "high",
                            "message": f"Te veel in volatiele assets: {total_high_vol_allocation:.1f}%",
                            "details": high_vol_positions,
                        }
                    )
                    risk_score += 25

            # Determine overall risk level
            if risk_score >= 50:
                risk_level = "high"
            elif risk_score >= 25:
                risk_level = "medium"
            else:
                risk_level = "low"

            return {
                "risk_level": risk_level,
                "risk_score": round(risk_score, 1),
                "warnings": warnings,
                "num_positions": num_crypto,
                "cash_pct": round(cash_pct, 2),
                "high_volatility_positions": high_vol_positions,
            }
        except Exception as e:
            log(f"AIEngine: risk analysis error: {e}", level="error")
            return {"risk_level": "unknown", "error": str(e)}

    def get_investment_recommendations(self) -> Dict[str, object]:
        """
        Complete investment advice combining:
        - Portfolio status
        - Market opportunities
        - Risk analysis
        - Optimal position sizing
        """
        try:
            # Get portfolio
            portfolio = self.get_portfolio_status()
            if "error" in portfolio:
                return {"error": portfolio["error"]}

            # Analyze risk
            risk_analysis = self.analyze_portfolio_risk(portfolio)

            # Get market scores
            market_scores = self.score_markets(self.get_whitelist()[:15])

            # Get regime
            regime, regime_stats = self.classify_regime()

            # Generate recommendations
            recommendations = []

            # Top 5 markets with position size recommendations
            for market_data in market_scores[:5]:
                market = market_data["market"]
                score = market_data["score"]

                # Calculate optimal size
                size_info = self.calculate_optimal_position_size(market, portfolio)

                # Only recommend if score is decent and size > 0
                if score > 0.4 and size_info["recommended_eur"] > 0:
                    recommendations.append(
                        {
                            "market": market,
                            "score": round(score, 3),
                            "recommended_size_eur": size_info["recommended_eur"],
                            "volatility_pct": size_info.get("atr_pct", 0),
                            "reason": size_info.get("reason", ""),
                            "factors": market_data.get("factors", [])[:2],
                        }
                    )

            return {
                "portfolio": {
                    "total_value_eur": portfolio["total_value_eur"],
                    "num_positions": portfolio["num_positions"],
                    "cash_pct": portfolio["cash_pct"],
                    "top_positions": portfolio["positions"][:5],
                },
                "risk_analysis": risk_analysis,
                "market_regime": {"regime": regime, "stats": regime_stats},
                "recommendations": recommendations,
                "summary": self._generate_summary(portfolio, risk_analysis, regime, recommendations),
            }
        except Exception as e:
            log(f"AIEngine: investment recommendations error: {e}", level="error")
            return {"error": str(e)}

    def _generate_summary(self, portfolio: Dict, risk: Dict, regime: str, recs: List[Dict]) -> str:
        """Generate human-readable summary."""
        lines = []

        total = portfolio.get("total_value_eur", 0)
        lines.append(f"📊 Portfolio: €{total:.2f}")
        lines.append(f"💰 Cash: {portfolio.get('cash_pct', 0):.1f}%")
        lines.append(f"📈 Posities: {portfolio.get('num_positions', 0)}")
        lines.append(f"⚠️  Risico: {risk.get('risk_level', 'unknown').upper()}")
        lines.append(f"🌍 Markt regime: {regime.upper()}")

        if recs:
            lines.append("\n💡 Top kansen:")
            for i, rec in enumerate(recs[:3], 1):
                market = rec["market"]
                size = rec["recommended_size_eur"]
                score = rec["score"]
                lines.append(f"  {i}. {market}: €{size:.2f} (score: {score:.2f})")

        if risk.get("warnings"):
            lines.append("\n⚠️  Waarschuwingen:")
            for w in risk["warnings"][:3]:
                lines.append(f"  - {w['message']}")

        return "\n".join(lines)

    def calculate_correlation_matrix(
        self, markets: Optional[List[str]] = None, lookback: int = 100
    ) -> Dict[str, object]:
        """
        Calculate correlation between assets to detect diversification issues.
        High correlation (>0.7) means assets move together = less diversification.
        """
        try:
            markets = markets or self.get_whitelist()[:10]
            if len(markets) < 2:
                return {"error": "Need at least 2 markets"}

            # Get price data for all markets
            returns_data = {}
            for market in markets:
                candles = self.candles(market, "1m", lookback)
                if not candles or len(candles) < lookback:
                    continue
                closes = self._closes(candles)
                if len(closes) < 2:
                    continue
                # Calculate returns
                returns = [(closes[i] / closes[i - 1] - 1) for i in range(1, len(closes))]
                returns_data[market] = returns

            if len(returns_data) < 2:
                return {"error": "Not enough data"}

            # Calculate correlation matrix
            correlations = []
            markets_list = list(returns_data.keys())

            for i, m1 in enumerate(markets_list):
                for j, m2 in enumerate(markets_list):
                    if i >= j:  # Skip duplicates and self
                        continue

                    r1 = np.array(returns_data[m1])
                    r2 = np.array(returns_data[m2])

                    # Align lengths
                    min_len = min(len(r1), len(r2))
                    r1 = r1[-min_len:]
                    r2 = r2[-min_len:]

                    # Calculate correlation
                    corr = float(np.corrcoef(r1, r2)[0, 1])

                    correlations.append({"market1": m1, "market2": m2, "correlation": round(corr, 3)})

            # Sort by absolute correlation (highest correlation = least diversification)
            correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)

            # Find high correlation pairs (>0.7)
            high_corr = [c for c in correlations if abs(c["correlation"]) > 0.7]

            avg_corr = np.mean([abs(c["correlation"]) for c in correlations])

            return {
                "correlations": correlations[:10],  # Top 10
                "high_correlation_pairs": high_corr,
                "avg_correlation": round(float(avg_corr), 3),
                "diversification_score": round((1.0 - avg_corr) * 100, 1),  # Higher = better
                "warning": "Hoge correlatie detecteerd - weinig diversificatie" if len(high_corr) > 0 else None,
            }
        except Exception as e:
            log(f"AIEngine: correlation calculation error: {e}", level="error")
            return {"error": str(e)}

    def predict_trade_success(self, market: str, trade_history: List[Dict]) -> Dict[str, object]:
        """
        Predict success probability for a market based on historical performance.
        Uses past trades for this specific market.
        """
        try:
            # Filter trades for this market
            market_trades = [t for t in trade_history if t.get("market") == market]

            if len(market_trades) < 5:
                return {
                    "win_probability": 0.5,  # Default 50%
                    "confidence": "low",
                    "reason": f"Onvoldoende data ({len(market_trades)} trades)",
                }

            # Calculate win rate
            wins = sum(1 for t in market_trades if t.get("profit", 0) > 0)
            win_rate = wins / len(market_trades)

            # Calculate average profit and loss
            profits = [t["profit"] for t in market_trades if t.get("profit", 0) > 0]
            losses = [abs(t["profit"]) for t in market_trades if t.get("profit", 0) < 0]

            avg_profit = np.mean(profits) if profits else 0.0
            avg_loss = np.mean(losses) if losses else 0.0

            # Risk/Reward ratio
            rr_ratio = (avg_profit / avg_loss) if avg_loss > 0 else 0.0

            # Get current market features
            features = self.extract_features(market)
            if not features:
                return {"error": "Could not analyze market"}

            # Adjust win rate based on current conditions
            adjusted_prob = win_rate

            # RSI adjustment
            rsi = features.get("rsi14", 50)
            if rsi < 30:  # Oversold
                adjusted_prob += 0.1
            elif rsi > 70:  # Overbought
                adjusted_prob -= 0.1

            # Momentum adjustment
            ret_15 = features.get("ret_15", 0)
            if ret_15 > 0.02:  # Strong uptrend
                adjusted_prob += 0.05
            elif ret_15 < -0.02:  # Strong downtrend
                adjusted_prob -= 0.05

            # Volume adjustment
            vol_ratio = features.get("volume_ratio", 1.0)
            if vol_ratio > 1.5:  # High volume = more conviction
                adjusted_prob += 0.05

            # Volatility penalty
            atr_pct = features.get("atr_pct", 0.02)
            if atr_pct > 0.04:  # High volatility
                adjusted_prob -= 0.08

            # Clamp to 0-1
            adjusted_prob = max(0.1, min(0.9, adjusted_prob))

            # Confidence based on sample size
            if len(market_trades) >= 20:
                confidence = "high"
            elif len(market_trades) >= 10:
                confidence = "medium"
            else:
                confidence = "low"

            return {
                "win_probability": round(adjusted_prob, 3),
                "historical_win_rate": round(win_rate, 3),
                "num_trades": len(market_trades),
                "avg_profit_eur": round(avg_profit, 2),
                "avg_loss_eur": round(avg_loss, 2),
                "risk_reward_ratio": round(rr_ratio, 2),
                "confidence": confidence,
                "adjustments": {
                    "rsi": round(rsi, 1),
                    "momentum": round(ret_15 * 100, 2),
                    "volume_surge": round((vol_ratio - 1.0) * 100, 1),
                    "volatility": round(atr_pct * 100, 2),
                },
            }
        except Exception as e:
            log(f"AIEngine: trade prediction error: {e}", level="error")
            return {"error": str(e)}

    def optimize_dca_timing(self, market: str, entry_price: float, current_price: float) -> Dict[str, object]:
        """
        Determine optimal DCA entry timing based on:
        - Price drop percentage
        - RSI levels
        - Support levels
        - Volatility
        """
        try:
            drop_pct = (entry_price - current_price) / entry_price

            # Get market features
            features = self.extract_features(market)
            if not features:
                return {"recommendation": "wait", "reason": "Could not analyze market"}

            rsi = features.get("rsi14", 50)
            atr_pct = features.get("atr_pct", 0.02)
            volume_ratio = features.get("volume_ratio", 1.0)

            score = 0
            reasons = []

            # Price drop score
            if drop_pct >= 0.06:  # >6% drop
                score += 40
                reasons.append(f"Grote dip: {drop_pct * 100:.1f}%")
            elif drop_pct >= 0.04:  # >4% drop
                score += 25
                reasons.append(f"Goede dip: {drop_pct * 100:.1f}%")
            elif drop_pct >= 0.02:  # >2% drop
                score += 10
                reasons.append(f"Kleine dip: {drop_pct * 100:.1f}%")
            else:
                score -= 10
                reasons.append(f"Te kleine dip: {drop_pct * 100:.1f}%")

            # RSI score
            if rsi <= 25:  # Heavily oversold
                score += 35
                reasons.append(f"Zwaar oversold (RSI: {rsi:.0f})")
            elif rsi <= 30:
                score += 25
                reasons.append(f"Oversold (RSI: {rsi:.0f})")
            elif rsi <= 40:
                score += 15
                reasons.append(f"Laag RSI: {rsi:.0f}")
            elif rsi >= 60:
                score -= 20
                reasons.append(f"Te hoog RSI: {rsi:.0f}")

            # Volume spike score (panic selling or capitulation)
            if volume_ratio > 2.0:
                score += 15
                reasons.append(f"Volume spike: {volume_ratio:.1f}x")
            elif volume_ratio > 1.5:
                score += 10
                reasons.append(f"Verhoogd volume: {volume_ratio:.1f}x")

            # Volatility penalty (wait for calm)
            if atr_pct > 0.05:
                score -= 15
                reasons.append(f"Te volatiel: {atr_pct * 100:.1f}%")
            elif atr_pct > 0.03:
                score -= 5
                reasons.append(f"Redelijk volatiel: {atr_pct * 100:.1f}%")

            # Recommendation
            if score >= 50:
                recommendation = "buy_now"
                urgency = "high"
            elif score >= 30:
                recommendation = "buy_soon"
                urgency = "medium"
            elif score >= 10:
                recommendation = "wait_better_entry"
                urgency = "low"
            else:
                recommendation = "do_not_buy"
                urgency = "none"

            return {
                "recommendation": recommendation,
                "urgency": urgency,
                "score": score,
                "reasons": reasons,
                "metrics": {
                    "drop_pct": round(drop_pct * 100, 2),
                    "rsi": round(rsi, 1),
                    "volume_ratio": round(volume_ratio, 2),
                    "volatility_pct": round(atr_pct * 100, 2),
                },
            }
        except Exception as e:
            log(f"AIEngine: DCA timing error: {e}", level="error")
            return {"error": str(e)}

    def detect_momentum_shift(self, market: str, threshold: float = 0.6) -> Dict[str, object]:
        """
        Detect early momentum shifts (trend changes) using multiple indicators.
        Useful for early entry/exit signals.
        """
        try:
            features = self.extract_features(market, interval="1m", limit=180)
            if not features:
                return {"shift_detected": False, "reason": "No data"}

            # Get longer timeframe data too
            features_5m = self.extract_features(market, interval="5m", limit=100)

            signals = []
            score = 0.0

            # 1. RSI momentum
            rsi = features.get("rsi14", 50)
            if rsi < 30:
                signals.append({"indicator": "RSI", "signal": "oversold", "strength": 0.3})
                score += 0.3
            elif rsi > 70:
                signals.append({"indicator": "RSI", "signal": "overbought", "strength": -0.3})
                score -= 0.3

            # 2. MACD crossover
            macd_hist = features.get("macd_hist", 0)
            if macd_hist > 0:
                signals.append({"indicator": "MACD", "signal": "bullish", "strength": 0.2})
                score += 0.2
            elif macd_hist < 0:
                signals.append({"indicator": "MACD", "signal": "bearish", "strength": -0.2})
                score -= 0.2

            # 3. Price momentum (slope)
            slope = features.get("slope_30", 0)
            if slope > 0.01:
                signals.append({"indicator": "Slope", "signal": "uptrend", "strength": 0.25})
                score += 0.25
            elif slope < -0.01:
                signals.append({"indicator": "Slope", "signal": "downtrend", "strength": -0.25})
                score -= 0.25

            # 4. Volume confirmation
            vol_trend = features.get("volume_trend", 0)
            if vol_trend > 0.5:
                signals.append({"indicator": "Volume", "signal": "increasing", "strength": 0.15})
                score += 0.15
            elif vol_trend < -0.5:
                signals.append({"indicator": "Volume", "signal": "decreasing", "strength": -0.15})
                score -= 0.15

            # 5. Short-term momentum
            ret_5 = features.get("ret_5", 0)
            if ret_5 > 0.015:
                signals.append({"indicator": "Short-term", "signal": "strong_up", "strength": 0.2})
                score += 0.2
            elif ret_5 < -0.015:
                signals.append({"indicator": "Short-term", "signal": "strong_down", "strength": -0.2})
                score -= 0.2

            # Determine shift
            shift_detected = abs(score) >= threshold
            direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"

            return {
                "shift_detected": shift_detected,
                "direction": direction,
                "confidence": round(abs(score), 2),
                "threshold": threshold,
                "signals": signals,
                "recommendation": self._momentum_recommendation(score, shift_detected),
            }
        except Exception as e:
            log(f"AIEngine: momentum detection error: {e}", level="error")
            return {"error": str(e)}

    def _momentum_recommendation(self, score: float, detected: bool) -> str:
        """Generate recommendation based on momentum score."""
        if not detected:
            return "Geen duidelijke trend - afwachten"

        if score >= 0.6:
            return "🚀 Sterke bullish momentum - overwegen te kopen"
        elif score >= 0.3:
            return "📈 Lichte bullish momentum - voorzichtig positief"
        elif score <= -0.6:
            return "📉 Sterke bearish momentum - vermijden of verkopen"
        elif score <= -0.3:
            return "⚠️ Lichte bearish momentum - voorzichtig"
        else:
            return "➡️ Neutrale momentum - afwachten"

    def calculate_optimal_take_profit(
        self, market: str, entry_price: float, trade_history: List[Dict]
    ) -> Dict[str, object]:
        """
        Calculate optimal take-profit targets based on:
        - Historical performance of this market
        - Current volatility
        - Support/resistance levels
        """
        try:
            # Get historical performance for this market
            market_trades = [t for t in trade_history if t.get("market") == market and t.get("profit", 0) > 0]

            # Get current features
            features = self.extract_features(market)
            if not features:
                return {"error": "Could not analyze market"}

            atr_pct = features.get("atr_pct", 0.02)
            bb_width = features.get("bb_width", 0.03)

            # Calculate historical avg profit percentage
            if len(market_trades) >= 3:
                profits_pct = []
                for t in market_trades:
                    if "entry_price" in t and "exit_price" in t:
                        profit_pct = (t["exit_price"] - t["entry_price"]) / t["entry_price"]
                        profits_pct.append(profit_pct)

                if profits_pct:
                    avg_profit_pct = float(np.mean(profits_pct))
                    std_profit_pct = float(np.std(profits_pct))
                else:
                    avg_profit_pct = 0.025  # Default 2.5%
                    std_profit_pct = 0.01
            else:
                avg_profit_pct = 0.025
                std_profit_pct = 0.01

            # Adjust based on current volatility
            # Higher volatility = wider targets
            vol_multiplier = 1.0 + (atr_pct / 0.02)  # Normalize to 2% ATR

            # Calculate targets
            conservative_target = entry_price * (1 + (avg_profit_pct * 0.7 * vol_multiplier))
            moderate_target = entry_price * (1 + (avg_profit_pct * vol_multiplier))
            aggressive_target = entry_price * (1 + (avg_profit_pct * 1.5 * vol_multiplier))

            # Calculate stop-loss based on ATR
            recommended_sl = entry_price * (1 - (atr_pct * 2.0))  # 2x ATR stop

            return {
                "targets": {
                    "conservative": round(conservative_target, 8),
                    "moderate": round(moderate_target, 8),
                    "aggressive": round(aggressive_target, 8),
                },
                "target_pct": {
                    "conservative": round((conservative_target / entry_price - 1) * 100, 2),
                    "moderate": round((moderate_target / entry_price - 1) * 100, 2),
                    "aggressive": round((aggressive_target / entry_price - 1) * 100, 2),
                },
                "recommended_stop_loss": round(recommended_sl, 8),
                "stop_loss_pct": round((1 - recommended_sl / entry_price) * 100, 2),
                "risk_reward_ratio": round((moderate_target - entry_price) / (entry_price - recommended_sl), 2),
                "based_on": {
                    "historical_trades": len(market_trades),
                    "avg_profit_pct": round(avg_profit_pct * 100, 2),
                    "current_volatility": round(atr_pct * 100, 2),
                },
                "recommendation": self._tp_recommendation(avg_profit_pct, atr_pct),
            }
        except Exception as e:
            log(f"AIEngine: take-profit calculation error: {e}", level="error")
            return {"error": str(e)}

    def _tp_recommendation(self, avg_profit: float, volatility: float) -> str:
        """Generate take-profit recommendation."""
        if volatility > 0.04:
            return f"Hoge volatiliteit ({volatility * 100:.1f}%) - gebruik wijdere targets"
        elif volatility > 0.03:
            return "Normale volatiliteit - standaard targets OK"
        else:
            return f"Lage volatiliteit ({volatility * 100:.1f}%) - overweeg kortere targets"

    def analyze_market_blacklist(self, trade_history: List[Dict]) -> Dict[str, object]:
        """
        Analyze which markets consistently lose money and should be blacklisted.

        Returns dict with:
        - blacklist_candidates: markets with >70% loss rate after 5+ trades
        - underperformers: markets with <40% win rate
        - market_stats: detailed stats per market
        """
        try:
            from collections import defaultdict

            market_stats = defaultdict(
                lambda: {
                    "trades": 0,
                    "wins": 0,
                    "losses": 0,
                    "total_profit": 0,
                    "avg_profit": 0,
                    "win_rate": 0,
                    "avg_loss": 0,
                }
            )

            # Analyze each closed trade
            for trade in trade_history:
                if trade.get("close_reason") in ["sync_removed", "manual_close"]:
                    continue

                market = trade.get("market", "unknown")
                profit = trade.get("profit", 0)

                stats = market_stats[market]
                stats["trades"] += 1
                stats["total_profit"] += profit

                if profit > 0:
                    stats["wins"] += 1
                else:
                    stats["losses"] += 1

            # Calculate metrics
            blacklist_candidates = []
            underperformers = []

            for market, stats in market_stats.items():
                if stats["trades"] == 0:
                    continue

                stats["win_rate"] = (stats["wins"] / stats["trades"]) * 100
                stats["avg_profit"] = stats["total_profit"] / stats["trades"]

                if stats["losses"] > 0:
                    loss_trades = [t for t in trade_history if t.get("market") == market and t.get("profit", 0) < 0]
                    if loss_trades:
                        stats["avg_loss"] = sum(t.get("profit", 0) for t in loss_trades) / len(loss_trades)

                # Blacklist if: 5+ trades AND win_rate < 30% AND total_profit < -10
                if stats["trades"] >= 5 and stats["win_rate"] < 30 and stats["total_profit"] < -10:
                    blacklist_candidates.append(
                        {
                            "market": market,
                            "win_rate": stats["win_rate"],
                            "total_profit": stats["total_profit"],
                            "trades": stats["trades"],
                            "reason": "Consistent losses with low win rate",
                        }
                    )

                # Underperformer if: 10+ trades AND win_rate < 40%
                elif stats["trades"] >= 10 and stats["win_rate"] < 40:
                    underperformers.append(
                        {
                            "market": market,
                            "win_rate": stats["win_rate"],
                            "total_profit": stats["total_profit"],
                            "trades": stats["trades"],
                            "reason": "Below 40% win rate",
                        }
                    )

            # Sort by worst performance
            blacklist_candidates.sort(key=lambda x: x["total_profit"])
            underperformers.sort(key=lambda x: x["win_rate"])

            return {
                "blacklist_candidates": blacklist_candidates,
                "underperformers": underperformers,
                "market_stats": dict(market_stats),
                "recommendation": self._generate_blacklist_recommendation(blacklist_candidates, underperformers),
            }
        except Exception as e:
            log(f"AIEngine: blacklist analysis error: {e}", level="error")
            return {"error": str(e)}

    def _generate_blacklist_recommendation(self, blacklist: List[Dict], underperformers: List[Dict]) -> str:
        """Generate recommendation text for blacklisting."""
        if not blacklist and not underperformers:
            return "Geen markets om te blacklisten - alle markets presteren OK"

        rec = []
        if blacklist:
            markets = [m["market"] for m in blacklist[:5]]
            rec.append(f"⚠️ BLACKLIST: {', '.join(markets)} (consistent losses)")

        if underperformers:
            markets = [m["market"] for m in underperformers[:3]]
            rec.append(f"⚡ Monitor: {', '.join(markets)} (lage win rate)")

        return " | ".join(rec)

    def get_advanced_recommendations(self, trade_history: List[Dict]) -> Dict[str, object]:
        """
        Complete advanced AI analysis combining all new features.
        """
        try:
            markets = self.get_whitelist()[:10]

            # 1. Correlation analysis
            correlation = self.calculate_correlation_matrix(markets)

            # 2. Win predictions for top markets
            predictions = []
            for market in markets[:5]:
                pred = self.predict_trade_success(market, trade_history)
                if "error" not in pred:
                    predictions.append(
                        {"market": market, "win_probability": pred["win_probability"], "confidence": pred["confidence"]}
                    )

            # Sort by win probability
            predictions.sort(key=lambda x: x["win_probability"], reverse=True)

            # 3. Momentum detection for top markets
            momentum_shifts = []
            for market in markets[:5]:
                momentum = self.detect_momentum_shift(market)
                if momentum.get("shift_detected"):
                    momentum_shifts.append(
                        {
                            "market": market,
                            "direction": momentum["direction"],
                            "confidence": momentum["confidence"],
                            "recommendation": momentum["recommendation"],
                        }
                    )

            # 4. NEW: Blacklist analysis
            blacklist_analysis = self.analyze_market_blacklist(trade_history)

            return {
                "correlation_analysis": correlation,
                "win_predictions": predictions,
                "momentum_shifts": momentum_shifts,
                "blacklist_analysis": blacklist_analysis,
                "timestamp": time.time(),
            }
        except Exception as e:
            log(f"AIEngine: advanced recommendations error: {e}", level="error")
            return {"error": str(e)}
