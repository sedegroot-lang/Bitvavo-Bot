"""
LSTM Price Prediction Module
Deep learning model voor cryptocurrency prijsvoorspelling
"""

import numpy as np
import json
import importlib
from pathlib import Path
from typing import List, Tuple, Optional
from modules.logging_utils import log

try:
    # Probeer eerst tensorflow.keras te laden voor maximale compatibiliteit
    _keras_backend = importlib.import_module("tensorflow").keras
    _backend_label = "tensorflow.keras"
except ImportError:
    _keras_backend = None
    _backend_label = "keras"

if _keras_backend is None:
    try:
        _keras_backend = importlib.import_module("keras")
    except ImportError:
        _keras_backend = None

if _keras_backend is not None:
    Sequential = _keras_backend.models.Sequential
    load_model = _keras_backend.models.load_model
    LSTM = _keras_backend.layers.LSTM
    Dense = _keras_backend.layers.Dense
    Dropout = _keras_backend.layers.Dropout
    Adam = _keras_backend.optimizers.Adam
    TENSORFLOW_AVAILABLE = True
    log(f"Keras backend geladen via {_backend_label}", level='info')
else:
    TENSORFLOW_AVAILABLE = False
    log("TensorFlow/Keras niet beschikbaar. Installeer met: pip install tensorflow", level='warning')


