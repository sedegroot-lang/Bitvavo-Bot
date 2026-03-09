"""
Train LSTM Price Prediction Model
Train deep learning model op historische prijsdata
"""

import sys
from pathlib import Path
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.ml_lstm import LSTMPricePredictor, create_labels_from_prices
from modules.logging_utils import log
from modules.trading import bitvavo


def fetch_historical_candles(market: str = 'BTC-EUR', 
                            interval: str = '5m',
                            limit: int = 1000) -> dict:
    """Haal historische candle data op van Bitvavo"""
    try:
        candles = bitvavo.candles(market, interval, limit=limit)
        return candles
    except Exception as e:
        log(f"Fout bij ophalen candles: {e}", level='error')
        return []


def prepare_training_data(candles: list, 
                          lookback_window: int = 60) -> tuple:
    """
    Bereid training data voor uit candles
    
    Args:
        candles: Lijst van candles [timestamp, open, high, low, close, volume]
        lookback_window: Aantal bars voor sequence
    
    Returns: (X_sequences, y_labels)
    """
    if len(candles) < lookback_window + 10:
        raise ValueError(f"Niet genoeg data: {len(candles)} candles")
    
    # Extract data
    closes = [float(c[4]) for c in candles]  # Close prices
    volumes = [float(c[5]) for c in candles]  # Volumes
    
    # Bereken technische indicatoren
    rsi_values = calculate_rsi(closes, period=14)
    macd_values = calculate_macd(closes)
    bb_positions = calculate_bb_position(closes, period=20)
    
    # Maak sequences
    price_data = closes[:-5]  # Exclusief laatste 5 voor labels
    volume_data = volumes[:-5]
    rsi_data = rsi_values[:-5]
    macd_data = macd_values[:-5]
    bb_data = bb_positions[:-5]
    
    predictor = LSTMPricePredictor(lookback_window=lookback_window)
    
    X_sequences = predictor.prepare_sequences(
        price_data=price_data,
        volume_data=volume_data,
        rsi_data=rsi_data,
        macd_data=macd_data,
        bb_position_data=bb_data
    )
    
    # Maak labels (kijk 5 bars vooruit)
    y_labels = create_labels_from_prices(closes, horizon=5, threshold=0.3)
    
    # Trim labels om te matchen met sequences
    y_labels = y_labels[:len(X_sequences)]
    
    return X_sequences, y_labels


def calculate_rsi(prices: list, period: int = 14) -> list:
    """Bereken RSI indicator"""
    rsi_values = []
    
    for i in range(len(prices)):
        if i < period:
            rsi_values.append(50.0)  # Default voor eerste waarden
            continue
        
        gains = []
        losses = []
        
        for j in range(i - period, i):
            change = prices[j + 1] - prices[j]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        
        if avg_loss == 0:
            rsi = 100
        else:
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
        
        rsi_values.append(rsi)
    
    return rsi_values


def calculate_macd(prices: list, fast: int = 12, slow: int = 26) -> list:
    """Bereken MACD indicator"""
    macd_values = []
    
    for i in range(len(prices)):
        if i < slow:
            macd_values.append(0.0)
            continue
        
        # Simple EMA approximatie
        fast_ema = sum(prices[i-fast:i]) / fast
        slow_ema = sum(prices[i-slow:i]) / slow
        
        macd = fast_ema - slow_ema
        macd_values.append(macd)
    
    return macd_values


def calculate_bb_position(prices: list, period: int = 20) -> list:
    """
    Bereken positie binnen Bollinger Bands (0-1)
    0 = op lower band, 0.5 = op middle, 1 = op upper band
    """
    bb_positions = []
    
    for i in range(len(prices)):
        if i < period:
            bb_positions.append(0.5)
            continue
        
        window = prices[i-period:i]
        sma = sum(window) / period
        std = np.std(window)
        
        upper_band = sma + (2 * std)
        lower_band = sma - (2 * std)
        
        current_price = prices[i]
        
        if upper_band == lower_band:
            position = 0.5
        else:
            position = (current_price - lower_band) / (upper_band - lower_band)
            position = max(0, min(1, position))  # Clip to [0, 1]
        
        bb_positions.append(position)
    
    return bb_positions


