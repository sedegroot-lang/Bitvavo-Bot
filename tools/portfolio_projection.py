"""
Portfolio Value Projection Calculator
Generates realistic growth scenarios based on current balance and trading parameters
"""
import json
from typing import Dict, List
from datetime import datetime, timedelta


def calculate_portfolio_projection(
    current_balance: float,
    config: Dict,
    days: int = 30,
    win_rate: float = 0.60,  # 60% win rate (aggressive realistic)
    avg_profit_pct: float = 3.5,  # Average profit per winning trade
    avg_loss_pct: float = -1.5,  # Average loss per losing trade
    trades_per_day: float = 1.5,  # With aggressive params + restrictive filters
) -> Dict:
    """
    Calculate realistic portfolio projection scenarios.
    
    Args:
        current_balance: Starting EUR balance
        config: Bot configuration dict
        days: Projection period in days
        win_rate: Percentage of winning trades (0.0-1.0)
        avg_profit_pct: Average profit % for winning trades
        avg_loss_pct: Average loss % for losing trades (negative)
        trades_per_day: Expected trade frequency
    
    Returns:
        Dict with scenarios: conservative, realistic, optimistic
    """
    max_open_trades = int(config.get('MAX_OPEN_TRADES', 5))
    base_amount = float(config.get('BASE_AMOUNT_EUR', 35.0))
    max_eur_per_trade = float(config.get('MAX_EUR_PER_TRADE', 35.0))
    
    # Calculate expected value per trade
    expected_value_pct = (win_rate * avg_profit_pct) + ((1 - win_rate) * avg_loss_pct)
    
    # Scenarios
    scenarios = {
        'conservative': {
            'win_rate': win_rate - 0.10,  # 50% win rate
            'avg_profit_pct': avg_profit_pct * 0.8,  # 2.8% avg profit
            'trades_per_day': trades_per_day * 0.6,  # 0.9 trades/day
            'label': 'Conservatief (Bear Market)',
        },
        'realistic': {
            'win_rate': win_rate,  # 60% win rate
            'avg_profit_pct': avg_profit_pct,  # 3.5% avg profit
            'trades_per_day': trades_per_day,  # 1.5 trades/day
            'label': 'Realistisch (Current Market)',
        },
        'optimistic': {
            'win_rate': win_rate + 0.10,  # 70% win rate
            'avg_profit_pct': avg_profit_pct * 1.3,  # 4.55% avg profit
            'trades_per_day': trades_per_day * 1.4,  # 2.1 trades/day
            'label': 'Optimistisch (Bull Market)',
        },
    }
    
    results = {}
    
    for scenario_name, params in scenarios.items():
        balance = current_balance
        wr = params['win_rate']
        profit_pct = params['avg_profit_pct']
        trades_pd = params['trades_per_day']
        
        # Calculate expected value for this scenario
        ev_pct = (wr * profit_pct) + ((1 - wr) * avg_loss_pct)
        
        # Daily projections
        daily_balance = [balance]
        total_trades = 0
        winning_trades = 0
        losing_trades = 0
        
        for day in range(days):
            # Trades for this day
            expected_trades = trades_pd
            
            # Simulate trades
            for _ in range(int(expected_trades)):
                if balance < base_amount + 10:  # MIN_BALANCE_RESERVE check
                    break
                
                trade_amount = min(max_eur_per_trade, balance * 0.15)  # Max 15% per trade
                
                # Win or loss based on win rate
                if total_trades == 0 or (winning_trades / (total_trades + 1)) < wr:
                    # Winning trade
                    profit = trade_amount * (profit_pct / 100)
                    balance += profit
                    winning_trades += 1
                else:
                    # Losing trade
                    loss = trade_amount * (avg_loss_pct / 100)
                    balance += loss  # loss is negative
                    losing_trades += 1
                
                total_trades += 1
            
            daily_balance.append(balance)
        
        # Calculate statistics
        total_return_pct = ((balance - current_balance) / current_balance) * 100
        daily_return_pct = (total_return_pct / days) if days > 0 else 0
        
        results[scenario_name] = {
            'label': params['label'],
            'starting_balance': current_balance,
            'ending_balance': round(balance, 2),
            'total_return_eur': round(balance - current_balance, 2),
            'total_return_pct': round(total_return_pct, 2),
            'daily_return_pct': round(daily_return_pct, 3),
            'expected_trades': int(trades_pd * days),
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'actual_win_rate': round(winning_trades / total_trades, 3) if total_trades > 0 else 0,
            'daily_balance': [round(b, 2) for b in daily_balance],
            'parameters': {
                'win_rate': wr,
                'avg_profit_pct': profit_pct,
                'avg_loss_pct': avg_loss_pct,
                'trades_per_day': trades_pd,
                'expected_value_pct': round(ev_pct, 3),
            }
        }
    
    return {
        'projection_date': datetime.now().isoformat(),
        'projection_days': days,
        'current_balance': current_balance,
        'config': {
            'MAX_OPEN_TRADES': max_open_trades,
            'BASE_AMOUNT_EUR': base_amount,
            'MAX_EUR_PER_TRADE': max_eur_per_trade,
        },
        'scenarios': results,
    }


def format_projection_summary(projection: Dict) -> str:
    """Format projection results as readable summary."""
    lines = []
    lines.append("=" * 80)
    lines.append(f"PORTFOLIO PROJECTIE - {projection['projection_days']} dagen")
    lines.append(f"Startbalans: €{projection['current_balance']:.2f}")
    lines.append("=" * 80)
    lines.append("")
    
    for scenario_name in ['conservative', 'realistic', 'optimistic']:
        result = projection['scenarios'][scenario_name]
        lines.append(f"📊 {result['label']}")
        lines.append(f"   Eindbalans:      €{result['ending_balance']:.2f}")
        lines.append(f"   Totaal rendement: €{result['total_return_eur']:.2f} ({result['total_return_pct']:+.2f}%)")
        lines.append(f"   Dag rendement:   {result['daily_return_pct']:+.3f}%")
        lines.append(f"   Trades:          {result['total_trades']} ({result['winning_trades']}W / {result['losing_trades']}L)")
        lines.append(f"   Win rate:        {result['actual_win_rate']*100:.1f}%")
        lines.append(f"   EV per trade:    {result['parameters']['expected_value_pct']:+.3f}%")
        lines.append("")
    
    lines.append("=" * 80)
    lines.append("Parameters:")
    lines.append(f"  MAX_OPEN_TRADES: {projection['config']['MAX_OPEN_TRADES']}")
    lines.append(f"  BASE_AMOUNT_EUR: €{projection['config']['BASE_AMOUNT_EUR']}")
    lines.append(f"  MAX_EUR_PER_TRADE: €{projection['config']['MAX_EUR_PER_TRADE']}")
    lines.append("=" * 80)
    
    return "\n".join(lines)


if __name__ == "__main__":
    # Load current config
    with open("config/bot_config.json", "r", encoding="utf-8") as f:
        config = json.load(f)
    
    # Current balance (from user)
    current_balance = 104.03
    
    # Generate projections
    projection_30d = calculate_portfolio_projection(current_balance, config, days=30)
    projection_90d = calculate_portfolio_projection(current_balance, config, days=90)
    
    # Print summaries
    print(format_projection_summary(projection_30d))
    print("\n")
    print(format_projection_summary(projection_90d))
    
    # Save to file
    with open("data/portfolio_projection.json", "w", encoding="utf-8") as f:
        json.dump({
            '30_days': projection_30d,
            '90_days': projection_90d,
        }, f, indent=2)
    
    print("\n✅ Projection saved to: data/portfolio_projection.json")
