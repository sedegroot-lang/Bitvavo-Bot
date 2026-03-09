"""
Offline RL Training Script
Train RL model op historische trade data zonder live trading
"""

import sys
import json
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.reinforcement_learning import AdaptiveTradingAgent
from modules.trade_archive import get_all_trades
from datetime import datetime


def train_rl_from_history():
    """Train RL agent op historische trades"""
    
    print("=== OFFLINE RL TRAINING ===\n")
    
    # Load historical trades
    print("Loading trade archive...")
    trades = get_all_trades(exclude_sync_removed=True)
    
    if len(trades) < 50:
        print(f"ERROR: Niet genoeg trades voor training ({len(trades)} < 50)")
        return
    
    print(f"Found {len(trades)} trades for training\n")
    
    # Initialize RL agent in training mode
    agent = AdaptiveTradingAgent()
    agent.training_mode = True
    
    # Sort trades by timestamp
    trades.sort(key=lambda t: t.get('timestamp', 0))
    
    # Training statistics
    total_learned = 0
    positive_rewards = 0
    negative_rewards = 0
    
    print("Training RL agent...")
    print("-" * 60)
    
    for i, trade in enumerate(trades):
        # Construct market state at entry
        # (In real scenario, we'd have full market data, here we approximate)
        entry_state = {
            'trend': 'bullish' if trade.get('profit', 0) > 0 else 'bearish',
            'volatility': 0.02,  # Approximation
            'rsi': 45,  # Approximation
            'has_position': False
        }
        
        # Construct market state at exit
        exit_state = {
            'trend': 'bullish' if trade.get('profit', 0) > 0 else 'bearish',
            'volatility': 0.02,
            'rsi': 55 if trade.get('profit', 0) > 0 else 35,
            'has_position': True
        }
        
        # Calculate P/L percentage
        buy_price = trade.get('buy_price', 0)
        sell_price = trade.get('sell_price', 0)
        
        if buy_price > 0:
            pnl_pct = ((sell_price - buy_price) / buy_price) * 100
        else:
            pnl_pct = 0
        
        # Estimate hold duration (12 hours average)
        hold_hours = 12.0
        
        # Learn from this trade
        agent.learn_from_trade(
            entry_state=entry_state,
            action='BUY',
            exit_state=exit_state,
            pnl_pct=pnl_pct,
            hold_hours=hold_hours
        )
        
        total_learned += 1
        
        if pnl_pct > 0:
            positive_rewards += 1
        else:
            negative_rewards += 1
        
        # Progress indicator
        if (i + 1) % 20 == 0:
            print(f"Processed {i + 1}/{len(trades)} trades...")
    
    print("-" * 60)
    print("\nTraining complete!")
    print(f"\nStatistics:")
    print(f"  - Trades learned from: {total_learned}")
    print(f"  - Positive examples: {positive_rewards} ({positive_rewards/total_learned*100:.1f}%)")
    print(f"  - Negative examples: {negative_rewards} ({negative_rewards/total_learned*100:.1f}%)")
    
    # Experience replay for better learning
    print("\nPerforming experience replay...")
    for _ in range(10):  # 10 replay iterations
        agent.agent.replay_experience(batch_size=32)
    
    # Save trained model
    print("\nSaving model...")
    agent.save_model()
    
    # Check if model was saved
    model_path = Path("models/q_table.json")
    if model_path.exists():
        model_size = model_path.stat().st_size / 1024
        print(f"✓ Model saved: {model_path} ({model_size:.1f} KB)")
        
        # Show some Q-values
        print("\nExample Q-values learned:")
        with open(model_path, 'r') as f:
            q_table = json.load(f)
        
        # Show first 5 states
        for i, (state, actions) in enumerate(list(q_table.items())[:5]):
            best_action = max(actions, key=actions.get)
            print(f"  State: {state}")
            print(f"    → Best action: {best_action} (Q={actions[best_action]:.2f})")
    else:
        print("✗ ERROR: Model not saved!")
    
    print("\n=== TRAINING COMPLETE ===")
    print("\nNext steps:")
    print("1. Check bot_config.json:")
    print("   - RL_ENABLED: true")
    print("   - RL_TRAINING_MODE: false (gebruik getraind model)")
    print("2. Restart bot to use trained model")
    print("3. Monitor performance for 24-48 hours")


if __name__ == "__main__":
    train_rl_from_history()