def train_lstm_model():
    """Hoofd training functie"""
    print("=" * 60)
    print("LSTM PRICE PREDICTION MODEL TRAINING")
    print("=" * 60)
    print()
    
    # Configuratie
    MARKET = 'BTC-EUR'
    INTERVAL = '5m'
    LIMIT = 1000
    LOOKBACK_WINDOW = 60
    EPOCHS = 50
    BATCH_SIZE = 32
    VALIDATION_SPLIT = 0.2
    
    print(f"Market: {MARKET}")
    print(f"Interval: {INTERVAL}")
    print(f"Data points: {LIMIT}")
    print(f"Lookback window: {LOOKBACK_WINDOW}")
    print()
    
    # 1. Fetch data
    print("Stap 1: Data ophalen van Bitvavo...")
    candles = fetch_historical_candles(MARKET, INTERVAL, LIMIT)
    
    if not candles:
        print("FOUT: Geen candle data ontvangen!")
        return
    
    print(f"✓ {len(candles)} candles opgehaald")
    print()
    
    # 2. Prepare training data
    print("Stap 2: Training data voorbereiden...")
    try:
        X_sequences, y_labels = prepare_training_data(candles, LOOKBACK_WINDOW)
        print(f"✓ {len(X_sequences)} sequences gemaakt")
        print(f"  - Sequence shape: {X_sequences.shape}")
        print(f"  - Labels shape: {y_labels.shape}")
        print()
    except Exception as e:
        print(f"FOUT bij data voorbereiding: {e}")
        return
    
    # 3. Split train/validation
    print("Stap 3: Train/validation split...")
    split_idx = int(len(X_sequences) * (1 - VALIDATION_SPLIT))
    
    X_train = X_sequences[:split_idx]
    y_train = y_labels[:split_idx]
    X_val = X_sequences[split_idx:]
    y_val = y_labels[split_idx:]
    
    print(f"✓ Training set: {len(X_train)} samples")
    print(f"✓ Validation set: {len(X_val)} samples")
    print()
    
    # 4. Create and train model
    print("Stap 4: LSTM model trainen...")
    predictor = LSTMPricePredictor(
        lookback_window=LOOKBACK_WINDOW,
        prediction_horizon=5
    )
    
    try:
        history = predictor.train(
            X_train=X_train,
            y_train=y_train,
            X_val=X_val,
            y_val=y_val,
            epochs=EPOCHS,
            batch_size=BATCH_SIZE
        )
        
        print()
        print("✓ Training compleet!")
        print()
        
        # Print resultaten
        final_train_acc = history.history['accuracy'][-1]
        final_val_acc = history.history['val_accuracy'][-1] if 'val_accuracy' in history.history else 0
        
        print(f"Final training accuracy: {final_train_acc:.4f}")
        print(f"Final validation accuracy: {final_val_acc:.4f}")
        print()
        
    except Exception as e:
        print(f"FOUT tijdens training: {e}")
        import traceback
        traceback.print_exc()
        return
    
    # 5. Save model
    print("Stap 5: Model opslaan...")
    try:
        predictor.save_model()
        print("✓ Model opgeslagen!")
        print()
    except Exception as e:
        print(f"FOUT bij opslaan model: {e}")
        return
    
    # 6. Test prediction
    print("Stap 6: Test predictie...")
    try:
        test_sequence = X_val[0]
        prediction, confidence = predictor.predict(test_sequence)
        
        print(f"Test voorspelling: {prediction} (confidence: {confidence:.2%})")
        print()
    except Exception as e:
        print(f"FOUT bij test predictie: {e}")
    
    print("=" * 60)
    print("TRAINING COMPLEET!")
    print("=" * 60)
    print()
    print("Om LSTM te gebruiken in de bot:")
    print("1. Voeg toe aan config.json:")
    print('   "USE_LSTM": true')
    print()
    print("2. Installeer TensorFlow (als nog niet gedaan):")
    print("   pip install tensorflow")
    print()
    print("3. Herstart de bot")


if __name__ == '__main__':
    train_lstm_model()
