"""
ONE-COMMAND ML SETUP & AUTO-RETRAIN ACTIVATION
Run this once to set up automated ML retraining.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import subprocess
import time
from datetime import datetime

def run_command(cmd, description):
    """Run command and show progress."""
    print(f"\n{'='*60}")
    print(f"[SETUP] {description}")
    print(f"{'='*60}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(result.stdout)
        print(f"✅ {description} - SUCCESS")
        return True
    else:
        print(result.stdout)
        print(result.stderr)
        print(f"❌ {description} - FAILED")
        return False

def main():
    print("\n" + "="*60)
    print("ML AUTO-RETRAIN SETUP")
    print("="*60)
    print("\nThis will:")
    print("1. Extract training data from your trade history")
    print("2. Train initial ML model")
    print("3. Enable automated retraining (weekly + on-demand)")
    print("\nEstimated time: 2-3 minutes")
    print("="*60)
    
    input("\nPress ENTER to start...")
    
    base_dir = Path(__file__).parent.parent
    python_exe = base_dir / ".venv" / "Scripts" / "python.exe"
    
    # Step 1: Extract data
    success = run_command(
        f'cd "{base_dir}" && "{python_exe}" scripts/ml/extract_training_data.py --source trade_log',
        "Step 1/2: Extracting training data"
    )
    
    if not success:
        print("\n❌ Setup failed at data extraction")
        return
    
    # Step 2: Train model
    success = run_command(
        f'cd "{base_dir}" && "{python_exe}" scripts/ml/train_models.py --data ai/training_data/*.csv',
        "Step 2/2: Training ML model"
    )
    
    if not success:
        print("\n❌ Setup failed at model training")
        return
    
    # Summary
    print("\n" + "="*60)
    print("✅ ML AUTO-RETRAIN SETUP COMPLETE!")
    print("="*60)
    print("\nWhat's configured:")
    print("• ML model trained and saved to ai/ai_xgb_model.json")
    print("• Auto-retrain ENABLED in config (AI_AUTO_RETRAIN_ENABLED=true)")
    print("• Schedule: Weekly check every Sunday at 02:00")
    print("• Triggers: Model >7 days old OR accuracy <55% OR 50+ new trades")
    print("\nThe bot will automatically:")
    print("• Check on startup if retraining needed")
    print("• Retrain weekly (Sunday 02:00)")
    print("• Retrain when performance drops")
    print("\nManual retraining:")
    print(f'  python ai/auto_retrain.py --force')
    print("\nCheck retraining schedule:")
    print(f'  python ai/ml_scheduler.py --once')
    print("\n✅ You're all set! Bot will handle ML updates automatically.")
    print("="*60)

if __name__ == '__main__':
    main()
