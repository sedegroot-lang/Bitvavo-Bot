"""
Automated Backup System for Trading Bot
========================================

Features:
- Every 6 hours: backup trade_log.json & bot_config.json
- Append-only trade_audit.log for complete trade history
- Auto-cleanup: keep last 7 days of backups
- Recovery script included

Usage:
    python auto_backup.py
"""

import json
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

# CRITICAL: Use project root as base for all paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Configuration
BACKUP_INTERVAL_HOURS = 6
BACKUP_DIR = PROJECT_ROOT / 'backups'
AUDIT_LOG = PROJECT_ROOT / 'logs' / 'trade_audit.log'
FILES_TO_BACKUP = [
    'data/trade_log.json',
    'config/bot_config.json',
    'ai/ai_suggestions.json',
    'ai/ai_changes.json'
]
KEEP_DAYS = 7

def ensure_dirs():
    """Create backup and log directories if they don't exist."""
    BACKUP_DIR.mkdir(exist_ok=True)
    AUDIT_LOG.parent.mkdir(exist_ok=True)

def create_backup():
    """Create timestamped backup of critical files."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_subdir = BACKUP_DIR / timestamp
    backup_subdir.mkdir(exist_ok=True)
    
    backed_up = []
    for filename in FILES_TO_BACKUP:
        src = PROJECT_ROOT / filename
        if src.exists():
            dst = backup_subdir / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            backed_up.append(filename)
            print(f"[OK] Backed up: {filename} -> {dst}")
    
    if backed_up:
        print(f"[Auto-Backup] Backup created: {backup_subdir}")
        return backup_subdir
    else:
        print("[WARNING] No files found to backup")
        return None

def append_to_audit_log():
    """Append new closed trades to audit log (append-only)."""
    try:
        trade_log_path = PROJECT_ROOT / 'data' / 'trade_log.json'
        with open(trade_log_path, 'r') as f:
            trade_data = json.load(f)
        
        closed_trades = trade_data.get('closed', [])
        
        # Check if audit log exists
        if AUDIT_LOG.exists():
            with open(AUDIT_LOG, 'r') as f:
                last_line = None
                for line in f:
                    last_line = line
                
                # Get last timestamp
                if last_line:
                    try:
                        last_entry = json.loads(last_line)
                        last_ts = last_entry.get('timestamp', 0)
                    except:
                        last_ts = 0
                else:
                    last_ts = 0
        else:
            last_ts = 0
        
        # Append new trades
        new_count = 0
        with open(AUDIT_LOG, 'a') as f:
            for trade in closed_trades:
                if trade.get('timestamp', 0) > last_ts:
                    f.write(json.dumps(trade) + '\n')
                    new_count += 1
        
        if new_count > 0:
            print(f"[OK] Appended {new_count} new trades to audit log")
    
    except Exception as e:
        print(f"[WARNING] Audit log error: {e}")

def cleanup_old_backups():
    """Remove backups older than KEEP_DAYS."""
    if not BACKUP_DIR.exists():
        return
    
    cutoff_date = datetime.now() - timedelta(days=KEEP_DAYS)
    removed = []
    
    for backup_dir in BACKUP_DIR.iterdir():
        if backup_dir.is_dir():
            try:
                # Parse timestamp from dirname
                dir_name = backup_dir.name
                dir_date = datetime.strptime(dir_name, '%Y%m%d_%H%M%S')
                
                if dir_date < cutoff_date:
                    shutil.rmtree(backup_dir)
                    removed.append(dir_name)
            except (ValueError, OSError):
                pass
    
    if removed:
        print(f"[Auto-Backup] Cleaned up {len(removed)} old backups")

def recover_from_backup(backup_timestamp=None):
    """
    Recovery utility - restore from backup.
    
    Args:
        backup_timestamp: Specific backup to restore (format: YYYYMMDD_HHMMSS)
                         If None, uses most recent backup
    """
    if not BACKUP_DIR.exists():
        print("[Auto-Backup] ERROR: No backups directory found")
        return False
    
    backups = sorted([d for d in BACKUP_DIR.iterdir() if d.is_dir()], reverse=True)
    if not backups:
        print("[Auto-Backup] ERROR: No backups available")
        return False
    
    if backup_timestamp:
        backup_dir = BACKUP_DIR / backup_timestamp
        if not backup_dir.exists():
            print(f"[Auto-Backup] ERROR: Backup {backup_timestamp} not found")
            return False
    else:
        backup_dir = backups[0]
    
    print(f"\n[WARNING] RECOVERY MODE")
    print(f"[Auto-Backup] Restoring from: {backup_dir.name}")
    print(f"   Created: {datetime.strptime(backup_dir.name, '%Y%m%d_%H%M%S').strftime('%Y-%m-%d %H:%M:%S')}")
    
    response = input("\nContinue with recovery? (yes/no): ")
    if response.lower() != 'yes':
        print("[Auto-Backup] Recovery cancelled")
        return False
    
    # Create recovery backup first
    print("\n1) Creating safety backup of current files...")
    recovery_backup = BACKUP_DIR / f"pre_recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    recovery_backup.mkdir(exist_ok=True)
    
    for filename in FILES_TO_BACKUP:
        src = PROJECT_ROOT / filename
        if src.exists():
            dst = recovery_backup / filename
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    
    print(f"[OK] Safety backup: {recovery_backup}")
    
    # Restore files
    print("\n2) Restoring files...")
    restored = []
    for filename in FILES_TO_BACKUP:
        src = backup_dir / filename
        dst = PROJECT_ROOT / filename
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            restored.append(filename)
            print(f"[OK] Restored: {filename}")
    
    print(f"\n[Auto-Backup] Recovery complete! Restored {len(restored)} files")
    print(f"[Auto-Backup] Pre-recovery backup saved at: {recovery_backup}")
    return True

def run_backup_loop():
    """Main backup loop - runs every BACKUP_INTERVAL_HOURS."""
    ensure_dirs()
    print(f"\n[Auto-Backup] System Started")
    print(f"[Auto-Backup] Backup directory: {BACKUP_DIR.absolute()}")
    print(f"[Auto-Backup] Interval: Every {BACKUP_INTERVAL_HOURS} hours")
    print(f"[Auto-Backup] Retention: {KEEP_DAYS} days")
    print(f"[Auto-Backup] Audit log: {AUDIT_LOG.absolute()}\n")
    
    while True:
        try:
            print(f"\n{'='*60}")
            print(f"[Auto-Backup] Backup cycle: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}\n")
            
            # Create backup
            create_backup()
            
            # Update audit log
            append_to_audit_log()
            
            # Cleanup old backups
            cleanup_old_backups()
            
            # Wait
            print(f"\nNext backup in {BACKUP_INTERVAL_HOURS} hours...")
            time.sleep(BACKUP_INTERVAL_HOURS * 3600)
        
        except KeyboardInterrupt:
            print("\n\nBackup system stopped")
            break
        except Exception as e:
            print(f"\n[ERROR] Error in backup loop: {e}")
            print(f"Retrying in 1 hour...")
            time.sleep(3600)

if __name__ == '__main__':
    import sys
    
    # Single-instance check: prevent duplicate auto_backup processes
    try:
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from single_instance import ensure_single_instance_or_exit
        ensure_single_instance_or_exit('auto_backup.py')
    except ImportError:
        pass  # single_instance module not available, skip check
    
    if len(sys.argv) > 1 and sys.argv[1] == 'recover':
        # Recovery mode
        backup_ts = sys.argv[2] if len(sys.argv) > 2 else None
        recover_from_backup(backup_ts)
    elif len(sys.argv) > 1 and sys.argv[1] == 'once':
        # Single backup
        ensure_dirs()
        create_backup()
        append_to_audit_log()
        cleanup_old_backups()
    else:
        # Normal loop
        run_backup_loop()
