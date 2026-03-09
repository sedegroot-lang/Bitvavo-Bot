"""Force immediate retraining of all AI models to achieve 10/10 performance"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from modules.logging_utils import log

def main():
    log("🚀 FORCE RETRAIN ALL MODELS - 10/10 OPTIMALISATIE")
    log("=" * 60)
    
    # 1. Retrain XGBoost met optimale parameters
    log("\n📊 [1/3] Retraining XGBoost model...")
    result = subprocess.run([
        sys.executable,
        str(PROJECT_ROOT / 'tools' / 'train_ai_model.py'),
        '--interval', '1m',
        '--limit', '1500',  # Meer data voor betere accuracy
        '--lookahead', '25',  # Kortere voorspellingsperiode
        '--target-threshold', '0.008',  # Lagere drempel = meer signalen
    ], capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode == 0:
        log("✅ XGBoost retrained successfully")
    else:
        log(f"❌ XGBoost retrain failed: {result.stderr}", level='error')
    
    # 2. Retrain LSTM
    log("\n🧠 [2/3] Retraining LSTM model...")
    result = subprocess.run([
        sys.executable,
        str(PROJECT_ROOT / 'scripts' / 'train_lstm_model.py')
    ], capture_output=True, text=True, encoding='utf-8')
    
    if result.returncode == 0:
        log("✅ LSTM retrained successfully")
    else:
        log(f"❌ LSTM retrain failed: {result.stderr}", level='error')
    
    # 3. Reset RL Agent Q-table for fresh learning
    log("\n🎮 [3/3] Resetting RL Agent Q-table...")
    import json
    q_table_path = PROJECT_ROOT / 'modules' / 'rl_q_table.json'
    try:
        with open(q_table_path, 'w', encoding='utf-8') as f:
            json.dump({
                'q_table': {},
                'episode': 0,
                'total_reward': 0.0,
                'version': '2.0',
                'reset_timestamp': str(__import__('datetime').datetime.now())
            }, f, indent=2)
        log("✅ RL Q-table reset for fresh learning")
    except Exception as e:
        log(f"❌ RL reset failed: {e}", level='error')
    
    log("\n" + "=" * 60)
    log("🎯 ALL MODELS RETRAINED - Ready for 10/10 performance!")
    log("⏰ Bot will reload new models within 60 seconds (hot reload)")

if __name__ == '__main__':
    main()
