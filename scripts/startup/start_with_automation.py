"""
Enhanced Bot Startup with Automation
Starts bot with automatic SQLite migration, metrics, and scheduled tasks
"""

import sys
import time
import logging
import subprocess
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.automation.auto_sqlite_migration import AutoMigration
from scripts.automation.auto_metrics import AutoMetricsGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_pre_startup_automation():
    """Run automation tasks before starting the bot"""
    logger.info("=" * 70)
    logger.info("🚀 BITVAVO BOT - ENHANCED STARTUP WITH AUTOMATION")
    logger.info("=" * 70)
    
    # 1. Auto SQLite Migration
    logger.info("\n📦 Step 1: Checking SQLite migration...")
    try:
        migrator = AutoMigration(project_root)
        migrator.run(force=False)
    except Exception as e:
        logger.warning(f"⚠️ Migration check failed: {e}")
    
    # 2. Generate Initial Metrics
    logger.info("\n📊 Step 2: Generating performance metrics...")
    try:
        metrics_gen = AutoMetricsGenerator(project_root)
        metrics_gen.run(days=90, force=True, interval_hours=6)
    except Exception as e:
        logger.warning(f"⚠️ Metrics generation failed: {e}")
    
    logger.info("\n✅ Pre-startup automation complete")
    logger.info("=" * 70)


def start_bot():
    """Start the main trading bot"""
    logger.info("\n🤖 Starting trading bot...")
    
    try:
        bot_script = project_root / "scripts" / "startup" / "start_bot.py"
        python_exe = project_root / ".venv" / "Scripts" / "python.exe"
        
        if not bot_script.exists():
            logger.error(f"❌ Bot script not found: {bot_script}")
            return None
        
        # Start bot in separate process
        # CRITICAL: Don't capture stdout/stderr - bot spawns 7 subprocesses with continuous output
        # Capturing would fill the pipe buffer and deadlock the entire bot
        # CREATE_NEW_CONSOLE = bot draait in apart venster (nodig voor Flask dashboard visibility)
        process = subprocess.Popen(
            [str(python_exe), str(bot_script)],
            cwd=str(project_root),
            stdout=None,  # Let output go to console
            stderr=None,  # Let errors go to console
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        
        logger.info(f"✅ Bot started (PID: {process.pid})")
        return process
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")
        return None


def start_scheduler():
    """Start the automation scheduler"""
    logger.info("\n⏰ Starting automation scheduler...")
    
    try:
        scheduler_script = project_root / "scripts" / "automation" / "scheduler.py"
        python_exe = project_root / ".venv" / "Scripts" / "python.exe"
        
        if not scheduler_script.exists():
            logger.warning(f"⚠️ Scheduler script not found: {scheduler_script}")
            return None
        
        # Start scheduler in separate process
        # Scheduler has minimal output, but keep consistent with bot (no pipe blocking)
        process = subprocess.Popen(
            [str(python_exe), str(scheduler_script)],
            cwd=str(project_root),
            stdout=None,  # Let output go to console
            stderr=None,  # Let errors go to console
            creationflags=subprocess.CREATE_NEW_CONSOLE if sys.platform == "win32" else 0
        )
        
        logger.info(f"✅ Scheduler started (PID: {process.pid})")
        return process
        
    except Exception as e:
        logger.warning(f"⚠️ Failed to start scheduler: {e}")
        return None


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced bot startup')
    parser.add_argument('--no-automation', action='store_true', help='Skip automation tasks')
    parser.add_argument('--no-scheduler', action='store_true', help='Don\'t start scheduler')
    
    args = parser.parse_args()
    
    # Run pre-startup automation
    if not args.no_automation:
        run_pre_startup_automation()
    
    # Start the bot
    bot_process = start_bot()
    if not bot_process:
        logger.error("❌ Failed to start bot - exiting")
        sys.exit(1)
    
    # Start scheduler
    scheduler_process = None
    if not args.no_scheduler:
        scheduler_process = start_scheduler()
    
    # Monitor processes
    logger.info("\n" + "=" * 70)
    logger.info("🟢 ALL SYSTEMS RUNNING")
    logger.info("=" * 70)
    logger.info(f"Bot: Running in separate console window")
    if scheduler_process:
        logger.info(f"Scheduler PID: {scheduler_process.pid}")
    logger.info("\nℹ️  Bot runs independently in its own window")
    logger.info("   To stop bot: Close its console window or Ctrl+C there")
    if scheduler_process:
        logger.info("   Scheduler will continue running until Ctrl+C here")
    logger.info("=" * 70)
    
    # Bot runs independently in separate console - no monitoring needed
    # Only monitor scheduler if present
    if not scheduler_process:
        logger.info("✅ Startup complete - no background services to monitor")
        return
    
    try:
        # Monitor scheduler only (bot manages itself)
        while True:
            if scheduler_process.poll() is not None:
                logger.warning("⚠️ Scheduler process terminated")
                break
            time.sleep(30)  # Check every 30s
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Shutdown requested...")
        
        # Only stop scheduler (bot runs independently)
        if scheduler_process and scheduler_process.poll() is None:
            logger.info("Stopping scheduler...")
            scheduler_process.terminate()
            scheduler_process.wait(timeout=10)
        
        logger.info("✅ Scheduler stopped")
        logger.info("ℹ️  Bot is still running in its own window")


if __name__ == '__main__':
    main()
