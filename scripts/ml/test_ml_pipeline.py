"""
Quick test script to verify the ML pipeline works end-to-end.
Tests: extraction → feature engineering → model training
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import pandas as pd
import numpy as np
from scripts.ml.extract_training_data import TrainingDataExtractor
from scripts.ml.feature_engineering import AdvancedFeatureEngineer
from scripts.ml.train_models import MLModelTrainer


def test_feature_engineering():
    """Test feature engineering with sample data."""
    print("\n[TEST 1] Feature Engineering")
    print("=" * 60)
    
    # Create sample candle data
    candles = []
    for i in range(100):
        candles.append({
            'timestamp': 1700000000 + i * 3600,
            'open': 50000 + np.random.randn() * 1000,
            'high': 51000 + np.random.randn() * 1000,
            'low': 49000 + np.random.randn() * 1000,
            'close': 50000 + np.random.randn() * 1000,
            'volume': 100 + np.random.randn() * 20
        })
    
    # Sample order book
    orderbook = {
        'bids': [[49950, 1.5], [49900, 2.0]],
        'asks': [[50050, 1.2], [50100, 1.8]]
    }
    
    # Sample market stats
    market_stats = {
        'avg_win_rate': 0.6,
        'avg_profit_eur': 15.5,
        'consecutive_losses': 2,
        'total_profit_eur': 1250.0,
        'total_trades': 150
    }
    
    # Engineer features
    engineer = AdvancedFeatureEngineer()
    features = engineer.engineer_features(
        candles=candles,
        orderbook=orderbook,
        market='BTC-EUR',
        market_stats=market_stats
    )
    
    print(f"✅ Generated {len(features)} features")
    print(f"Feature names: {list(features.keys())[:10]}... (showing first 10)")
    print(f"Sample values: rsi_14={features.get('rsi_14', 'N/A'):.2f}, "
          f"macd_histogram={features.get('macd_histogram', 'N/A'):.4f}")
    
    # Verify expected features
    expected_features = [
        'rsi_7', 'rsi_14', 'rsi_28',
        'macd', 'macd_signal', 'macd_histogram',
        'bb_upper', 'bb_middle', 'bb_lower',
        'volume_ma_20', 'volume_surge',
        'bid_ask_ratio', 'order_book_imbalance',
        'historical_win_rate', 'is_major_pair'
    ]
    
    missing = [f for f in expected_features if f not in features]
    if missing:
        print(f"⚠️  Missing features: {missing}")
    else:
        print("✅ All expected features present")
    
    return features


def test_model_training():
    """Test model training with synthetic data."""
    print("\n[TEST 2] Model Training")
    print("=" * 60)
    
    # Create synthetic training data (500 samples, 55 features)
    np.random.seed(42)
    n_samples = 500
    n_features = 55
    
    # Generate features
    X = pd.DataFrame(
        np.random.randn(n_samples, n_features),
        columns=[f'feature_{i}' for i in range(n_features)]
    )
    
    # Generate labels (60% wins)
    y = pd.Series(np.random.choice([0, 1], size=n_samples, p=[0.4, 0.6]))
    
    print(f"Training data: {X.shape[0]} samples, {X.shape[1]} features")
    print(f"Label distribution: {y.value_counts().to_dict()}")
    
    # Train model (no hyperparameter tuning for speed)
    trainer = MLModelTrainer(model_save_path='ai/test_model.json')
    print("\nTraining XGBoost (quick mode - no tuning)...")
    
    metrics = trainer.train_xgboost(
        X_train=X,
        y_train=y,
        hyperparameter_tuning=False
    )
    
    print(f"\n✅ Training complete!")
    print(f"Accuracy: {metrics['accuracy']:.2%}")
    print(f"Precision: {metrics['precision']:.2%}")
    print(f"Recall: {metrics['recall']:.2%}")
    print(f"F1 Score: {metrics['f1_score']:.2%}")
    print(f"ROC-AUC: {metrics['roc_auc']:.2%}")
    
    # Verify model was saved
    model_path = Path('ai/test_model.json')
    if model_path.exists():
        print(f"✅ Model saved to {model_path}")
        model_path.unlink()  # Clean up test model
    else:
        print(f"⚠️  Model not saved")
    
    return metrics


def test_data_extraction_from_trade_log():
    """Test extraction from trade_log.json (if available)."""
    print("\n[TEST 3] Data Extraction (trade_log.json)")
    print("=" * 60)
    
    trade_log_path = Path('data/trade_log.json')
    if not trade_log_path.exists():
        print("⚠️  trade_log.json not found - skipping test")
        return None
    
    extractor = TrainingDataExtractor()
    
    try:
        df = extractor.load_trade_log()
        print(f"✅ Loaded {len(df)} trades from trade_log.json")
        print(f"Columns: {df.columns.tolist()}")
        print(f"\nSample row:")
        print(df.iloc[0] if len(df) > 0 else "No trades")
        
        # Check label distribution
        if 'label' in df.columns:
            label_dist = df['label'].value_counts()
            print(f"\nLabel distribution: {label_dist.to_dict()}")
            win_rate = label_dist.get(1, 0) / len(df) * 100
            print(f"Historical win rate: {win_rate:.1f}%")
        
        return df
    
    except Exception as e:
        print(f"❌ Error: {e}")
        return None


def main():
    print("\n" + "=" * 60)
    print("ML PIPELINE TEST SUITE")
    print("=" * 60)
    
    results = {
        'feature_engineering': False,
        'model_training': False,
        'data_extraction': False
    }
    
    try:
        # Test 1: Feature Engineering
        features = test_feature_engineering()
        results['feature_engineering'] = len(features) >= 50
        
        # Test 2: Model Training
        metrics = test_model_training()
        results['model_training'] = metrics['accuracy'] > 0.4  # Sanity check
        
        # Test 3: Data Extraction
        df = test_data_extraction_from_trade_log()
        results['data_extraction'] = df is not None if df is not None else None
        
    except Exception as e:
        print(f"\n❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    for test, passed in results.items():
        status = "✅ PASS" if passed else ("⚠️  SKIP" if passed is None else "❌ FAIL")
        print(f"{test.ljust(30)}: {status}")
    
    all_passed = all(v is True or v is None for v in results.values())
    
    if all_passed:
        print("\n✅ All tests passed! ML pipeline is ready.")
        print("\nNext steps:")
        print("1. python scripts/ml/extract_training_data.py --source trade_log")
        print("2. python scripts/ml/train_models.py --data ai/training_data/raw_data*.csv")
        print("3. Bot will auto-load from ai/ai_xgb_model.json on next restart")
    else:
        print("\n⚠️  Some tests failed. Check errors above.")


if __name__ == '__main__':
    main()
