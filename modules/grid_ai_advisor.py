"""
AI Grid Advisor - Intelligent Grid Trading Recommendations

This module uses market analysis to recommend optimal grid trading parameters:
- Best coins for grid trading (volatility-based)
- Optimal upper/lower price bounds
- Grid count recommendations
- Confidence scores and rationale

Features:
- Volatility analysis (ATR, realized volatility)
- Trend strength detection (EMA slopes)
- Volume regime analysis
- Mean reversion signals
- Spread/liquidity proxies
"""

import json
import math
import os
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

# Project imports
try:
    from modules.json_compat import write_json_compat
    from modules.logging_utils import log
except ImportError:

    def log(msg, level="info"):
        print(f"[{level.upper()}] {msg}")

    def write_json_compat(path, data, **kwargs):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, **kwargs)


# ================= DATA CLASSES =================


@dataclass
class GridPlan:
    """AI-recommended grid trading plan."""

    symbol: str
    lower_price: float
    upper_price: float
    current_price: float
    grid_count: int
    spacing_mode: str  # 'arithmetic' or 'geometric'
    base_order_size_eur: float
    total_investment_eur: float
    confidence: float  # 0.0 - 1.0
    rationale: str
    features: Dict[str, float]
    safety_limits: Dict[str, Any]
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MarketAnalysis:
    """Analysis results for a single market."""

    symbol: str
    current_price: float
    volatility_24h: float  # 24h realized volatility %
    volatility_7d: float  # 7d realized volatility %
    atr_14: float  # Average True Range (14 periods)
    trend_strength: float  # -1 (strong down) to +1 (strong up)
    volume_regime: str  # 'low', 'normal', 'high'
    mean_reversion_score: float  # 0-1, higher = better for grid
    spread_pct: float  # Bid-ask spread %
    grid_score: float  # Overall grid suitability 0-100
    recommendation: str  # 'excellent', 'good', 'neutral', 'avoid'


# ================= AI GRID ADVISOR =================


