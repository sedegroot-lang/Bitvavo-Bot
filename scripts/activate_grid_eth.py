"""
Grid Trading Activation Script for ETH-EUR

This script initializes and activates the ETH-EUR neutral range grid trading strategy.
It uses the GridManager from modules/grid_trading.py to create and start the grid.

Strategy Overview:
- Market: ETH-EUR
- Investment: €35.00
- Grid Levels: 12 (geometric spacing)
- Range: €2392.85 - €2643.25 (±5% from current price)
- Take Profit: 12%
- Stop Loss: 8%

Usage:
    python scripts/activate_grid_eth.py
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import json
from modules.grid_trading import GridManager
from modules.bitvavo_client import get_bitvavo
from modules.logging_utils import log


def activate_eth_grid():
    """Activate ETH-EUR grid trading strategy."""
    
    # Load strategy configuration
    config_path = project_root / 'config' / 'grid_strategy_eth.json'
    
    if not config_path.exists():
        log(f"ERROR: Strategy config not found at {config_path}", level='error')
        return False
    
    with open(config_path, 'r') as f:
        strategy = json.load(f)
    
    log("=" * 60)
    log("ETH-EUR GRID TRADING ACTIVATION")
    log("=" * 60)
    log(f"Market: {strategy['market']}")
    log(f"Investment: €{strategy['investment']['total_eur']:.2f}")
    log(f"Grid Levels: {strategy['grid_settings']['num_grids']}")
    log(f"Price Range: €{strategy['grid_settings']['lower_price']:.2f} - €{strategy['grid_settings']['upper_price']:.2f}")
    log(f"Current Price: €{strategy['grid_settings']['current_price']:.2f}")
    log(f"Take Profit: {strategy['advanced_settings']['take_profit_pct']}%")
    log(f"Stop Loss: {strategy['advanced_settings']['stop_loss_pct']}%")
    log("=" * 60)
    
    # Initialize Bitvavo client
    try:
        bitvavo = get_bitvavo()
        log("Bitvavo client initialized successfully")
    except Exception as e:
        log(f"ERROR: Failed to initialize Bitvavo client: {e}", level='error')
        return False
    
    # Initialize GridManager
    grid_manager = GridManager(bitvavo_client=bitvavo)
    
    # Extract parameters from strategy
    grid_settings = strategy['grid_settings']
    advanced = strategy['advanced_settings']
    investment = strategy['investment']['total_eur']
    
    # Create grid
    try:
        log("Creating grid configuration...")
        grid_state = grid_manager.create_grid(
            market='ETH-EUR',
            lower_price=grid_settings['lower_price'],
            upper_price=grid_settings['upper_price'],
            num_grids=grid_settings['num_grids'],
            total_investment=investment,
            grid_mode=grid_settings['grid_mode'],
            auto_rebalance=advanced['auto_rebalance'],
            stop_loss_pct=advanced['stop_loss_pct'] / 100.0,  # Convert % to decimal
            take_profit_pct=advanced['take_profit_pct'] / 100.0,
        )
        log("Grid configuration created successfully")
        
        # Display grid levels
        log("\nGrid Levels:")
        log("-" * 60)
        log(f"{'Level':<8} {'Price (EUR)':<15} {'Side':<8} {'Amount (ETH)':<15}")
        log("-" * 60)
        for level in grid_state.levels:
            log(f"{level.level_id:<8} {level.price:<15.2f} {level.side:<8} {level.amount:<15.8f}")
        log("-" * 60)
        
    except Exception as e:
        log(f"ERROR: Failed to create grid: {e}", level='error')
        return False
    
    # Start the grid
    try:
        log("\nStarting grid trading...")
        success = grid_manager.start_grid('ETH-EUR')
        
        if success:
            log("✓ Grid trading activated successfully!")
            log("\nNext Steps:")
            log("1. Monitor grid status in dashboard")
            log("2. Grid will automatically place orders as price moves")
            log("3. Profits accumulate from completed buy-sell cycles")
            log("4. Auto-rebalance enabled if price exits range")
            log("\nGrid will be managed by the main bot loop.")
            return True
        else:
            log("ERROR: Failed to start grid", level='error')
            return False
            
    except Exception as e:
        log(f"ERROR: Failed to start grid: {e}", level='error')
        return False


def display_grid_info():
    """Display current grid trading information."""
    grid_manager = GridManager()
    
    if 'ETH-EUR' in grid_manager.grids:
        state = grid_manager.grids['ETH-EUR']
        
        log("\n" + "=" * 60)
        log("CURRENT GRID STATUS")
        log("=" * 60)
        log(f"Market: {state.config.market}")
        log(f"Status: {state.status}")
        log(f"Total Profit: €{state.total_profit:.2f}")
        log(f"Total Trades: {state.total_trades}")
        log(f"Current Price: €{state.current_price:.2f}")
        log(f"Base Balance (ETH): {state.base_balance:.8f}")
        log(f"Quote Balance (EUR): €{state.quote_balance:.2f}")
        log(f"Rebalances: {state.rebalance_count}")
        log("=" * 60)
        
        # Count filled levels
        filled = sum(1 for level in state.levels if level.status == 'filled')
        pending = sum(1 for level in state.levels if level.status == 'pending')
        
        log(f"Grid Efficiency: {filled}/{len(state.levels)} levels filled ({filled/len(state.levels)*100:.1f}%)")
        log(f"Pending Orders: {pending}")
        log("=" * 60)
    else:
        log("No active grid found for ETH-EUR")


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='ETH-EUR Grid Trading Manager')
    parser.add_argument('--activate', action='store_true', help='Activate the grid strategy')
    parser.add_argument('--status', action='store_true', help='Display grid status')
    parser.add_argument('--stop', action='store_true', help='Stop the grid')
    
    args = parser.parse_args()
    
    if args.activate:
        success = activate_eth_grid()
        sys.exit(0 if success else 1)
    
    elif args.status:
        display_grid_info()
    
    elif args.stop:
        grid_manager = GridManager()
        if grid_manager.stop_grid('ETH-EUR'):
            log("Grid stopped successfully")
        else:
            log("Failed to stop grid or no grid found", level='error')
    
    else:
        # Default: activate
        success = activate_eth_grid()
        sys.exit(0 if success else 1)
