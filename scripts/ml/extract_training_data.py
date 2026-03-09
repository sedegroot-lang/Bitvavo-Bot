"""
ML Training Data Extraction
Extracts features and labels from 28GB log files for model training.

Parses bot logs to identify trade entries/exits and extract indicator values.
"""

import json
import re
import gzip
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pandas as pd
import sys

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from modules.logging_utils import log


class TrainingDataExtractor:
    """Extract training data from bot logs."""
    
    def __init__(self, log_dir: str = "scripts/helpers/logs", output_dir: str = "ai/training_data"):
        self.log_dir = Path(log_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Regex patterns for log parsing
        self.trade_opened_pattern = re.compile(
            r'.*TRADE.*OPENED.*market[:\s]+([A-Z0-9-]+).*price[:\s]+([\d.]+)'
        )
        self.trade_closed_pattern = re.compile(
            r'.*TRADE.*CLOSED.*market[:\s]+([A-Z0-9-]+).*profit[:\s]+([-\d.]+)'
        )
        self.indicator_pattern = re.compile(
            r'.*RSI[:\s]+([\d.]+).*MACD[:\s]+([-\d.]+).*SMA[:\s]+([\d.]+)'
        )
    
    def extract_from_logs(self, days: int = 90, sample_ratio: float = 1.0) -> pd.DataFrame:
        """
        Extract training data from log files.
        
        Args:
            days: Number of days of logs to process
            sample_ratio: Fraction of data to sample (0.0-1.0)
        
        Returns:
            DataFrame with features and labels
        """
        log(f"[EXTRACT] Starting extraction from last {days} days...")
        
        # Find log files in date range
        cutoff_date = datetime.now() - timedelta(days=days)
        log_files = self._find_log_files(cutoff_date)
        
        log(f"[EXTRACT] Found {len(log_files)} log files to process")
        
        # Extract data from each file
        all_samples = []
        for log_file in log_files:
            samples = self._extract_from_file(log_file)
            all_samples.extend(samples)
            
            if len(all_samples) % 1000 == 0:
                log(f"[EXTRACT] Extracted {len(all_samples)} samples so far...")
        
        log(f"[EXTRACT] Total raw samples: {len(all_samples)}")
        
        # Convert to DataFrame
        df = pd.DataFrame(all_samples)
        
        # Sample if requested
        if sample_ratio < 1.0:
            df = df.sample(frac=sample_ratio, random_state=42)
            log(f"[EXTRACT] Sampled to {len(df)} samples (ratio={sample_ratio})")
        
        # Save raw data
        output_path = self.output_dir / f"raw_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(output_path, index=False)
        log(f"[EXTRACT] Saved raw data to {output_path}")
        
        return df
    
    def _find_log_files(self, cutoff_date: datetime) -> List[Path]:
        """Find log files newer than cutoff date."""
        log_files = []
        
        for log_file in self.log_dir.rglob("*.log*"):
            # Check file modification time
            if log_file.stat().st_mtime > cutoff_date.timestamp():
                log_files.append(log_file)
        
        return sorted(log_files, key=lambda x: x.stat().st_mtime)
    
    def _extract_from_file(self, log_file: Path) -> List[Dict]:
        """Extract samples from a single log file."""
        samples = []
        open_trades: Dict[str, Dict] = {}  # market -> trade_data
        
        try:
            # Handle gzipped files
            if log_file.suffix == '.gz':
                with gzip.open(log_file, 'rt', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            else:
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    lines = f.readlines()
            
            for line in lines:
                # Look for trade opened
                opened_match = self.trade_opened_pattern.search(line)
                if opened_match:
                    market = opened_match.group(1)
                    price = float(opened_match.group(2))
                    
                    # Extract indicators from nearby lines (look back 10 lines)
                    indicators = self._extract_indicators_from_context(lines, lines.index(line), lookback=10)
                    
                    if indicators:
                        open_trades[market] = {
                            'market': market,
                            'entry_price': price,
                            'timestamp': self._extract_timestamp(line),
                            **indicators
                        }
                
                # Look for trade closed
                closed_match = self.trade_closed_pattern.search(line)
                if closed_match:
                    market = closed_match.group(1)
                    profit = float(closed_match.group(2))
                    
                    # Match with open trade
                    if market in open_trades:
                        trade_data = open_trades.pop(market)
                        trade_data['profit'] = profit
                        trade_data['label'] = 1 if profit > 0 else 0  # Binary: win/loss
                        trade_data['exit_timestamp'] = self._extract_timestamp(line)
                        
                        samples.append(trade_data)
        
        except Exception as e:
            log(f"[EXTRACT] Error processing {log_file}: {e}", level='warning')
        
        return samples
    
    def _extract_indicators_from_context(self, lines: List[str], current_idx: int, lookback: int = 10) -> Optional[Dict]:
        """Extract indicator values from nearby log lines."""
        # Look back up to 'lookback' lines
        start_idx = max(0, current_idx - lookback)
        context_lines = lines[start_idx:current_idx + 1]
        
        indicators = {}
        
        for line in reversed(context_lines):
            # Try to extract RSI, MACD, SMA, etc.
            if 'RSI' in line:
                match = re.search(r'RSI[:\s]+([\d.]+)', line)
                if match and 'rsi' not in indicators:
                    indicators['rsi'] = float(match.group(1))
            
            if 'MACD' in line:
                match = re.search(r'MACD[:\s]+([-\d.]+)', line)
                if match and 'macd' not in indicators:
                    indicators['macd'] = float(match.group(1))
            
            if 'SMA' in line or 'sma' in line.lower():
                match = re.search(r'(?:SMA|sma)[:\s]+([\d.]+)', line)
                if match and 'sma' not in indicators:
                    indicators['sma'] = float(match.group(1))
            
            if 'volume' in line.lower():
                match = re.search(r'volume[:\s]+([\d.]+)', line, re.IGNORECASE)
                if match and 'volume' not in indicators:
                    indicators['volume'] = float(match.group(1))
            
            # Stop early if we have enough indicators
            if len(indicators) >= 4:
                break
        
        # Return None if we didn't find minimum indicators
        if len(indicators) < 2:
            return None
        
        # Fill missing with defaults
        indicators.setdefault('rsi', 50.0)
        indicators.setdefault('macd', 0.0)
        indicators.setdefault('sma', 0.0)
        indicators.setdefault('volume', 0.0)
        
        return indicators
    
    def _extract_timestamp(self, line: str) -> str:
        """Extract timestamp from log line."""
        # Try common timestamp formats
        timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2})', line)
        if timestamp_match:
            return timestamp_match.group(1)
        
        return datetime.now().isoformat()
    
    def load_trade_log(self, trade_log_path: str = "data/trade_log.json") -> List[Dict]:
        """
        Alternative: Extract features from trade_log.json closed trades.
        More reliable than log parsing if trade_log has complete data.
        """
        log(f"[EXTRACT] Loading from {trade_log_path}...")
        
        try:
            with open(trade_log_path, 'r') as f:
                data = json.load(f)
            
            closed_trades = data.get('closed', [])
            log(f"[EXTRACT] Found {len(closed_trades)} closed trades in trade_log")
            
            samples = []
            for trade in closed_trades:
                # Extract basic features (limited in trade_log)
                sample = {
                    'market': trade.get('market', 'UNKNOWN'),
                    'entry_price': trade.get('buy_price', 0),
                    'exit_price': trade.get('sell_price', 0),
                    'profit': trade.get('profit', 0),
                    'label': 1 if trade.get('profit', 0) > 0 else 0,
                    'timestamp': trade.get('timestamp', 0),
                    'close_timestamp': trade.get('close_timestamp', 0),
                    # Limited indicators in trade_log - need to reconstruct
                    'rsi': 50.0,  # Placeholder
                    'macd': 0.0,  # Placeholder
                    'sma': trade.get('buy_price', 0),  # Approximate
                    'volume': 0.0,  # Placeholder
                }
                samples.append(sample)
            
            df = pd.DataFrame(samples)
            return df
        
        except Exception as e:
            log(f"[EXTRACT] Error loading trade_log: {e}", level='error')
            return pd.DataFrame()