class AIGridAdvisor:
    """
    AI-powered grid trading advisor.

    Analyzes markets and recommends optimal grid trading parameters.

    Usage:
        advisor = AIGridAdvisor(bitvavo_client)

        # Get best coins for grid trading
        recommendations = advisor.get_top_grid_candidates(top_n=5)

        # Get specific grid plan for a coin
        plan = advisor.create_grid_plan('BTC-EUR', investment=500)
    """

    CACHE_FILE = "data/grid_advisor_cache.json"
    CACHE_DURATION = 300  # 5 minutes

    def __init__(self, bitvavo_client=None):
        """Initialize the advisor."""
        self.bitvavo = bitvavo_client
        self._cache = {}
        self._cache_time = 0
        self._load_cache()

    def _load_cache(self):
        """Load cached analysis from disk."""
        try:
            if os.path.exists(self.CACHE_FILE):
                with open(self.CACHE_FILE, "r") as f:
                    data = json.load(f)
                    self._cache = data.get("analyses", {})
                    self._cache_time = data.get("timestamp", 0)
        except Exception as e:
            log(f"[AIGridAdvisor] Failed to load cache: {e}", level="warning")

    def _save_cache(self):
        """Save analysis cache to disk."""
        try:
            os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
            write_json_compat(self.CACHE_FILE, {"timestamp": time.time(), "analyses": self._cache}, indent=2)
        except Exception as e:
            log(f"[AIGridAdvisor] Failed to save cache: {e}", level="warning")

    def _get_candles(self, market: str, interval: str = "1h", limit: int = 168) -> List[Dict]:
        """Get historical candles from API or cache."""
        if not self.bitvavo:
            return []

        try:
            candles = self.bitvavo.candles(market, interval, {"limit": limit})
            return candles if candles else []
        except Exception as e:
            log(f"[AIGridAdvisor] Failed to get candles for {market}: {e}", level="warning")
            return []

    def _get_ticker(self, market: str) -> Optional[Dict]:
        """Get current ticker data."""
        if not self.bitvavo:
            return None

        try:
            return self.bitvavo.ticker_price({"market": market})
        except Exception:
            return None

    def _get_book(self, market: str) -> Optional[Dict]:
        """Get order book for spread analysis."""
        if not self.bitvavo:
            return None

        try:
            return self.bitvavo.book(market, {"depth": 1})
        except Exception:
            return None

    def _calculate_volatility(self, candles: List[Dict]) -> Tuple[float, float]:
        """
        Calculate realized volatility.

        Returns:
            (24h_volatility_pct, 7d_volatility_pct)
        """
        if len(candles) < 24:
            return (0.0, 0.0)

        # Get close prices
        closes = [float(c[4]) for c in candles]  # [timestamp, open, high, low, close, volume]

        # Calculate returns
        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                ret = (closes[i] - closes[i - 1]) / closes[i - 1]
                returns.append(ret)

        if not returns:
            return (0.0, 0.0)

        # 24h volatility (last 24 returns for hourly candles)
        returns_24h = returns[-24:] if len(returns) >= 24 else returns
        vol_24h = math.sqrt(sum(r**2 for r in returns_24h) / len(returns_24h)) * math.sqrt(24) * 100

        # 7d volatility
        returns_7d = returns[-168:] if len(returns) >= 168 else returns
        vol_7d = math.sqrt(sum(r**2 for r in returns_7d) / len(returns_7d)) * math.sqrt(168) * 100

        return (vol_24h, vol_7d)

    def _calculate_atr(self, candles: List[Dict], period: int = 14) -> float:
        """Calculate Average True Range."""
        if len(candles) < period + 1:
            return 0.0

        trs = []
        for i in range(1, len(candles)):
            high = float(candles[i][2])
            low = float(candles[i][3])
            prev_close = float(candles[i - 1][4])

            tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
            trs.append(tr)

        # ATR is EMA of TR
        if len(trs) < period:
            return sum(trs) / len(trs) if trs else 0.0

        atr = sum(trs[:period]) / period
        multiplier = 2 / (period + 1)

        for tr in trs[period:]:
            atr = (tr - atr) * multiplier + atr

        return atr

    def _calculate_trend_strength(self, candles: List[Dict]) -> float:
        """
        Calculate trend strength using EMA slopes.

        Returns:
            -1 (strong downtrend) to +1 (strong uptrend)
        """
        if len(candles) < 50:
            return 0.0

        closes = [float(c[4]) for c in candles]

        # Calculate EMAs
        def ema(data: List[float], period: int) -> List[float]:
            if len(data) < period:
                return []
            result = [sum(data[:period]) / period]
            multiplier = 2 / (period + 1)
            for price in data[period:]:
                result.append((price - result[-1]) * multiplier + result[-1])
            return result

        ema_20 = ema(closes, 20)
        ema_50 = ema(closes, 50)

        if not ema_20 or not ema_50:
            return 0.0

        # Trend based on EMA relationship and slope
        current_ema20 = ema_20[-1]
        current_ema50 = ema_50[-1]

        # EMA20 vs EMA50 relationship
        if current_ema50 > 0:
            ema_diff_pct = (current_ema20 - current_ema50) / current_ema50
        else:
            ema_diff_pct = 0

        # EMA20 slope (last 5 periods)
        if len(ema_20) >= 5:
            slope = (ema_20[-1] - ema_20[-5]) / ema_20[-5] if ema_20[-5] > 0 else 0
        else:
            slope = 0

        # Combine into trend strength
        trend = ema_diff_pct * 5 + slope * 10  # Weighted combination

        # Clamp to [-1, 1]
        return max(-1.0, min(1.0, trend))

    def _calculate_volume_regime(self, candles: List[Dict]) -> str:
        """Determine volume regime (low/normal/high)."""
        if len(candles) < 50:
            return "normal"

        volumes = [float(c[5]) for c in candles]
        recent_vol = sum(volumes[-24:]) / 24
        avg_vol = sum(volumes) / len(volumes)

        if avg_vol == 0:
            return "normal"

        ratio = recent_vol / avg_vol

        if ratio < 0.5:
            return "low"
        elif ratio > 1.5:
            return "high"
        else:
            return "normal"

    def _calculate_mean_reversion_score(self, candles: List[Dict]) -> float:
        """
        Calculate mean reversion potential.
        Higher score = more suitable for grid trading.
        """
        if len(candles) < 50:
            return 0.5

        closes = [float(c[4]) for c in candles]

        # Calculate price oscillations around mean
        mean_price = sum(closes) / len(closes)

        # Count crosses through mean
        crosses = 0
        for i in range(1, len(closes)):
            if (closes[i - 1] < mean_price and closes[i] >= mean_price) or (
                closes[i - 1] > mean_price and closes[i] <= mean_price
            ):
                crosses += 1

        # Normalize: more crosses = better for grid trading
        max_possible = len(closes) - 1
        cross_ratio = crosses / max_possible if max_possible > 0 else 0

        # Also consider volatility consistency
        returns = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes)) if closes[i - 1] > 0]

        if returns:
            # Lower variance in returns = more predictable oscillation
            avg_return = sum(abs(r) for r in returns) / len(returns)
            variance = sum((abs(r) - avg_return) ** 2 for r in returns) / len(returns)
            consistency = 1 / (1 + variance * 1000)  # Higher consistency = better
        else:
            consistency = 0.5

        # Combined score
        return 0.6 * cross_ratio + 0.4 * consistency

    def _calculate_spread(self, book: Optional[Dict]) -> float:
        """Calculate bid-ask spread percentage."""
        if not book:
            return 0.0

        try:
            asks = book.get("asks", [])
            bids = book.get("bids", [])

            if not asks or not bids:
                return 0.0

            best_ask = float(asks[0][0])
            best_bid = float(bids[0][0])

            if best_bid > 0:
                return (best_ask - best_bid) / best_bid * 100
            return 0.0
        except Exception:
            return 0.0

    def analyze_market(self, market: str, force_refresh: bool = False) -> Optional[MarketAnalysis]:
        """
        Analyze a market for grid trading suitability.

        Args:
            market: Trading pair (e.g., 'BTC-EUR')
            force_refresh: Bypass cache

        Returns:
            MarketAnalysis or None if analysis fails
        """
        # Check cache
        cache_key = f"analysis_{market}"
        if not force_refresh and cache_key in self._cache:
            cache_entry = self._cache[cache_key]
            if time.time() - cache_entry.get("timestamp", 0) < self.CACHE_DURATION:
                return MarketAnalysis(**cache_entry["data"])

        # Get data
        candles = self._get_candles(market, "1h", 168)  # 7 days hourly
        ticker = self._get_ticker(market)
        book = self._get_book(market)

        if not candles or not ticker:
            log(f"[AIGridAdvisor] Insufficient data for {market}", level="warning")
            return None

        try:
            current_price = float(ticker.get("price", 0))
        except (ValueError, TypeError):
            return None

        if current_price <= 0:
            return None

        # Calculate metrics
        vol_24h, vol_7d = self._calculate_volatility(candles)
        atr = self._calculate_atr(candles, 14)
        trend_strength = self._calculate_trend_strength(candles)
        volume_regime = self._calculate_volume_regime(candles)
        mean_reversion = self._calculate_mean_reversion_score(candles)
        spread_pct = self._calculate_spread(book)

        # Calculate grid suitability score (0-100)
        # Ideal: moderate volatility, neutral trend, high mean reversion, low spread

        # Volatility score (10-30% is ideal for grid)
        if vol_7d < 5:
            vol_score = 20  # Too low
        elif vol_7d < 10:
            vol_score = 60
        elif vol_7d < 30:
            vol_score = 100  # Sweet spot
        elif vol_7d < 50:
            vol_score = 70
        else:
            vol_score = 30  # Too high

        # Trend score (neutral is best)
        trend_score = (1 - abs(trend_strength)) * 100

        # Mean reversion score
        mr_score = mean_reversion * 100

        # Spread score (lower is better)
        if spread_pct < 0.05:
            spread_score = 100
        elif spread_pct < 0.1:
            spread_score = 80
        elif spread_pct < 0.2:
            spread_score = 60
        elif spread_pct < 0.5:
            spread_score = 40
        else:
            spread_score = 20

        # Volume score
        volume_scores = {"low": 50, "normal": 100, "high": 80}
        volume_score = volume_scores.get(volume_regime, 70)

        # Weighted grid score
        grid_score = vol_score * 0.30 + trend_score * 0.25 + mr_score * 0.25 + spread_score * 0.10 + volume_score * 0.10

        # Recommendation
        if grid_score >= 80:
            recommendation = "excellent"
        elif grid_score >= 60:
            recommendation = "good"
        elif grid_score >= 40:
            recommendation = "neutral"
        else:
            recommendation = "avoid"

        analysis = MarketAnalysis(
            symbol=market,
            current_price=current_price,
            volatility_24h=round(vol_24h, 2),
            volatility_7d=round(vol_7d, 2),
            atr_14=round(atr, 6),
            trend_strength=round(trend_strength, 3),
            volume_regime=volume_regime,
            mean_reversion_score=round(mean_reversion, 3),
            spread_pct=round(spread_pct, 4),
            grid_score=round(grid_score, 1),
            recommendation=recommendation,
        )

        # Cache result
        self._cache[cache_key] = {"timestamp": time.time(), "data": asdict(analysis)}
        self._save_cache()

        return analysis

    def get_top_grid_candidates(self, markets: Optional[List[str]] = None, top_n: int = 5) -> List[MarketAnalysis]:
        """
        Get top markets suitable for grid trading.

        Args:
            markets: List of markets to analyze. If None, uses default list.
            top_n: Number of top candidates to return.

        Returns:
            List of MarketAnalysis sorted by grid_score descending
        """
        if markets is None:
            # Default watchlist
            markets = [
                "BTC-EUR",
                "ETH-EUR",
                "SOL-EUR",
                "XRP-EUR",
                "ADA-EUR",
                "DOGE-EUR",
                "AVAX-EUR",
                "DOT-EUR",
                "MATIC-EUR",
                "LINK-EUR",
                "ATOM-EUR",
                "UNI-EUR",
                "LTC-EUR",
                "BCH-EUR",
                "NEAR-EUR",
            ]

        analyses = []
        for market in markets:
            try:
                analysis = self.analyze_market(market)
                if analysis:
                    analyses.append(analysis)
            except Exception as e:
                log(f"[AIGridAdvisor] Error analyzing {market}: {e}", level="warning")

        # Sort by grid score descending
        analyses.sort(key=lambda x: x.grid_score, reverse=True)

        return analyses[:top_n]

    def create_grid_plan(
        self, market: str, investment: float = 100.0, risk_profile: str = "balanced"
    ) -> Optional[GridPlan]:
        """
        Create an AI-recommended grid plan for a market.

        Args:
            market: Trading pair
            investment: Total investment in EUR
            risk_profile: 'conservative', 'balanced', or 'aggressive'

        Returns:
            GridPlan with recommended parameters
        """
        analysis = self.analyze_market(market, force_refresh=True)
        if not analysis:
            return None

        # Risk profile multipliers
        profiles = {
            "conservative": {"range_mult": 1.5, "grids": 8, "spacing": "arithmetic"},
            "balanced": {"range_mult": 2.0, "grids": 12, "spacing": "geometric"},
            "aggressive": {"range_mult": 3.0, "grids": 20, "spacing": "geometric"},
        }
        profile = profiles.get(risk_profile, profiles["balanced"])

        # Calculate price range based on volatility
        volatility = max(analysis.volatility_7d, 5)  # Minimum 5%
        range_pct = volatility * profile["range_mult"] / 100

        # Adjust for trend
        trend_adjustment = analysis.trend_strength * 0.02  # Slight bias

        current_price = analysis.current_price
        lower_price = current_price * (1 - range_pct / 2 + trend_adjustment)
        upper_price = current_price * (1 + range_pct / 2 + trend_adjustment)

        # Grid count based on range and profile
        grid_count = profile["grids"]

        # Adjust grid count based on investment size
        if investment >= 1000:
            grid_count = int(grid_count * 1.5)
        elif investment < 50:
            grid_count = max(5, int(grid_count * 0.7))

        # Ensure minimum grid spacing
        min_spacing_pct = 0.5  # Minimum 0.5% between grids
        max_grids_for_range = int((upper_price - lower_price) / lower_price * 100 / min_spacing_pct)
        grid_count = min(grid_count, max_grids_for_range)
        grid_count = max(3, grid_count)

        # Order sizes
        base_order_size = investment / grid_count

        # Confidence based on analysis
        confidence = analysis.grid_score / 100

        # Adjust confidence for extremes
        if abs(analysis.trend_strength) > 0.5:
            confidence *= 0.8  # Strong trend reduces confidence
        if analysis.spread_pct > 0.2:
            confidence *= 0.9  # High spread reduces confidence

        # Generate rationale
        rationale_parts = []

        if analysis.grid_score >= 70:
            rationale_parts.append(f"High grid suitability score ({analysis.grid_score:.0f}/100)")
        elif analysis.grid_score >= 50:
            rationale_parts.append(f"Moderate grid suitability ({analysis.grid_score:.0f}/100)")
        else:
            rationale_parts.append(f"Below-average suitability ({analysis.grid_score:.0f}/100)")

        rationale_parts.append(f"7d volatility: {analysis.volatility_7d:.1f}%")

        if abs(analysis.trend_strength) < 0.2:
            rationale_parts.append("Neutral trend (ideal for grid)")
        elif analysis.trend_strength > 0:
            rationale_parts.append(f"Slight uptrend ({analysis.trend_strength:.2f})")
        else:
            rationale_parts.append(f"Slight downtrend ({analysis.trend_strength:.2f})")

        rationale_parts.append(f"Mean reversion score: {analysis.mean_reversion_score:.0%}")

        # Safety limits
        safety_limits = {
            "stop_loss_pct": 0.15 if risk_profile == "conservative" else (0.20 if risk_profile == "balanced" else 0.30),
            "take_profit_pct": 0.10
            if risk_profile == "conservative"
            else (0.15 if risk_profile == "balanced" else 0.25),
            "max_drawdown_pct": 0.10,
            "auto_rebalance": True,
        }

        plan = GridPlan(
            symbol=market,
            lower_price=round(lower_price, 2),
            upper_price=round(upper_price, 2),
            current_price=current_price,
            grid_count=grid_count,
            spacing_mode=profile["spacing"],
            base_order_size_eur=round(base_order_size, 2),
            total_investment_eur=investment,
            confidence=round(confidence, 3),
            rationale=" | ".join(rationale_parts),
            features={
                "volatility_7d": analysis.volatility_7d,
                "trend_strength": analysis.trend_strength,
                "mean_reversion": analysis.mean_reversion_score,
                "spread_pct": analysis.spread_pct,
                "grid_score": analysis.grid_score,
            },
            safety_limits=safety_limits,
        )

        log(
            f"[AIGridAdvisor] Created grid plan for {market}: "
            f"{grid_count} grids, €{lower_price:.2f}-€{upper_price:.2f}, "
            f"confidence {confidence:.0%}"
        )

        return plan

    def get_grid_recommendations_summary(self, top_n: int = 5) -> Dict[str, Any]:
        """
        Get a summary of grid trading recommendations for dashboard display.

        Returns dict suitable for dashboard rendering.
        """
        candidates = self.get_top_grid_candidates(top_n=top_n)

        summary = {
            "timestamp": time.time(),
            "candidates": [],
        }

        for analysis in candidates:
            summary["candidates"].append(
                {
                    "symbol": analysis.symbol,
                    "price": analysis.current_price,
                    "grid_score": analysis.grid_score,
                    "recommendation": analysis.recommendation,
                    "volatility_7d": analysis.volatility_7d,
                    "trend": "up"
                    if analysis.trend_strength > 0.1
                    else ("down" if analysis.trend_strength < -0.1 else "neutral"),
                    "trend_strength": analysis.trend_strength,
                }
            )

        return summary


