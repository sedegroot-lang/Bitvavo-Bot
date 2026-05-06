"""
Automated Task Scheduler
Runs periodic maintenance tasks (metrics, tests, backups)
"""

import sys
import time
import logging
import schedule
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.automation.auto_metrics import AutoMetricsGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutomationScheduler:
    """Schedules and runs automated tasks"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.metrics_generator = AutoMetricsGenerator(project_root)
        self.running = False
    
    def job_generate_metrics(self):
        """Job: Generate performance metrics"""
        logger.info("📊 Scheduled job: Generate metrics")
        try:
            self.metrics_generator.run(days=90, force=False, interval_hours=6)
        except Exception as e:
            logger.error(f"Error in metrics job: {e}")
    
    def job_cleanup_logs(self):
        """Job: Cleanup old log files"""
        logger.info("🗑️ Scheduled job: Cleanup logs")
        try:
            logs_dir = self.project_root / "logs"
            if logs_dir.exists():
                # Keep last 30 days of logs
                cutoff_time = time.time() - (30 * 24 * 3600)
                deleted_count = 0
                
                for log_file in logs_dir.glob("*.log"):
                    if log_file.stat().st_mtime < cutoff_time:
                        log_file.unlink()
                        deleted_count += 1
                
                if deleted_count > 0:
                    logger.info(f"✅ Deleted {deleted_count} old log files")
                else:
                    logger.info("✅ No old logs to delete")
        except Exception as e:
            logger.error(f"Error in cleanup job: {e}")
    
    def job_backup_data(self):
        """Job: Create backup of critical data"""
        logger.info("💾 Scheduled job: Backup data")
        try:
            import shutil
            from datetime import datetime
            
            # Backup trade log
            trade_log = self.project_root / "data" / "trade_log.json"
            if trade_log.exists():
                backup_dir = self.project_root / "backups"
                backup_dir.mkdir(exist_ok=True)
                
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                backup_file = backup_dir / f"trade_log_{timestamp}.json"
                
                shutil.copy2(trade_log, backup_file)
                logger.info(f"✅ Backup created: {backup_file.name}")
                
                # Keep only last 20 backups
                backups = sorted(backup_dir.glob("trade_log_*.json"))
                if len(backups) > 20:
                    for old_backup in backups[:-20]:
                        old_backup.unlink()
                        logger.info(f"🗑️ Deleted old backup: {old_backup.name}")
        except Exception as e:
            logger.error(f"Error in backup job: {e}")
    
    def job_cold_tier_scan(self):
        """Job: scan cold tier (~400 EUR markets) and promote top-1 to WATCHLIST_MARKETS.

        Uses scripts/cold_tier_scanner.py with --apply --n 1. Writes ONLY to local
        config (%LOCALAPPDATA%/BotConfig/bot_config_local.json), so it cannot be
        reverted by OneDrive sync. The bot's config hot-reload picks up the new
        watchlist entry on the next loop iteration.
        """
        logger.info("🔭 Scheduled job: cold-tier scan (apply top-1)")
        try:
            import subprocess
            scanner = self.project_root / "scripts" / "cold_tier_scanner.py"
            python = sys.executable
            result = subprocess.run(
                [python, "-u", str(scanner), "--apply", "--n", "1"],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                timeout=120,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                # Show only the meaningful tail (header + ranked + apply result)
                tail = "\n".join(result.stdout.splitlines()[-20:])
                logger.info("✅ cold_tier_scanner OK\n" + tail)
            else:
                logger.error(f"❌ cold_tier_scanner failed (rc={result.returncode}): {result.stderr[:500]}")
        except Exception as e:
            logger.error(f"Error in cold-tier scan job: {e}")

    def job_weekly_report(self):
        """Job: Weekly performance report (snapshot + Telegram)."""
        logger.info("📅 Scheduled job: weekly PnL report")
        try:
            from bot.weekly_report import run as run_weekly
            report, snapshot, sent = run_weekly(force=False, dry=False)
            logger.info(f"✅ weekly report: snapshot={snapshot.name} sent={sent} pnl=€{report['current']['pnl_eur']:+.2f}")
        except Exception as e:
            logger.error(f"Error in weekly report job: {e}")

    def job_regression_check(self):
        """Job: Hourly check for performance regression — alert via Telegram."""
        logger.info("🔎 Scheduled job: regression check")
        try:
            from bot.regression_alerter import run as run_regress
            result, sent = run_regress(force=False, dry=False)
            if result.get("skipped"):
                logger.info(f"   skipped: {result.get('reason')}")
            elif result.get("ok"):
                logger.info(f"   ✅ healthy (n={result['n']} wr={result['win_rate']*100:.0f}% pnl=€{result['cum_pnl']:+.2f})")
            else:
                throttled = " (throttled)" if result.get("throttled") else ""
                logger.warning(f"   ⚠️ regression detected{throttled}: {result['breaches']} sent={sent}")
        except Exception as e:
            logger.error(f"Error in regression check job: {e}")

    def job_health_check(self):
        """Job: Check bot health"""
        logger.info("🏥 Scheduled job: Health check")
        try:
            heartbeat_file = self.project_root / "data" / "heartbeat.json"
            if heartbeat_file.exists():
                import json
                with open(heartbeat_file, 'r') as f:
                    heartbeat = json.load(f)
                
                last_update = heartbeat.get('timestamp', 0)
                age_seconds = time.time() - last_update
                
                if age_seconds > 300:  # 5 minutes
                    logger.warning(f"⚠️ Bot heartbeat is {age_seconds:.0f}s old - might be down!")
                else:
                    logger.info(f"✅ Bot is healthy (heartbeat {age_seconds:.0f}s old)")
                    
                    # Log status - if bot_active field missing, assume ON (backwards compat)
                    bot_active = heartbeat.get('bot_active', True)  # Default True if missing
                    ai_active = heartbeat.get('ai_active', False)
                    open_trades = heartbeat.get('open_trades', 0)  # Use 'open_trades' not 'total_open_trades'
                    logger.info(f"   Bot: {'🟢 ON' if bot_active else '🔴 OFF'} | AI: {'🟢 ON' if ai_active else '🔴 OFF'} | Trades: {open_trades}")
            else:
                logger.warning("⚠️ Heartbeat file not found")
        except Exception as e:
            logger.error(f"Error in health check: {e}")
    
    def setup_schedule(self):
        """Setup all scheduled jobs"""
        logger.info("⏰ Setting up automated task schedule...")
        
        # Metrics: Every 6 hours
        schedule.every(6).hours.do(self.job_generate_metrics)
        logger.info("  ✅ Metrics generation: every 6 hours")
        
        # Cleanup: Daily at 3 AM
        schedule.every().day.at("03:00").do(self.job_cleanup_logs)
        logger.info("  ✅ Log cleanup: daily at 03:00")
        
        # Backup: Every 12 hours
        schedule.every(12).hours.do(self.job_backup_data)
        logger.info("  ✅ Data backup: every 12 hours")
        
        # Health check: Every 15 minutes
        schedule.every(15).minutes.do(self.job_health_check)
        logger.info("  ✅ Health check: every 15 minutes")

        # Cold-tier scan: every 4 hours, applies top-1 to local WATCHLIST_MARKETS
        schedule.every(4).hours.do(self.job_cold_tier_scan)
        logger.info("  ✅ Cold-tier scan: every 4 hours (apply top-1)")

        # Weekly PnL report: Sunday 21:00
        schedule.every().sunday.at("21:00").do(self.job_weekly_report)
        logger.info("  ✅ Weekly PnL report: Sunday 21:00")

        # Performance regression check: hourly
        schedule.every(1).hours.do(self.job_regression_check)
        logger.info("  ✅ Regression check: hourly")
        
        logger.info("=" * 60)
    
    def run(self):
        """Run the scheduler"""
        logger.info("=" * 60)
        logger.info("🤖 AUTOMATION SCHEDULER STARTED")
        logger.info("=" * 60)
        
        self.setup_schedule()
        self.running = True
        
        # Run initial jobs
        logger.info("🚀 Running initial tasks...")
        self.job_health_check()
        self.job_generate_metrics()
        self.job_cold_tier_scan()
        
        logger.info("=" * 60)
        logger.info("⏰ Scheduler is now running - press Ctrl+C to stop")
        logger.info("=" * 60)
        
        try:
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
        except KeyboardInterrupt:
            logger.info("\n🛑 Scheduler stopped by user")
            self.running = False


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automation scheduler')
    parser.add_argument('--test', action='store_true', help='Run test jobs and exit')
    
    args = parser.parse_args()
    
    scheduler = AutomationScheduler(project_root)
    
    if args.test:
        logger.info("🧪 Running test jobs...")
        scheduler.job_health_check()
        scheduler.job_generate_metrics()
        scheduler.job_backup_data()
        logger.info("✅ Test complete")
    else:
        scheduler.run()


if __name__ == '__main__':
    main()
