"""
SQLite Database Migration
=========================

Migrate from JSON files to SQLite database for:
- Better performance with large datasets
- ACID transactions
- Complex queries
- Proper indexing
- Data integrity

Includes:
- Schema definition
- Migration script from trade_log.json
- Database access layer
- Backup/rollback capabilities
"""

import sqlite3
import json
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from contextlib import contextmanager


# Database schema
SCHEMA = """
-- Trades table
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    market TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open', 'closed')),
    buy_price REAL NOT NULL,
    sell_price REAL,
    amount REAL NOT NULL,
    initial_invested_eur REAL,
    total_invested_eur REAL,
    profit REAL DEFAULT 0,
    profit_pct REAL DEFAULT 0,
    
    -- Timestamps
    opened_ts REAL NOT NULL,
    closed_ts REAL,
    timestamp REAL NOT NULL,
    
    -- DCA info
    dca_count INTEGER DEFAULT 0,
    dca_levels TEXT,  -- JSON array
    
    -- Trailing info
    highest_price REAL,
    lowest_price REAL,
    trailing_activated BOOLEAN DEFAULT 0,
    trailing_stop_pct REAL,
    
    -- Exit details
    reason TEXT,
    
    -- Metadata
    bot_version TEXT,
    strategy TEXT,
    created_at REAL DEFAULT (strftime('%s', 'now')),
    updated_at REAL DEFAULT (strftime('%s', 'now')),
    
    -- Indexes
    UNIQUE(market, opened_ts) ON CONFLICT REPLACE
);

CREATE INDEX IF NOT EXISTS idx_trades_market ON trades(market);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
CREATE INDEX IF NOT EXISTS idx_trades_opened_ts ON trades(opened_ts);
CREATE INDEX IF NOT EXISTS idx_trades_closed_ts ON trades(closed_ts);
CREATE INDEX IF NOT EXISTS idx_trades_profit ON trades(profit);

-- Trade history (for audit trail)
CREATE TABLE IF NOT EXISTS trade_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL,
    action TEXT NOT NULL,  -- 'opened', 'dca_buy', 'closed', 'sync_removed'
    timestamp REAL NOT NULL,
    price REAL,
    amount REAL,
    invested_eur REAL,
    details TEXT,  -- JSON for additional data
    FOREIGN KEY (trade_id) REFERENCES trades(id)
);

CREATE INDEX IF NOT EXISTS idx_history_trade_id ON trade_history(trade_id);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON trade_history(timestamp);

-- Performance metrics (daily snapshots)
CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    total_trades INTEGER DEFAULT 0,
    open_trades INTEGER DEFAULT 0,
    closed_trades INTEGER DEFAULT 0,
    win_rate REAL DEFAULT 0,
    total_profit REAL DEFAULT 0,
    total_profit_pct REAL DEFAULT 0,
    avg_win REAL DEFAULT 0,
    avg_loss REAL DEFAULT 0,
    max_drawdown REAL DEFAULT 0,
    sharpe_ratio REAL DEFAULT 0,
    balance_eur REAL DEFAULT 0,
    portfolio_value REAL DEFAULT 0,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_metrics_date ON metrics(date);

-- Bot configuration snapshots
CREATE TABLE IF NOT EXISTS config_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    config_json TEXT NOT NULL,
    changed_by TEXT,  -- 'user', 'ai', 'system'
    changes_summary TEXT
);

CREATE INDEX IF NOT EXISTS idx_config_timestamp ON config_history(timestamp);

-- AI suggestions log
CREATE TABLE IF NOT EXISTS ai_suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    suggestion_type TEXT NOT NULL,  -- 'entry', 'exit', 'parameter_change'
    market TEXT,
    confidence REAL,
    reasoning TEXT,
    suggestion_json TEXT NOT NULL,
    applied BOOLEAN DEFAULT 0,
    applied_at REAL,
    result TEXT,
    created_at REAL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_timestamp ON ai_suggestions(timestamp);
CREATE INDEX IF NOT EXISTS idx_ai_market ON ai_suggestions(market);
CREATE INDEX IF NOT EXISTS idx_ai_applied ON ai_suggestions(applied);
"""


