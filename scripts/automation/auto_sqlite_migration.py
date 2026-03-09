"""
Automatic SQLite Migration
Checks if JSON is used and automatically migrates to SQLite on bot startup
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.database_manager import DatabaseManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoMigration:
    """Automatic SQLite migration handler"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.data_dir = project_root / "data"
        self.config_dir = project_root / "config"
        
        self.json_path = self.data_dir / "trade_log.json"
        self.db_path = self.data_dir / "trades.db"
        self.migration_flag = self.data_dir / ".migrated_to_sqlite"
        self.config_file = self.config_dir / "system_config.json"
    
    def is_sqlite_enabled(self) -> bool:
        """Check if SQLite is enabled in config"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                    return config.get('use_sqlite', False)
        except Exception as e:
            logger.warning(f"Error reading config: {e}")
        return False
    
    def should_migrate(self) -> bool:
        """Determine if migration should run"""
        # Already migrated?
        if self.migration_flag.exists():
            logger.info("✅ Already migrated to SQLite")
            return False
        
        # SQLite DB already exists?
        if self.db_path.exists():
            logger.info("✅ SQLite database already exists")
            self.mark_as_migrated()
            return False
        
        # JSON exists?
        if not self.json_path.exists():
            logger.warning("⚠️ No JSON trade log found - nothing to migrate")
            return False
        
        # Check if JSON has data
        try:
            with open(self.json_path, 'r') as f:
                data = json.load(f)
                total_trades = len(data.get('open', [])) + len(data.get('closed', []))
                
                if total_trades == 0:
                    logger.info("📭 JSON is empty - skipping migration")
                    return False
                
                logger.info(f"📊 Found {total_trades} trades in JSON - migration recommended")
                return True
        except Exception as e:
            logger.error(f"Error reading JSON: {e}")
            return False
    
    def mark_as_migrated(self):
        """Create migration flag file"""
        try:
            data = {
                'migrated_at': datetime.now().isoformat(),
                'json_path': str(self.json_path),
                'db_path': str(self.db_path)
            }
            with open(self.migration_flag, 'w') as f:
                json.dump(data, f, indent=2)
            logger.info("✅ Migration flag created")
        except Exception as e:
            logger.warning(f"Error creating migration flag: {e}")
    
    def run_migration(self) -> bool:
        """Execute the migration"""
        logger.info("=" * 60)
        logger.info("🚀 STARTING AUTOMATIC SQLITE MIGRATION")
        logger.info("=" * 60)
        
        try:
            # Initialize database manager
            db_manager = DatabaseManager(str(self.db_path))
            
            # Run migration with backup
            logger.info(f"📦 Migrating from {self.json_path} to {self.db_path}")
            db_manager.migrate_from_json(str(self.json_path), backup=True)
            
            # Verify migration
            stats = db_manager.get_statistics()
            logger.info("=" * 60)
            logger.info("✅ MIGRATION SUCCESSFUL")
            logger.info("=" * 60)
            logger.info(f"Total trades in database: {stats.get('total_trades', 0)}")
            logger.info(f"Open trades: {stats.get('open_trades', 0)}")
            logger.info(f"Closed trades: {stats.get('closed_trades', 0)}")
            logger.info(f"Win rate: {stats.get('win_rate', 0):.1f}%")
            logger.info(f"Total profit: €{stats.get('total_profit', 0):.2f}")
            logger.info("=" * 60)
            
            # Mark as migrated
            self.mark_as_migrated()
            
            # Update config to use SQLite
            self.enable_sqlite_in_config()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            logger.error("Bot will continue using JSON")
            return False
    
    def enable_sqlite_in_config(self):
        """Enable SQLite in system config"""
        try:
            config = {}
            if self.config_file.exists():
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
            
            config['use_sqlite'] = True
            config['sqlite_db_path'] = str(self.db_path)
            config['json_backup_path'] = str(self.json_path)
            config['migrated_at'] = datetime.now().isoformat()
            
            with open(self.config_file, 'w') as f:
                json.dump(config, f, indent=2)
            
            logger.info("✅ SQLite enabled in system config")
            
        except Exception as e:
            logger.warning(f"Could not update config: {e}")
    
    def run(self, force: bool = False):
        """Main entry point"""
        logger.info("🔍 Checking if SQLite migration is needed...")
        
        if force:
            logger.info("⚡ Force mode enabled - running migration")
            return self.run_migration()
        
        if self.should_migrate():
            logger.info("✅ Migration needed - proceeding")
            return self.run_migration()
        else:
            logger.info("⏭️ Migration not needed - skipping")
            return False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automatic SQLite migration')
    parser.add_argument('--force', action='store_true', help='Force migration even if already done')
    parser.add_argument('--check-only', action='store_true', help='Only check if migration needed')
    
    args = parser.parse_args()
    
    migrator = AutoMigration(project_root)
    
    if args.check_only:
        should_migrate = migrator.should_migrate()
        print(f"Migration needed: {should_migrate}")
        sys.exit(0 if should_migrate else 1)
    else:
        success = migrator.run(force=args.force)
        sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
