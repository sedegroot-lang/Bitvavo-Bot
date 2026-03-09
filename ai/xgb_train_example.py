import xgboost as xgb
import numpy as np
import pandas as pd

from modules.config import load_config

try:
    _cfg = load_config()
except Exception:
    _cfg = {}

MODEL_FILE = _cfg.get("XGB_MODEL_PATH") or _cfg.get("MODEL_PATH") or "ai_xgb_model.json"

# Dummy voorbeelddata: features en labels
# Vervang dit door je eigen historische trading data
# Features: RSI, MACD, SMA_short, SMA_long, Volume, etc.
data = {
    'rsi': [30, 70, 50, 60, 40],
    'macd': [0.1, -0.2, 0.05, 0.3, -0.1],
    'sma_short': [100, 105, 102, 110, 98],
    'sma_long': [99, 104, 101, 108, 97],
    'volume': [1000, 1500, 1200, 1800, 900],
    'label': [1, 0, 1, 1, 0]  # 1=koop, 0=geen koop
}
df = pd.DataFrame(data)

X = df[['rsi', 'macd', 'sma_short', 'sma_long', 'volume']].values
y = df['label'].values

# Train XGBoost model
model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss')
model.fit(X, y)

# Simuleer een nieuwe trade-feature
new_features = np.array([[55, 0.15, 107, 105, 1600]])
prediction = model.predict(new_features)[0]

if prediction == 1:
    print("Trading signal: BUY")
else:
    print("No buy signal")

# Sla het model op voor gebruik in je bot
model.save_model(MODEL_FILE)
print(f"Model opgeslagen als {MODEL_FILE}")
