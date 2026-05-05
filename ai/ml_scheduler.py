"""
ML Auto-Retrain Scheduler
Runs as background service to periodically check and retrain ML models.
Can be integrated into bot or run standalone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging
import time

import schedule

from ai.auto_retrain import AutoRetrain

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
    handlers=[logging.FileHandler("logs/ml_scheduler.log"), logging.StreamHandler()],
)
log = logging.getLogger(__name__)


class MLScheduler:
    """Manages periodic ML model retraining."""

    def __init__(self):
        self.retrainer = AutoRetrain()
        self.running = False

    def scheduled_retrain_check(self):
        """Run retraining check (called by scheduler)."""
        log.info("=" * 60)
        log.info("[ML_SCHEDULER] Running scheduled retraining check")
        log.info("=" * 60)

        try:
            result = self.retrainer.run_check()

            if result["action"] == "retrained":
                log.info("[ML_SCHEDULER] ✅ Model retrained successfully")
                log.info(f"[ML_SCHEDULER] New accuracy: {result['metrics'].get('accuracy', 0):.2%}")
            elif result["action"] == "skipped":
                log.info(f"[ML_SCHEDULER] ⏭️  Retraining skipped: {result['reason']}")
            elif result["action"] == "failed":
                log.error(f"[ML_SCHEDULER] ❌ Retraining failed: {result.get('error')}")

        except Exception as e:
            log.error(f"[ML_SCHEDULER] Error in scheduled check: {e}")
            import traceback

            traceback.print_exc()

    def start(self):
        """Start the scheduler."""
        log.info("=" * 60)
        log.info("[ML_SCHEDULER] Starting ML Auto-Retrain Scheduler")
        log.info("=" * 60)
        log.info("[ML_SCHEDULER] Schedule:")
        log.info("[ML_SCHEDULER]   - Daily check at 03:00 (night)")
        log.info("[ML_SCHEDULER]   - Weekly full check on Sunday 02:00")
        log.info("[ML_SCHEDULER] Retraining triggers:")
        log.info("[ML_SCHEDULER]   - Model > 7 days old")
        log.info("[ML_SCHEDULER]   - Accuracy < 55%")
        log.info("[ML_SCHEDULER]   - 50+ new closed trades")
        log.info("=" * 60)

        # Schedule daily check at 3 AM
        schedule.every().day.at("03:00").do(self.scheduled_retrain_check)

        # Schedule weekly full check on Sunday at 2 AM
        schedule.every().sunday.at("02:00").do(self.scheduled_retrain_check)

        # Initial check on startup
        log.info("[ML_SCHEDULER] Running initial check on startup...")
        self.scheduled_retrain_check()

        self.running = True

        # Main loop
        log.info("[ML_SCHEDULER] Scheduler is now running. Press Ctrl+C to stop.")

        try:
            while self.running:
                schedule.run_pending()
                time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            log.info("[ML_SCHEDULER] Shutdown requested")
        except Exception as e:
            log.error(f"[ML_SCHEDULER] Error in main loop: {e}")
        finally:
            self.stop()

    def stop(self):
        """Stop the scheduler."""
        log.info("[ML_SCHEDULER] Stopping scheduler...")
        self.running = False
        schedule.clear()
        log.info("[ML_SCHEDULER] Scheduler stopped.")


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="ML Auto-Retrain Scheduler")
    parser.add_argument("--once", action="store_true", help="Run check once and exit")
    parser.add_argument("--force", action="store_true", help="Force retrain on startup")

    args = parser.parse_args()

    scheduler = MLScheduler()

    if args.force:
        log.info("[ML_SCHEDULER] Force retraining requested")
        scheduler.retrainer.execute_retrain()
    elif args.once:
        log.info("[ML_SCHEDULER] Running one-time check")
        scheduler.scheduled_retrain_check()
    else:
        # Start persistent scheduler
        scheduler.start()


if __name__ == "__main__":
    main()