# ================= SINGLETON =================

_ai_advisor: Optional[AIGridAdvisor] = None


def get_ai_grid_advisor(bitvavo_client=None) -> AIGridAdvisor:
    """Get or create the singleton AI advisor instance."""
    global _ai_advisor
    if _ai_advisor is None:
        _ai_advisor = AIGridAdvisor(bitvavo_client)
    elif bitvavo_client is not None and _ai_advisor.bitvavo is None:
        _ai_advisor.bitvavo = bitvavo_client
    return _ai_advisor


# ================= CLI TEST =================

if __name__ == "__main__":
    print("AI Grid Advisor Test")
    print("=" * 60)

    # Test without API (will use empty data)
    advisor = AIGridAdvisor()

    print("\nNote: This test requires a Bitvavo API connection for live data.")
    print("Without API, analysis will return None.")

    # Example of what output would look like
    print("\nExample GridPlan output:")
    example_plan = GridPlan(
        symbol="BTC-EUR",
        lower_price=88000.0,
        upper_price=96000.0,
        current_price=92000.0,
        grid_count=12,
        spacing_mode="geometric",
        base_order_size_eur=41.67,
        total_investment_eur=500.0,
        confidence=0.78,
        rationale="High grid suitability (78/100) | 7d volatility: 12.5% | Neutral trend | Mean reversion: 65%",
        features={
            "volatility_7d": 12.5,
            "trend_strength": 0.05,
            "mean_reversion": 0.65,
            "spread_pct": 0.02,
            "grid_score": 78.0,
        },
        safety_limits={
            "stop_loss_pct": 0.20,
            "take_profit_pct": 0.15,
            "max_drawdown_pct": 0.10,
            "auto_rebalance": True,
        },
    )

    print(f"\n  Symbol: {example_plan.symbol}")
    print(f"  Range: €{example_plan.lower_price:,.2f} - €{example_plan.upper_price:,.2f}")
    print(f"  Current: €{example_plan.current_price:,.2f}")
    print(f"  Grids: {example_plan.grid_count} ({example_plan.spacing_mode})")
    print(f"  Investment: €{example_plan.total_investment_eur:.2f}")
    print(f"  Order size: €{example_plan.base_order_size_eur:.2f}")
    print(f"  Confidence: {example_plan.confidence:.0%}")
    print(f"  Rationale: {example_plan.rationale}")
