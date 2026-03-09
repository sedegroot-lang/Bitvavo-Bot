"""
Automatic Metrics Generation
Runs advanced performance metrics on schedule and updates dashboard
"""

import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from modules.advanced_metrics import AdvancedMetrics

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoMetricsGenerator:
    """Automatically generate and update performance metrics"""
    
    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.data_dir = project_root / "data"
        self.reports_dir = project_root / "reports"
        self.metrics_dir = project_root / "metrics"
        
        # Create directories if needed
        self.reports_dir.mkdir(exist_ok=True)
        self.metrics_dir.mkdir(exist_ok=True)
        
        self.trade_log_path = self.data_dir / "trade_log.json"
        self.metrics_output = self.reports_dir / "auto_metrics.json"
        self.last_run_file = self.metrics_dir / "last_metrics_run.json"
    
    def should_run(self, interval_hours: int = 6) -> bool:
        """Check if enough time has passed since last run"""
        if not self.last_run_file.exists():
            return True
        
        try:
            with open(self.last_run_file, 'r') as f:
                data = json.load(f)
                last_run = data.get('timestamp', 0)
                
            time_since_last = time.time() - last_run
            hours_since_last = time_since_last / 3600
            
            if hours_since_last >= interval_hours:
                logger.info(f"Last run was {hours_since_last:.1f}h ago - running metrics")
                return True
            else:
                logger.info(f"Last run was {hours_since_last:.1f}h ago - skipping (interval: {interval_hours}h)")
                return False
                
        except Exception as e:
            logger.warning(f"Error reading last run file: {e} - running metrics")
            return True
    
    def update_last_run(self):
        """Update last run timestamp"""
        data = {
            'timestamp': time.time(),
            'datetime': datetime.now().isoformat()
        }
        with open(self.last_run_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def generate_metrics(self, days: int = 90) -> dict:
        """Generate advanced performance metrics"""
        logger.info(f"Generating metrics for last {days} days...")
        
        try:
            metrics = AdvancedMetrics(str(self.trade_log_path))
            report = metrics.generate_report(days=days)
            
            # Add metadata
            report['generated_at'] = datetime.now().isoformat()
            report['days_analyzed'] = days
            report['auto_generated'] = True
            
            logger.info(f"✅ Metrics generated successfully")
            return report
            
        except Exception as e:
            logger.error(f"Error generating metrics: {e}")
            return {'error': str(e), 'generated_at': datetime.now().isoformat()}
    
    def save_metrics(self, report: dict):
        """Save metrics to file"""
        try:
            # Save full report
            with open(self.metrics_output, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"💾 Metrics saved to {self.metrics_output}")
            
            # Also save to metrics directory with timestamp
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            timestamped_file = self.metrics_dir / f"metrics_{timestamp}.json"
            with open(timestamped_file, 'w') as f:
                json.dump(report, f, indent=2)
            logger.info(f"💾 Timestamped copy saved to {timestamped_file}")
            
            # Keep only last 10 timestamped files
            self.cleanup_old_metrics()
            
        except Exception as e:
            logger.error(f"Error saving metrics: {e}")
    
    def cleanup_old_metrics(self, keep_count: int = 10):
        """Keep only the most recent timestamped metrics files"""
        try:
            metrics_files = sorted(self.metrics_dir.glob("metrics_*.json"))
            if len(metrics_files) > keep_count:
                files_to_delete = metrics_files[:-keep_count]
                for file in files_to_delete:
                    file.unlink()
                    logger.info(f"🗑️ Deleted old metrics file: {file.name}")
        except Exception as e:
            logger.warning(f"Error cleaning up old metrics: {e}")
    
    def run(self, days: int = 90, force: bool = False, interval_hours: int = 6):
        """Run metrics generation if needed"""
        logger.info("=" * 60)
        logger.info("AUTO METRICS GENERATOR")
        logger.info("=" * 60)
        
        # Check if we should run
        if not force and not self.should_run(interval_hours):
            logger.info("⏭️ Skipping - too soon since last run")
            return
        
        # Check if trade log exists
        if not self.trade_log_path.exists():
            logger.warning(f"⚠️ Trade log not found: {self.trade_log_path}")
            return
        
        # Generate metrics
        report = self.generate_metrics(days)
        
        # Save results
        if 'error' not in report:
            self.save_metrics(report)
            self.update_last_run()
            
            # Print summary
            logger.info("=" * 60)
            logger.info("METRICS SUMMARY")
            logger.info("=" * 60)
            if report.get('summary'):
                summary = report['summary']
                logger.info(f"Total Trades: {summary.get('total_trades', 'N/A')}")
                logger.info(f"Win Rate: {summary.get('win_rate', 0):.1f}%")
                logger.info(f"Total Profit: €{summary.get('total_profit', 0):.2f}")
                if summary.get('sharpe_ratio'):
                    logger.info(f"Sharpe Ratio: {summary['sharpe_ratio']:.2f}")
            logger.info("=" * 60)
        else:
            logger.error(f"❌ Failed to generate metrics: {report.get('error')}")


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Automatic metrics generation')
    parser.add_argument('--days', type=int, default=90, help='Days to analyze (default: 90)')
    parser.add_argument('--force', action='store_true', help='Force run even if recently run')
    parser.add_argument('--interval', type=int, default=6, help='Minimum hours between runs (default: 6)')
    
    args = parser.parse_args()
    
    generator = AutoMetricsGenerator(project_root)
    generator.run(days=args.days, force=args.force, interval_hours=args.interval)


if __name__ == '__main__':
    main()
