"""
Documentation Auto-Update Scheduler
Runs in background to automatically update documentation at regular intervals

Features:
- Auto-updates bot status in docs every 5 minutes
- Logs major changes to CHANGELOG.md
- Verifies cross-references
- Integrates with trailing_bot.py

Usage:
    # As standalone daemon
    python scripts/helpers/doc_auto_updater.py
    
    # Or import and integrate with bot
    from scripts.helpers.doc_auto_updater import start_doc_updater
    start_doc_updater()  # Starts background thread
"""

import threading
import time
from pathlib import Path

# Import sync functions
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.helpers.sync_documentation import sync_documentation, extract_bot_status, PROJECT_ROOT


class DocumentationUpdater:
    """Background thread for automatic documentation updates"""
    
    def __init__(self, update_interval_seconds: int = 300):
        """
        Args:
            update_interval_seconds: Update interval (default: 300 = 5 minutes)
        """
        self.update_interval = update_interval_seconds
        self.running = False
        self.thread = None
        self._last_status_hash = None
    
    def _status_changed(self) -> bool:
        """Check if bot status has changed since last update"""
        trade_log_path = PROJECT_ROOT / 'trade_log.json'
        if not trade_log_path.exists():
            return False
        
        try:
            status = extract_bot_status(trade_log_path)
            status_hash = hash((
                status['open_trades'],
                status['total_trades'],
                tuple(status['markets'])
            ))
            
            if self._last_status_hash is None or status_hash != self._last_status_hash:
                self._last_status_hash = status_hash
                return True
            
            return False
        except Exception as e:
            print(f"[DOC_UPDATER] Error checking status: {e}")
            return False
    
    def _update_loop(self):
        """Main update loop"""
        print(f"[DOC_UPDATER] Started (update interval: {self.update_interval}s)")
        
        while self.running:
            try:
                # Check if status changed
                if self._status_changed():
                    print("[DOC_UPDATER] Bot status changed, updating docs...")
                    sync_documentation(auto_update_status=True, log_to_changelog=False)
                
                # Sleep in small increments for faster shutdown
                for _ in range(self.update_interval):
                    if not self.running:
                        break
                    time.sleep(1)
                
            except Exception as e:
                print(f"[DOC_UPDATER] Error in update loop: {e}")
                time.sleep(60)  # Wait 1 minute on error
    
    def start(self):
        """Start the background updater thread"""
        if self.running:
            print("[DOC_UPDATER] Already running")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._update_loop, daemon=True, name="DocUpdater")
        self.thread.start()
        print("[DOC_UPDATER] Background updater started")
    
    def stop(self):
        """Stop the background updater thread"""
        if not self.running:
            return
        
        print("[DOC_UPDATER] Stopping...")
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        print("[DOC_UPDATER] Stopped")


# Global instance
_updater_instance = None


def start_doc_updater(update_interval_seconds: int = 300):
    """
    Start the documentation auto-updater (call this from trailing_bot.py)
    
    Args:
        update_interval_seconds: Update interval in seconds (default: 300 = 5 minutes)
    """
    global _updater_instance
    
    if _updater_instance is None:
        _updater_instance = DocumentationUpdater(update_interval_seconds)
    
    _updater_instance.start()


def stop_doc_updater():
    """Stop the documentation auto-updater"""
    global _updater_instance
    
    if _updater_instance:
        _updater_instance.stop()


if __name__ == '__main__':
    # Standalone mode
    import signal
    
    updater = DocumentationUpdater(update_interval_seconds=300)
    
    def signal_handler(sig, frame):
        print("\n[DOC_UPDATER] Received signal, shutting down...")
        updater.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    updater.start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[DOC_UPDATER] Keyboard interrupt, shutting down...")
        updater.stop()