class LSTMPricePredictor:
    """
    LSTM model voor prijsvoorspelling
    
    Input: Sequence van prijzen en indicatoren (lookback_window punten)
    Output: Voorspelde prijsbeweging (up/down/neutral)
    """
    
    def __init__(self, 
                 lookback_window: int = 60,
                 prediction_horizon: int = 5,
                 model_path: str = "models/lstm_price_model.h5"):
        """
        Args:
            lookback_window: Aantal historische datapunten voor voorspelling
            prediction_horizon: Hoeveel stappen vooruit voorspellen
            model_path: Pad naar opgeslagen model
        """
        if not TENSORFLOW_AVAILABLE:
            raise ImportError("TensorFlow is vereist voor LSTM predictor")
        
        self.lookback_window = lookback_window
        self.prediction_horizon = prediction_horizon
        self.model_path = Path(model_path)
        self.model = None
        self.scaler_params = None  # Voor normalisatie
        
        # Model configuratie
        self.features_count = 5  # price, volume, rsi, macd, bb_position
        
    def build_model(self):
        """Bouw LSTM architectuur"""
        model = Sequential([
            # Eerste LSTM laag met dropout
            LSTM(units=50, return_sequences=True, 
                 input_shape=(self.lookback_window, self.features_count)),
            Dropout(0.2),
            
            # Tweede LSTM laag
            LSTM(units=50, return_sequences=True),
            Dropout(0.2),
            
            # Derde LSTM laag
            LSTM(units=50, return_sequences=False),
            Dropout(0.2),
            
            # Dense layers
            Dense(units=25, activation='relu'),
            Dense(units=3, activation='softmax')  # 3 classes: DOWN, NEUTRAL, UP
        ])
        
        model.compile(
            optimizer=Adam(learning_rate=0.001),
            loss='categorical_crossentropy',
            metrics=['accuracy']
        )
        
        self.model = model
        log(f"LSTM model gebouwd: {self.lookback_window} lookback, {self.features_count} features")
        
    def normalize_data(self, data: np.ndarray, fit: bool = False) -> np.ndarray:
        """
        Normaliseer data naar [0, 1] range
        
        Args:
            data: Raw data array
            fit: Als True, bereken en sla normalisatie parameters op
        
        Returns: Genormaliseerde data
        """
        if fit or self.scaler_params is None:
            # Bereken min/max voor elke feature
            self.scaler_params = {
                'min': data.min(axis=(0, 1)),
                'max': data.max(axis=(0, 1))
            }
        
        min_vals = self.scaler_params['min']
        max_vals = self.scaler_params['max']
        
        # Voorkom deling door nul
        range_vals = max_vals - min_vals
        range_vals[range_vals == 0] = 1
        
        normalized = (data - min_vals) / range_vals
        
        return normalized
    
    def prepare_sequences(self, 
                         price_data: List[float],
                         volume_data: List[float],
                         rsi_data: List[float],
                         macd_data: List[float],
                         bb_position_data: List[float]) -> np.ndarray:
        """
        Bereid data voor als sequences voor LSTM
        
        Returns: Array van shape (n_samples, lookback_window, features_count)
        """
        # Combineer alle features
        all_data = np.column_stack([
            price_data,
            volume_data,
            rsi_data,
            macd_data,
            bb_position_data
        ])
        
        sequences = []
        for i in range(len(all_data) - self.lookback_window):
            seq = all_data[i:i + self.lookback_window]
            sequences.append(seq)
        
        sequences = np.array(sequences)
        
        return sequences
    
    def train(self, 
              X_train: np.ndarray, 
              y_train: np.ndarray,
              X_val: Optional[np.ndarray] = None,
              y_val: Optional[np.ndarray] = None,
              epochs: int = 50,
              batch_size: int = 32):
        """
        Train LSTM model
        
        Args:
            X_train: Training sequences (n_samples, lookback_window, features)
            y_train: Training labels (n_samples, 3) - one-hot encoded
            X_val: Validation sequences (optional)
            y_val: Validation labels (optional)
            epochs: Aantal training epochs
            batch_size: Batch grootte
        """
        if self.model is None:
            self.build_model()
        
        # Normaliseer data
        X_train_norm = self.normalize_data(X_train, fit=True)
        
        validation_data = None
        if X_val is not None and y_val is not None:
            X_val_norm = self.normalize_data(X_val, fit=False)
            validation_data = (X_val_norm, y_val)
        
        log(f"Training LSTM: {len(X_train)} samples, {epochs} epochs")
        
        history = self.model.fit(
            X_train_norm, y_train,
            validation_data=validation_data,
            epochs=epochs,
            batch_size=batch_size,
            verbose=1
        )
        
        log(f"Training compleet. Final accuracy: {history.history['accuracy'][-1]:.4f}")
        
        return history
    
    def predict(self, sequence: np.ndarray) -> Tuple[str, float]:
        """
        Voorspel prijsbeweging voor gegeven sequence
        
        Args:
            sequence: Input sequence (lookback_window, features_count)
        
        Returns: 
            - Voorspelling: 'UP', 'NEUTRAL', 'DOWN'
            - Confidence: probability van voorspelling
        """
        if self.model is None:
            log("Model niet geladen. Gebruik load_model() of train() eerst.", level='error')
            return ('NEUTRAL', 0.33)
        
        try:
            # Validate input array
            sequence = np.asarray(sequence, dtype=np.float32)
            
            # Handle different input shapes
            if sequence.ndim == 1:
                # Flat array - check if size matches expected dimensions
                expected_size = self.lookback_window * self.features_count
                if sequence.size != expected_size:
                    log(f"LSTM predict: Input size {sequence.size} != expected {expected_size}", level='debug')
                    return ('NEUTRAL', 0.33)
                sequence = sequence.reshape(1, self.lookback_window, self.features_count)
            elif sequence.ndim == 2:
                # (lookback_window, features_count) - add batch dimension
                if sequence.shape[0] != self.lookback_window or sequence.shape[1] != self.features_count:
                    log(f"LSTM predict: Shape {sequence.shape} != expected ({self.lookback_window}, {self.features_count})", level='debug')
                    return ('NEUTRAL', 0.33)
                sequence = sequence.reshape(1, self.lookback_window, self.features_count)
            elif sequence.ndim == 3:
                # Already (batch, lookback, features) - validate
                if sequence.shape[1] != self.lookback_window or sequence.shape[2] != self.features_count:
                    log(f"LSTM predict: Shape {sequence.shape} incompatible", level='debug')
                    return ('NEUTRAL', 0.33)
            else:
                log(f"LSTM predict: Unsupported ndim {sequence.ndim}", level='debug')
                return ('NEUTRAL', 0.33)
            
            # Normaliseer
            sequence_norm = self.normalize_data(sequence, fit=False)
        except Exception as e:
            log(f"LSTM reshape error: {e}", level='debug')
            return ('NEUTRAL', 0.33)
        
        # Voorspel
        prediction = self.model.predict(sequence_norm, verbose=0)[0]
        
        # Interpreteer resultaat
        class_idx = np.argmax(prediction)
        confidence = float(prediction[class_idx])
        
        classes = ['DOWN', 'NEUTRAL', 'UP']
        predicted_class = classes[class_idx]
        
        return (predicted_class, confidence)
    
    def predict_price_change(self, sequence: np.ndarray) -> float:
        """
        Voorspel verwachte prijsverandering percentage
        
        Returns: Verwachte % verandering (-100 tot +100)
        """
        prediction, confidence = self.predict(sequence)
        
        # Map voorspelling naar percentage
        if prediction == 'UP':
            return confidence * 2.0  # Max +2% verwacht
        elif prediction == 'DOWN':
            return -confidence * 2.0  # Max -2% verwacht
        else:
            return 0.0
    
    def save_model(self):
        """Sla model en parameters op"""
        if self.model is None:
            log("Geen model om op te slaan", level='warning')
            return
        
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Sla Keras model op
        self.model.save(str(self.model_path))
        
        # Sla scaler parameters op
        scaler_path = self.model_path.with_suffix('.scaler.json')
        with open(scaler_path, 'w') as f:
            json.dump({
                'min': self.scaler_params['min'].tolist(),
                'max': self.scaler_params['max'].tolist(),
                'lookback_window': self.lookback_window,
                'features_count': self.features_count
            }, f)
        
        log(f"LSTM model opgeslagen naar {self.model_path}")
    
    def load_model(self):
        """Laad opgeslagen model en parameters"""
        if not self.model_path.exists():
            log(f"Model bestand niet gevonden: {self.model_path}", level='warning')
            return False
        
        try:
            # Laad Keras model
            self.model = load_model(str(self.model_path))
            
            # Laad scaler parameters
            scaler_path = self.model_path.with_suffix('.scaler.json')
            if scaler_path.exists():
                with open(scaler_path, 'r') as f:
                    data = json.load(f)
                    self.scaler_params = {
                        'min': np.array(data['min']),
                        'max': np.array(data['max'])
                    }
                    self.lookback_window = data.get('lookback_window', self.lookback_window)
                    self.features_count = data.get('features_count', self.features_count)
            
            log(f"LSTM model geladen van {self.model_path}")
            return True
            
        except Exception as e:
            log(f"Fout bij laden model: {e}", level='error')
            return False


def create_labels_from_prices(prices: List[float], 
                              horizon: int = 5,
                              threshold: float = 0.5) -> np.ndarray:
    """
    Maak training labels van prijzen
    
    Args:
        prices: Lijst van prijzen
        horizon: Hoeveel stappen vooruit kijken
        threshold: % threshold voor UP/DOWN classificatie
    
    Returns: One-hot encoded labels (n_samples, 3)
    """
    labels = []
    
    for i in range(len(prices) - horizon):
        current_price = prices[i]
        future_price = prices[i + horizon]
        
        pct_change = ((future_price - current_price) / current_price) * 100
        
        if pct_change > threshold:
            label = [0, 0, 1]  # UP
        elif pct_change < -threshold:
            label = [1, 0, 0]  # DOWN
        else:
            label = [0, 1, 0]  # NEUTRAL
        
        labels.append(label)
    
    return np.array(labels)