class DatabaseManager:
    """SQLite database manager"""
    
    def __init__(self, db_path: str = "data/bot_database.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Create database and tables"""
        with self.get_connection() as conn:
            conn.executescript(SCHEMA)
            conn.commit()
    
    @contextmanager
    def get_connection(self):
        """Get database connection with context manager"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Return rows as dicts
        try:
            yield conn
        finally:
            conn.close()
    
    # ========== TRADE OPERATIONS ==========
    
    def insert_trade(self, trade: Dict[str, Any]) -> int:
        """Insert new trade"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                INSERT INTO trades (
                    market, status, buy_price, sell_price, amount,
                    initial_invested_eur, total_invested_eur, profit, profit_pct,
                    opened_ts, closed_ts, timestamp,
                    dca_count, dca_levels,
                    highest_price, lowest_price, trailing_activated, trailing_stop_pct,
                    reason, bot_version, strategy
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trade.get('market'),
                'open',
                trade.get('buy_price'),
                None,
                trade.get('amount'),
                trade.get('initial_invested_eur') or (trade.get('buy_price', 0) * trade.get('amount', 0)),
                trade.get('total_invested_eur') or (trade.get('buy_price', 0) * trade.get('amount', 0)),
                0,
                0,
                trade.get('opened_ts') or trade.get('timestamp'),
                None,
                trade.get('timestamp'),
                trade.get('dca_count', 0),
                json.dumps(trade.get('dca_levels', [])),
                trade.get('highest_price'),
                trade.get('lowest_price'),
                trade.get('trailing_activated', False),
                trade.get('trailing_stop_pct'),
                None,
                trade.get('bot_version'),
                trade.get('strategy')
            ))
            conn.commit()
            return cursor.lastrowid
    
    def update_trade(self, market: str, updates: Dict[str, Any]):
        """Update existing trade"""
        set_clause = ', '.join(f"{k} = ?" for k in updates.keys())
        set_clause += ", updated_at = ?"
        
        values = list(updates.values()) + [time.time(), market]
        
        with self.get_connection() as conn:
            conn.execute(f"""
                UPDATE trades 
                SET {set_clause}
                WHERE market = ? AND status = 'open'
            """, values)
            conn.commit()
    
    def close_trade(self, market: str, sell_price: float, reason: str):
        """Close an open trade"""
        with self.get_connection() as conn:
            # Get current trade
            trade = conn.execute("""
                SELECT * FROM trades WHERE market = ? AND status = 'open'
            """, (market,)).fetchone()
            
            if not trade:
                return False
            
            # Calculate profit
            sold_for = trade['amount'] * sell_price
            profit = sold_for - trade['total_invested_eur']
            profit_pct = (profit / trade['total_invested_eur']) * 100 if trade['total_invested_eur'] > 0 else 0
            
            # Update trade
            conn.execute("""
                UPDATE trades
                SET status = 'closed',
                    sell_price = ?,
                    profit = ?,
                    profit_pct = ?,
                    reason = ?,
                    closed_ts = ?,
                    updated_at = ?
                WHERE market = ? AND status = 'open'
            """, (sell_price, profit, profit_pct, reason, time.time(), time.time(), market))
            
            conn.commit()
            return True
    
    def get_open_trades(self) -> List[Dict]:
        """Get all open trades"""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT * FROM trades WHERE status = 'open' ORDER BY opened_ts DESC
            """).fetchall()
            return [dict(row) for row in rows]
    
    def get_closed_trades(self, limit: Optional[int] = None, offset: int = 0) -> List[Dict]:
        """Get closed trades with pagination"""
        with self.get_connection() as conn:
            query = "SELECT * FROM trades WHERE status = 'closed' ORDER BY closed_ts DESC"
            if limit:
                query += f" LIMIT {limit} OFFSET {offset}"
            
            rows = conn.execute(query).fetchall()
            return [dict(row) for row in rows]
    
    def get_trade_by_market(self, market: str) -> Optional[Dict]:
        """Get trade by market (open or most recent)"""
        with self.get_connection() as conn:
            row = conn.execute("""
                SELECT * FROM trades WHERE market = ? ORDER BY opened_ts DESC LIMIT 1
            """, (market,)).fetchone()
            return dict(row) if row else None
    
    # ========== STATISTICS ==========
    
    def get_statistics(self, days: Optional[int] = None) -> Dict[str, Any]:
        """Get trading statistics"""
        with self.get_connection() as conn:
            where_clause = ""
            params = []
            
            if days:
                cutoff = time.time() - (days * 86400)
                where_clause = "WHERE closed_ts > ?"
                params.append(cutoff)
            
            stats = conn.execute(f"""
                SELECT
                    COUNT(*) as total_trades,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as winning_trades,
                    SUM(CASE WHEN profit <= 0 THEN 1 ELSE 0 END) as losing_trades,
                    SUM(profit) as total_profit,
                    AVG(profit) as avg_profit,
                    MAX(profit) as max_profit,
                    MIN(profit) as min_profit,
                    AVG(CASE WHEN profit > 0 THEN profit END) as avg_win,
                    AVG(CASE WHEN profit <= 0 THEN profit END) as avg_loss
                FROM trades
                WHERE status = 'closed' {where_clause}
            """, params).fetchone()
            
            result = dict(stats)
            result['win_rate'] = (result['winning_trades'] / result['total_trades'] * 100) if result['total_trades'] > 0 else 0
            
            return result
    
    def get_performance_by_market(self) -> List[Dict]:
        """Get performance grouped by market"""
        with self.get_connection() as conn:
            rows = conn.execute("""
                SELECT
                    market,
                    COUNT(*) as trades,
                    SUM(profit) as total_profit,
                    AVG(profit) as avg_profit,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) as win_rate
                FROM trades
                WHERE status = 'closed'
                GROUP BY market
                ORDER BY total_profit DESC
            """).fetchall()
            return [dict(row) for row in rows]
    
    # ========== MIGRATION ==========
    
    def migrate_from_json(self, json_path: str = "data/trade_log.json", backup: bool = True):
        """Migrate data from trade_log.json to SQLite"""
        json_file = Path(json_path)
        
        if not json_file.exists():
            print(f"❌ JSON file not found: {json_path}")
            return False
        
        # Backup JSON before migration
        if backup:
            backup_path = json_file.parent / f"trade_log_backup_{int(time.time())}.json"
            import shutil
            shutil.copy(json_file, backup_path)
            print(f"✅ Backup created: {backup_path}")
        
        # Load JSON data
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        print(f"\n📊 Migration Summary:")
        print(f"  Open trades: {len(data.get('open', {}))}")
        print(f"  Closed trades: {len(data.get('closed', []))}")
        
        # Migrate open trades
        open_count = 0
        for market, trade in data.get('open', {}).items():
            try:
                trade['market'] = market
                self.insert_trade(trade)
                open_count += 1
            except Exception as e:
                print(f"⚠️  Failed to migrate open trade {market}: {e}")
        
        # Migrate closed trades
        closed_count = 0
        for trade in data.get('closed', []):
            try:
                # Ensure invested fields exist - calculate from buy_price * amount if missing
                if not trade.get('initial_invested_eur') and trade.get('buy_price') and trade.get('amount'):
                    trade['initial_invested_eur'] = trade['buy_price'] * trade['amount']
                if not trade.get('total_invested_eur') and trade.get('buy_price') and trade.get('amount'):
                    trade['total_invested_eur'] = trade['buy_price'] * trade['amount']
                
                # Insert as open first
                trade_id = self.insert_trade(trade)
                
                # Then close it
                if trade.get('sell_price'):
                    with self.get_connection() as conn:
                        conn.execute("""
                            UPDATE trades
                            SET status = 'closed',
                                sell_price = ?,
                                profit = ?,
                                profit_pct = ?,
                                reason = ?,
                                closed_ts = ?,
                                updated_at = ?
                            WHERE id = ?
                        """, (
                            trade.get('sell_price'),
                            trade.get('profit', 0),
                            trade.get('profit_pct', 0),
                            trade.get('reason', 'unknown'),
                            trade.get('timestamp'),
                            time.time(),
                            trade_id
                        ))
                        conn.commit()
                
                closed_count += 1
            except Exception as e:
                print(f"⚠️  Failed to migrate closed trade: {e}")
        
        print(f"\n✅ Migration complete!")
        print(f"  ✅ Migrated {open_count} open trades")
        print(f"  ✅ Migrated {closed_count} closed trades")
        
        return True
    
    def export_to_json(self, output_path: str = "data/trade_log_export.json"):
        """Export database back to JSON format"""
        open_trades = self.get_open_trades()
        closed_trades = self.get_closed_trades()
        
        data = {
            'open': {trade['market']: trade for trade in open_trades},
            'closed': closed_trades
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        
        print(f"✅ Exported to {output_path}")
        return True


# ========== CLI INTERFACE ==========

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='SQLite database migration')
    parser.add_argument('--migrate', action='store_true', help='Migrate from trade_log.json')
    parser.add_argument('--export', action='store_true', help='Export database to JSON')
    parser.add_argument('--stats', action='store_true', help='Show database statistics')
    parser.add_argument('--db', default='data/bot_database.db', help='Database path')
    parser.add_argument('--json', default='data/trade_log.json', help='JSON file path')
    parser.add_argument('--no-backup', action='store_true', help='Skip JSON backup')
    
    args = parser.parse_args()
    
    db = DatabaseManager(args.db)
    
    if args.migrate:
        print(f"\n{'='*60}")
        print(f"MIGRATING FROM JSON TO SQLITE")
        print(f"{'='*60}")
        print(f"Source: {args.json}")
        print(f"Database: {args.db}")
        print(f"{'='*60}\n")
        
        db.migrate_from_json(args.json, backup=not args.no_backup)
    
    elif args.export:
        print(f"\nExporting database to JSON...")
        db.export_to_json()
    
    elif args.stats:
        print(f"\n{'='*60}")
        print(f"DATABASE STATISTICS")
        print(f"{'='*60}")
        
        stats = db.get_statistics()
        print(f"Total Trades: {stats['total_trades']}")
        print(f"Winning Trades: {stats['winning_trades']}")
        print(f"Losing Trades: {stats['losing_trades']}")
        print(f"Win Rate: {stats['win_rate']:.1f}%")
        print(f"Total Profit: €{stats['total_profit']:.2f}")
        print(f"Average Profit: €{stats['avg_profit']:.2f}")
        print(f"Best Trade: €{stats['max_profit']:.2f}")
        print(f"Worst Trade: €{stats['min_profit']:.2f}")
        print(f"Average Win: €{stats.get('avg_win', 0) or 0:.2f}")
        print(f"Average Loss: €{stats.get('avg_loss', 0) or 0:.2f}")
        
        print(f"\n{'='*60}")
        print(f"PERFORMANCE BY MARKET")
        print(f"{'='*60}")
        
        by_market = db.get_performance_by_market()
        for row in by_market[:10]:  # Top 10
            print(f"{row['market']}: €{row['total_profit']:.2f} ({row['trades']} trades, {row['win_rate']:.1f}% WR)")
        
        print(f"{'='*60}\n")
    
    else:
        print("Use --migrate, --export, or --stats")
        print("Example: python -m modules.database_manager --migrate")
