"""
Trade Block Analyzer - Comprehensive trade blocking diagnostics
Analyzes all possible reasons why trades aren't being opened
"""

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List


class TradeBlockAnalyzer:
    """Analyzes all factors that can block trade execution"""

    def __init__(self, bot_root: str = None):
        self.bot_root = bot_root or os.getcwd()

    def analyze(self) -> Dict[str, Any]:
        """Perform complete analysis of trade blocking factors"""
        analysis = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "config_blocks": self._check_config(),
            "balance_blocks": self._check_balance(),
            "market_blocks": self._check_markets(),
            "api_blocks": self._check_api_errors(),
            "scan_health": self._check_scan_health(),
            "recent_blocks": self._get_recent_block_reasons(),
            "summary": {},
        }

        # Generate summary
        analysis["summary"] = self._generate_summary(analysis)
        return analysis

    def _check_config(self) -> Dict[str, Any]:
        """Check configuration values that might block trades"""
        try:
            config_path = os.path.join(self.bot_root, "config", "bot_config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            blocks = []
            warnings = []

            # Check MIN_SCORE_TO_BUY
            min_score = config.get("MIN_SCORE_TO_BUY", 7.0)
            if min_score > 5.0:
                warnings.append(f"MIN_SCORE_TO_BUY very high: {min_score} (typical: 2-5)")
            if min_score > 10.0:
                blocks.append(f"MIN_SCORE_TO_BUY unreachable: {min_score}")

            # Check RSI range
            rsi_min = config.get("RSI_MIN_BUY", 35.0)
            rsi_max = config.get("RSI_MAX_BUY", 65.0)
            if rsi_min >= rsi_max:
                blocks.append(f"RSI range impossible: {rsi_min}-{rsi_max}")
            if (rsi_max - rsi_min) < 10:
                warnings.append(f"RSI range very narrow: {rsi_min}-{rsi_max}")

            # Check MAX_OPEN_TRADES
            max_trades = config.get("MAX_OPEN_TRADES", 5)
            if max_trades == 0:
                blocks.append("MAX_OPEN_TRADES is 0 - no trades allowed")

            # Check BASE_AMOUNT
            base_amount = config.get("BASE_AMOUNT_EUR")
            if base_amount is None or base_amount == 0:
                warnings.append("BASE_AMOUNT_EUR not set or zero")

            # Check volume filter
            min_volume = config.get("MIN_AVG_VOLUME_1M", 0)
            if min_volume > 50:
                warnings.append(f"MIN_AVG_VOLUME_1M very high: {min_volume}")

            return {
                "status": "blocking" if blocks else ("warning" if warnings else "ok"),
                "blocks": blocks,
                "warnings": warnings,
                "values": {
                    "MIN_SCORE_TO_BUY": min_score,
                    "RSI_MIN_BUY": rsi_min,
                    "RSI_MAX_BUY": rsi_max,
                    "MAX_OPEN_TRADES": max_trades,
                    "BASE_AMOUNT_EUR": base_amount,
                    "MIN_AVG_VOLUME_1M": min_volume,
                },
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_balance(self) -> Dict[str, Any]:
        """Check if balance is sufficient for trades"""
        try:
            acc_path = os.path.join(self.bot_root, "data", "account_overview.json")
            with open(acc_path, "r", encoding="utf-8") as f:
                acc = json.load(f)

            eur_balance = acc.get("eur_available", 0)
            open_trades = acc.get("open_trade_count", 0)

            config_path = os.path.join(self.bot_root, "config", "bot_config.json")
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)

            base_amount = config.get("BASE_AMOUNT_EUR", 12.0)
            max_trades = config.get("MAX_OPEN_TRADES", 5)

            blocks = []
            warnings = []

            if eur_balance < base_amount:
                blocks.append(f"Insufficient balance: €{eur_balance:.2f} < €{base_amount:.2f} (BASE_AMOUNT)")
            elif eur_balance < base_amount * 2:
                warnings.append(
                    f"Low balance: €{eur_balance:.2f}, can only open {int(eur_balance / base_amount)} trade(s)"
                )

            if open_trades >= max_trades:
                blocks.append(f"Max trades reached: {open_trades}/{max_trades}")

            return {
                "status": "blocking" if blocks else ("warning" if warnings else "ok"),
                "blocks": blocks,
                "warnings": warnings,
                "balance": eur_balance,
                "open_trades": open_trades,
                "max_trades": max_trades,
                "base_amount": base_amount,
                "can_open_trades": int(eur_balance / base_amount) if base_amount > 0 else 0,
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_markets(self) -> Dict[str, Any]:
        """Check market-level blocking (performance filter, external trades)"""
        try:
            # Check performance filter
            perf_blocks = []
            log_path = os.path.join(self.bot_root, "logs", "bot_log.txt")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-200:]  # Last 200 lines
                    for line in lines:
                        if "Performance filter blokkeert" in line:
                            # Extract market name
                            parts = line.split("Performance filter blokkeert ")
                            if len(parts) > 1:
                                market = parts[1].split(":")[0].strip()
                                if market not in perf_blocks:
                                    perf_blocks.append(market)

            # Check external trades
            ext_trades_path = os.path.join(self.bot_root, "data", "active_external_trades.json")
            external_trades = []
            if os.path.exists(ext_trades_path):
                with open(ext_trades_path, "r", encoding="utf-8") as f:
                    external_trades = json.load(f)

            blocks = []
            if perf_blocks:
                blocks.append(f"{len(perf_blocks)} markets blocked by performance filter: {', '.join(perf_blocks[:5])}")
            if external_trades:
                blocks.append(f"{len(external_trades)} markets claimed by external sources")

            return {
                "status": "info",
                "performance_filtered": perf_blocks,
                "external_trades": external_trades,
                "total_blocked_markets": len(perf_blocks) + len(external_trades),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_api_errors(self) -> Dict[str, Any]:
        """Check for API errors that might block trading"""
        try:
            errors = []
            log_path = os.path.join(self.bot_root, "logs", "bot_log.txt")
            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-500:]  # Last 500 lines
                    for line in lines:
                        if "ERROR" in line or "403" in line or "429" in line:
                            timestamp = line.split("]")[0].replace("[", "") if "]" in line else "unknown"
                            error_msg = line.split("ERROR:")[-1].strip() if "ERROR:" in line else line.strip()
                            errors.append({"timestamp": timestamp, "message": error_msg[:200]})

            # Get unique error types
            error_types = {}
            for err in errors[-20:]:  # Last 20 errors
                msg = err["message"]
                if "403" in msg:
                    error_types["api_403_forbidden"] = error_types.get("api_403_forbidden", 0) + 1
                elif "429" in msg:
                    error_types["api_rate_limit"] = error_types.get("api_rate_limit", 0) + 1
                elif "cannot import" in msg:
                    error_types["import_error"] = error_types.get("import_error", 0) + 1
                else:
                    error_types["other"] = error_types.get("other", 0) + 1

            blocks = []
            if error_types.get("api_403_forbidden", 0) > 5:
                blocks.append("Multiple API 403 errors - possible permission/auth issue")
            if error_types.get("api_rate_limit", 0) > 3:
                blocks.append("API rate limit errors detected")
            if error_types.get("import_error", 0) > 0:
                blocks.append("Import errors detected - code issues")

            return {
                "status": "blocking" if blocks else ("warning" if error_types else "ok"),
                "blocks": blocks,
                "error_types": error_types,
                "recent_errors": errors[-10:],  # Last 10 errors
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _check_scan_health(self) -> Dict[str, Any]:
        """Check if scans are completing successfully"""
        try:
            log_path = os.path.join(self.bot_root, "logs", "bot_log.txt")
            scan_starts = []
            scan_completions = []
            evaluations = []

            if os.path.exists(log_path):
                with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()[-1000:]  # Last 1000 lines
                    for line in lines:
                        if "Nieuwe scan gestart" in line:
                            scan_starts.append(line)
                        elif "Markten:" in line and "totaal" in line and "geëvalueerd" in line:
                            scan_completions.append(line)
                        elif "Evaluating" in line and "SCAN" in line:
                            evaluations.append(line)

            warnings = []
            blocks = []

            # Check if scans are completing
            if len(scan_starts) > 0 and len(scan_completions) == 0:
                blocks.append("Scans starting but NOT completing - possible crash/timeout")

            # Check evaluation progress
            if evaluations:
                # Get last evaluation
                last_eval = evaluations[-1]
                if "(" in last_eval and "/" in last_eval:
                    progress = last_eval.split("(")[1].split(")")[0]
                    current, total = progress.split("/")
                    current = int(current)
                    total = int(total)
                    if current < total:
                        warnings.append(f"Last scan incomplete: {current}/{total} markets evaluated")

            return {
                "status": "blocking" if blocks else ("warning" if warnings else "ok"),
                "blocks": blocks,
                "warnings": warnings,
                "scan_starts": len(scan_starts),
                "scan_completions": len(scan_completions),
                "markets_evaluated": len(evaluations),
                "completion_rate": f"{len(scan_completions)}/{len(scan_starts)}" if scan_starts else "N/A",
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def _get_recent_block_reasons(self) -> List[Dict[str, Any]]:
        """Get recent block reasons from file"""
        try:
            block_file = os.path.join(self.bot_root, "data", "trade_block_reasons.json")
            if os.path.exists(block_file):
                with open(block_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "blocks" in data:
                        return data["blocks"][-20:]  # Last 20
                    elif isinstance(data, list):
                        return data[-20:]
            return []
        except Exception as e:
            return [{"error": str(e)}]

    def _generate_summary(self, analysis: Dict[str, Any]) -> Dict[str, Any]:
        """Generate executive summary of blocking factors"""
        blocking_factors = []
        warning_factors = []

        for category, data in analysis.items():
            if category in ["timestamp", "summary", "recent_blocks"]:
                continue

            if isinstance(data, dict):
                if data.get("status") == "blocking":
                    blocking_factors.extend(data.get("blocks", []))
                elif data.get("status") == "warning":
                    warning_factors.extend(data.get("warnings", []))

        return {
            "is_blocked": len(blocking_factors) > 0,
            "blocking_factors": blocking_factors,
            "warning_factors": warning_factors,
            "status": "BLOCKED" if blocking_factors else ("WARNING" if warning_factors else "OK"),
        }


def analyze_trade_blocks() -> Dict[str, Any]:
    """Main entry point for trade block analysis"""
    analyzer = TradeBlockAnalyzer()
    return analyzer.analyze()


if __name__ == "__main__":
    import pprint

    result = analyze_trade_blocks()
    pprint.pprint(result)
