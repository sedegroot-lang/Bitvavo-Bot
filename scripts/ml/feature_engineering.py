"""
Advanced Feature Engineering for ML Models
Generates 50+ features from market data for improved prediction accuracy.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.logging_utils import log


class AdvancedFeatureEngineer:
    """Generate comprehensive feature set for ML models."""
    
    def __init__(self):
        self.feature_names = []
    
    def engineer_features(self, candles: List[Dict], orderbook: Optional[Dict] = None,
                         market: str = "", market_stats: Optional[Dict] = None) -> Dict[str, float]:
        """
        Generate 50+ features from candle data.
        
        Returns:
            Dictionary of feature_name: value
        """
        features = {}
        
        if not candles or len(candles) < 50:
            return self._get_default_features()
        
        # Extract price/volume arrays
        closes = np.array([float(c.get('close', 0)) for c in candles])
        highs = np.array([float(c.get('high', 0)) for c in candles])
        lows = np.array([float(c.get('low', 0)) for c in candles])
        volumes = np.array([float(c.get('volume', 0)) for c in candles])
        
        # === TECHNICAL INDICATORS (15 features) ===
        features.update(self._technical_indicators(closes, highs, lows, volumes))
        
        # === TIME-SERIES FEATURES (12 features) ===
        features.update(self._timeseries_features(closes, volumes))
        
        # === VOLATILITY FEATURES (6 features) ===
        features.update(self._volatility_features(closes))
        
        # === VOLUME FEATURES (5 features) ===
        features.update(self._volume_features(volumes))
        
        # === PATTERN RECOGNITION (5 features) ===
        features.update(self._pattern_features(closes, highs, lows))
        
        # === ORDER BOOK FEATURES (4 features) ===
        if orderbook:
            features.update(self._orderbook_features(orderbook))
        else:
            features.update({
                'bid_ask_ratio': 1.0,
                'book_imbalance': 0.0,
                'spread_pct': 0.0,
                'depth_ratio': 1.0
            })
        
        # === MARKET CONTEXT (8 features) ===
        features.update(self._market_context_features(market, market_stats))
        
        self.feature_names = list(features.keys())
        return features
    
    def _technical_indicators(self, closes, highs, lows, volumes) -> Dict:
        """Calculate technical indicators."""
        features = {}
        
        # RSI (multiple periods)
        features['rsi_14'] = self._calculate_rsi(closes, 14)
        features['rsi_7'] = self._calculate_rsi(closes, 7)
        features['rsi_28'] = self._calculate_rsi(closes, 28)
        
        # MACD
        macd_line, signal_line, histogram = self._calculate_macd(closes)
        features['macd_line'] = macd_line
        features['macd_signal'] = signal_line
        features['macd_histogram'] = histogram
        
        # Bollinger Bands
        bb_upper, bb_middle, bb_lower, bb_width = self._calculate_bollinger_bands(closes)
        features['bb_upper'] = bb_upper
        features['bb_width'] = bb_width
        features['bb_position'] = (closes[-1] - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5
        
        # Moving Averages
        features['sma_10'] = np.mean(closes[-10:]) if len(closes) >= 10 else closes[-1]
        features['sma_20'] = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        features['sma_50'] = np.mean(closes[-50:]) if len(closes) >= 50 else closes[-1]
        features['ema_12'] = self._calculate_ema(closes, 12)
        features['ema_26'] = self._calculate_ema(closes, 26)
        
        # ATR
        features['atr_14'] = self._calculate_atr(highs, lows, closes, 14)
        
        return features
    
    def _timeseries_features(self, closes, volumes) -> Dict:
        """Time-series momentum and trend features."""
        features = {}
        
        # Rate of Change (multiple periods)
        features['roc_1'] = (closes[-1] - closes[-2]) / closes[-2] if len(closes) >= 2 and closes[-2] != 0 else 0
        features['roc_5'] = (closes[-1] - closes[-6]) / closes[-6] if len(closes) >= 6 and closes[-6] != 0 else 0
        features['roc_10'] = (closes[-1] - closes[-11]) / closes[-11] if len(closes) >= 11 and closes[-11] != 0 else 0
        features['roc_20'] = (closes[-1] - closes[-21]) / closes[-21] if len(closes) >= 21 and closes[-21] != 0 else 0
        
        # Momentum
        features['momentum_5'] = closes[-1] - closes[-6] if len(closes) >= 6 else 0
        features['momentum_10'] = closes[-1] - closes[-11] if len(closes) >= 11 else 0
        
        # Trend strength (linear regression slope)
        if len(closes) >= 20:
            x = np.arange(20)
            slope, _ = np.polyfit(x, closes[-20:], 1)
            features['trend_slope_20'] = slope / closes[-1] if closes[-1] != 0 else 0
        else:
            features['trend_slope_20'] = 0
        
        # Price position relative to high/low
        if len(closes) >= 20:
            high_20 = np.max(closes[-20:])
            low_20 = np.min(closes[-20:])
            features['price_position_20'] = (closes[-1] - low_20) / (high_20 - low_20) if (high_20 - low_20) > 0 else 0.5
        else:
            features['price_position_20'] = 0.5
        
        # Distance from moving averages
        sma_20 = np.mean(closes[-20:]) if len(closes) >= 20 else closes[-1]
        features['distance_from_sma20'] = (closes[-1] - sma_20) / sma_20 if sma_20 != 0 else 0
        
        # Acceleration
        if len(closes) >= 3:
            v1 = closes[-1] - closes[-2]
            v2 = closes[-2] - closes[-3]
            features['price_acceleration'] = v1 - v2
        else:
            features['price_acceleration'] = 0
        
        # Volume trend
        if len(volumes) >= 10:
            vol_ma = np.mean(volumes[-10:])
            features['volume_trend'] = volumes[-1] / vol_ma if vol_ma > 0 else 1
        else:
            features['volume_trend'] = 1
        
        # Time-based features
        now = datetime.now()
        features['hour_of_day'] = now.hour / 24.0  # Normalize to 0-1
        features['day_of_week'] = now.weekday() / 7.0  # Normalize to 0-1
        
        return features
    
    def _volatility_features(self, closes) -> Dict:
        """Volatility metrics."""
        features = {}
        
        # Historical volatility (multiple windows)
        if len(closes) >= 10:
            returns_10 = np.diff(closes[-10:]) / closes[-10:-1]
            features['volatility_10'] = np.std(returns_10)
        else:
            features['volatility_10'] = 0
        
        if len(closes) >= 20:
            returns_20 = np.diff(closes[-20:]) / closes[-20:-1]
            features['volatility_20'] = np.std(returns_20)
        else:
            features['volatility_20'] = 0
        
        if len(closes) >= 50:
            returns_50 = np.diff(closes[-50:]) / closes[-50:-1]
            features['volatility_50'] = np.std(returns_50)
        else:
            features['volatility_50'] = 0
        
        # Volatility ratio (recent vs historical)
        if features['volatility_20'] > 0 and features['volatility_50'] > 0:
            features['volatility_ratio'] = features['volatility_10'] / features['volatility_20']
        else:
            features['volatility_ratio'] = 1.0
        
        # Price range
        if len(closes) >= 20:
            high_20 = np.max(closes[-20:])
            low_20 = np.min(closes[-20:])
            features['price_range_20'] = (high_20 - low_20) / closes[-1] if closes[-1] != 0 else 0
        else:
            features['price_range_20'] = 0
        
        # Keltner Channel Width (ATR-based)
        features['keltner_width'] = features.get('atr_14', 0) / closes[-1] if closes[-1] != 0 else 0
        
        return features
    
    def _volume_features(self, volumes) -> Dict:
        """Volume analysis features."""
        features = {}
        
        # Volume moving averages
        features['volume_ma_5'] = np.mean(volumes[-5:]) if len(volumes) >= 5 else volumes[-1]
        features['volume_ma_20'] = np.mean(volumes[-20:]) if len(volumes) >= 20 else volumes[-1]
        
        # Volume surge
        if features['volume_ma_20'] > 0:
            features['volume_surge'] = volumes[-1] / features['volume_ma_20']
        else:
            features['volume_surge'] = 1.0
        
        # Volume trend (linear regression)
        if len(volumes) >= 20:
            x = np.arange(20)
            slope, _ = np.polyfit(x, volumes[-20:], 1)
            features['volume_trend_slope'] = slope / np.mean(volumes[-20:]) if np.mean(volumes[-20:]) > 0 else 0
        else:
            features['volume_trend_slope'] = 0
        
        # On-Balance Volume (OBV) approximation
        # Simplified: just volume direction
        features['volume_direction'] = 1.0 if len(volumes) >= 2 and volumes[-1] > volumes[-2] else -1.0
        
        return features
    
    def _pattern_features(self, closes, highs, lows) -> Dict:
        """Candlestick pattern recognition."""
        features = {}
        
        # Higher highs / lower lows
        if len(highs) >= 5:
            features['higher_highs'] = 1.0 if all(highs[-i] >= highs[-(i+1)] for i in range(1, min(5, len(highs)))) else 0.0
            features['lower_lows'] = 1.0 if all(lows[-i] <= lows[-(i+1)] for i in range(1, min(5, len(lows)))) else 0.0
        else:
            features['higher_highs'] = 0.0
            features['lower_lows'] = 0.0
        
        # Support/Resistance proximity
        if len(closes) >= 50:
            recent_high = np.max(closes[-50:])
            recent_low = np.min(closes[-50:])
            features['distance_from_high'] = (recent_high - closes[-1]) / closes[-1] if closes[-1] != 0 else 0
            features['distance_from_low'] = (closes[-1] - recent_low) / closes[-1] if closes[-1] != 0 else 0
        else:
            features['distance_from_high'] = 0
            features['distance_from_low'] = 0
        
        # Consecutive up/down candles
        if len(closes) >= 5:
            consecutive_up = sum(1 for i in range(1, 5) if closes[-i] > closes[-(i+1)])
            features['consecutive_direction'] = consecutive_up / 4.0  # Normalize
        else:
            features['consecutive_direction'] = 0.5
        
        return features
    
    def _orderbook_features(self, orderbook: Dict) -> Dict:
        """Order book depth features."""
        features = {}
        
        try:
            bids = orderbook.get('bids', [])[:10]  # Top 10 levels
            asks = orderbook.get('asks', [])[:10]
            
            bid_volume = sum(float(b[1]) for b in bids if len(b) >= 2)
            ask_volume = sum(float(a[1]) for a in asks if len(a) >= 2)
            
            # Bid/ask ratio
            features['bid_ask_ratio'] = bid_volume / ask_volume if ask_volume > 0 else 1.0
            
            # Book imbalance
            total_volume = bid_volume + ask_volume
            features['book_imbalance'] = (bid_volume - ask_volume) / total_volume if total_volume > 0 else 0.0
            
            # Spread
            if bids and asks:
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                features['spread_pct'] = (best_ask - best_bid) / best_bid if best_bid > 0 else 0.0
            else:
                features['spread_pct'] = 0.0
            
            # Depth ratio (close levels vs far levels)
            if len(bids) >= 5 and len(asks) >= 5:
                close_bid_vol = sum(float(b[1]) for b in bids[:3])
                far_bid_vol = sum(float(b[1]) for b in bids[3:6])
                features['depth_ratio'] = close_bid_vol / far_bid_vol if far_bid_vol > 0 else 1.0
            else:
                features['depth_ratio'] = 1.0
        
        except Exception as e:
            log(f"[FEATURE_ENG] Order book feature error: {e}", level='debug')
            features = {
                'bid_ask_ratio': 1.0,
                'book_imbalance': 0.0,
                'spread_pct': 0.0,
                'depth_ratio': 1.0
            }
        
        return features
    
    def _market_context_features(self, market: str, market_stats: Optional[Dict]) -> Dict:
        """Market-specific context features."""
        features = {}
        
        # Historical performance stats
        if market_stats:
            features['historical_win_rate'] = market_stats.get('win_rate', 0.5)
            features['avg_profit_pct'] = market_stats.get('avg_profit', 0.0)
            features['consecutive_losses'] = market_stats.get('consecutive_losses', 0) / 10.0  # Normalize
            features['trade_count'] = min(market_stats.get('trade_count', 0) / 100.0, 1.0)  # Cap at 100
        else:
            features['historical_win_rate'] = 0.5
            features['avg_profit_pct'] = 0.0
            features['consecutive_losses'] = 0.0
            features['trade_count'] = 0.0
        
        # Market tier (majors vs alts)
        major_markets = ['BTC-EUR', 'ETH-EUR', 'BNB-EUR', 'SOL-EUR', 'XRP-EUR']
        features['is_major'] = 1.0 if market in major_markets else 0.0
        
        # Time-based context
        now = datetime.now()
        features['is_weekend'] = 1.0 if now.weekday() >= 5 else 0.0
        features['is_night'] = 1.0 if now.hour < 6 or now.hour >= 22 else 0.0
        
        # Quarter of day
        features['quarter_of_day'] = now.hour // 6 / 4.0  # 0-1 normalized
        
        return features
    
    def _calculate_rsi(self, prices, period=14) -> float:
        """Calculate RSI indicator."""
        if len(prices) < period + 1:
            return 50.0
        
        deltas = np.diff(prices[-period-1:])
        gains = np.where(deltas > 0, deltas, 0).sum() / period
        losses = np.where(deltas < 0, -deltas, 0).sum() / period
        
        if losses == 0:
            return 100.0
        
        rs = gains / losses
        rsi = 100 - (100 / (1 + rs))
        return float(rsi)
    
    def _calculate_macd(self, prices, fast=12, slow=26, signal=9) -> Tuple[float, float, float]:
        """Calculate MACD indicator."""
        if len(prices) < slow + signal:
            return 0.0, 0.0, 0.0
        
        ema_fast = self._calculate_ema(prices, fast)
        ema_slow = self._calculate_ema(prices, slow)
        macd_line = ema_fast - ema_slow
        
        # Approximate signal line (simplified)
        macd_values = [ema_fast - ema_slow]  # Simplified
        signal_line = macd_line * 0.9  # Approximation
        histogram = macd_line - signal_line
        
        return macd_line, signal_line, histogram
    
    def _calculate_ema(self, prices, period) -> float:
        """Calculate Exponential Moving Average."""
        if len(prices) < period:
            return float(prices[-1]) if len(prices) > 0 else 0.0
        
        multiplier = 2 / (period + 1)
        ema = prices[-period]
        
        for price in prices[-(period-1):]:
            ema = (price - ema) * multiplier + ema
        
        return float(ema)
    
    def _calculate_bollinger_bands(self, prices, period=20, std_dev=2) -> Tuple[float, float, float, float]:
        """Calculate Bollinger Bands."""
        if len(prices) < period:
            return prices[-1], prices[-1], prices[-1], 0.0
        
        sma = np.mean(prices[-period:])
        std = np.std(prices[-period:])
        
        upper = sma + (std_dev * std)
        lower = sma - (std_dev * std)
        width = (upper - lower) / sma if sma != 0 else 0
        
        return float(upper), float(sma), float(lower), float(width)
    
    def _calculate_atr(self, highs, lows, closes, period=14) -> float:
        """Calculate Average True Range."""
        if len(closes) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(-period, 0):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i-1]),
                abs(lows[i] - closes[i-1])
            )
            true_ranges.append(tr)
        
        return float(np.mean(true_ranges))
    
    def _get_default_features(self) -> Dict[str, float]:
        """Return default feature values when insufficient data."""
        return {f'feature_{i}': 0.0 for i in range(55)}  # 55 default features
    
    def get_feature_names(self) -> List[str]:
        """Get list of feature names in order."""
        return self.feature_names


def main():
    """Test feature engineering."""
    engineer = AdvancedFeatureEngineer()
    
    # Generate sample candles
    sample_candles = [
        {'close': 100 + i, 'high': 102 + i, 'low': 98 + i, 'volume': 1000 + i*10}
        for i in range(100)
    ]
    
    features = engineer.engineer_features(sample_candles, market='BTC-EUR')
    
    print(f"Generated {len(features)} features:")
    for name, value in list(features.items())[:10]:
        print(f"  {name}: {value:.4f}")
    print("  ...")


if __name__ == "__main__":
    main()
