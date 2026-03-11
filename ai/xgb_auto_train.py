import xgboost as xgb
import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import os

from modules.config import load_config

# Automatische retraining en model update
DATA_FILE = "trade_features.csv"

try:
    _cfg = load_config()
except Exception:
    _cfg = {}

MODEL_FILE = _cfg.get("XGB_MODEL_PATH") or _cfg.get("MODEL_PATH") or "ai/ai_xgb_model.json"

# 1. Laad of genereer data
if os.path.exists(DATA_FILE):
    df = pd.read_csv(DATA_FILE)
else:
    # Dummy data als voorbeeld
    df = pd.DataFrame({
        'rsi': np.random.uniform(20, 80, 100),
        'macd': np.random.uniform(-0.5, 0.5, 100),
        'sma_short': np.random.uniform(90, 120, 100),
        'sma_long': np.random.uniform(90, 120, 100),
        'volume': np.random.uniform(500, 3000, 100),
        'label': np.random.randint(0, 2, 100)
    })
    df.to_csv(DATA_FILE, index=False)

X = df[['rsi', 'macd', 'sma_short', 'sma_long', 'volume']].values
y = df['label'].values

# 2. Split data en train model
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
model = xgb.XGBClassifier(use_label_encoder=False, eval_metric='logloss')
model.fit(X_train, y_train)

# 3. Evaluatie
preds = model.predict(X_test)
acc = accuracy_score(y_test, preds)
print(f"Model accuracy: {acc:.2f}")

# 4. Sla model op
model.save_model(MODEL_FILE)
print(f"Model opgeslagen als {MODEL_FILE}")

# 5. Automatische update functie

def update_model(new_data):
    global model, X, y
    df_new = pd.DataFrame(new_data)
    df_all = pd.concat([df, df_new], ignore_index=True)
    X = df_all[['rsi', 'macd', 'sma_short', 'sma_long', 'volume']].values
    y = df_all['label'].values
    model.fit(X, y)
    model.save_model(MODEL_FILE)
    print("Model automatisch geüpdatet!")

# Voorbeeld van automatische update:
# new_data = [{"rsi": 60, "macd": 0.1, "sma_short": 110, "sma_long": 108, "volume": 2000, "label": 1}]
# update_model(new_data)