def main():
    """CLI entry point for data extraction."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Extract ML training data from logs')
    parser.add_argument('--days', type=int, default=90, help='Days of logs to process')
    parser.add_argument('--sample', type=float, default=1.0, help='Sample ratio (0.0-1.0)')
    parser.add_argument('--source', choices=['logs', 'trade_log'], default='logs', 
                       help='Data source: logs or trade_log.json')
    parser.add_argument('--output-dir', type=str, default='ai/training_data',
                       help='Output directory for extracted data')
    
    args = parser.parse_args()
    
    extractor = TrainingDataExtractor(output_dir=args.output_dir)
    
    if args.source == 'logs':
        df = extractor.extract_from_logs(days=args.days, sample_ratio=args.sample)
    else:
        df = extractor.load_trade_log()
    
    # Save to CSV
    if not df.empty:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_file = Path(extractor.output_dir) / f'raw_data_{timestamp}.csv'
        df.to_csv(output_file, index=False)
        print(f"\n=== Extraction Complete ===")
        print(f"Total samples: {len(df)}")
        print(f"Win rate: {df['label'].mean():.2%}")
        print(f"Columns: {list(df.columns)}")
        print(f"\nData saved to: {output_file}")
    else:
        print("\n⚠️  No data extracted!")


if __name__ == "__main__":
    main()
