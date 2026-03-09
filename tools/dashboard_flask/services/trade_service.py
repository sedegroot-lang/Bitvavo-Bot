"""Trade service - Business logic for trade operations."""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class ClosedTrade:
    """Closed trade data structure."""
    market: str
    symbol: str
    buy_price: float
    sell_price: float
    amount: float
    invested: float
    returned: float
    pnl: float
    pnl_pct: float
    buy_time: Optional[datetime]
    sell_time: Optional[datetime]
    hold_duration_hours: float
    dca_level: int
    exit_reason: str


class TradeService:
    """Service for trade calculations and history."""
    
    def __init__(self, data_service):
        self.data_service = data_service
    
    def get_closed_trades(self, limit: int = 100) -> List[ClosedTrade]:
        """Get list of closed trades."""
        trades = self.data_service.load_trades()
        closed_list = trades.get('closed', [])
        
        result = []
        for trade in closed_list[-limit:]:
            try:
                closed = self._parse_closed_trade(trade)
                if closed:
                    result.append(closed)
            except Exception as e:
                logger.warning(f"Error parsing closed trade: {e}")
        
        # Sort by sell time descending
        result.sort(key=lambda x: x.sell_time or datetime.min, reverse=True)
        return result
    
    def _parse_closed_trade(self, trade: Dict[str, Any]) -> Optional[ClosedTrade]:
        """Parse a closed trade from raw data."""
        market = trade.get('market', '')
        if not market:
            return None
        
        buy_price = float(trade.get('buy_price', 0))
        sell_price = float(trade.get('sell_price', 0))
        amount = float(trade.get('amount', 0))
        invested = float(trade.get('invested_eur', buy_price * amount))
        returned = float(trade.get('returned_eur', sell_price * amount))
        pnl = returned - invested
        pnl_pct = ((returned / invested) - 1) * 100 if invested > 0 else 0
        
        # Parse timestamps
        buy_time = self._parse_timestamp(trade.get('buy_time'))
        sell_time = self._parse_timestamp(trade.get('sell_time'))
        
        # Calculate hold duration
        hold_duration = 0
        if buy_time and sell_time:
            delta = sell_time - buy_time
            hold_duration = delta.total_seconds() / 3600  # hours
        
        return ClosedTrade(
            market=market,
            symbol=market.replace('-EUR', ''),
            buy_price=buy_price,
            sell_price=sell_price,
            amount=amount,
            invested=invested,
            returned=returned,
            pnl=pnl,
            pnl_pct=pnl_pct,
            buy_time=buy_time,
            sell_time=sell_time,
            hold_duration_hours=hold_duration,
            dca_level=int(trade.get('dca_level', 0)),
            exit_reason=trade.get('exit_reason', 'unknown'),
        )
    
    def _parse_timestamp(self, value) -> Optional[datetime]:
        """Parse timestamp from various formats."""
        if not value:
            return None
        
        if isinstance(value, datetime):
            return value
        
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value)
            except:
                return None
        
        if isinstance(value, str):
            for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d']:
                try:
                    return datetime.strptime(value, fmt)
                except:
                    continue
        
        return None
    
    def get_trade_stats(self) -> Dict[str, Any]:
        """Calculate overall trading statistics."""
        closed = self.get_closed_trades(limit=1000)
        
        if not closed:
            return {
                'total_trades': 0,
                'winning_trades': 0,
                'losing_trades': 0,
                'win_rate': 0,
                'total_pnl': 0,
                'avg_pnl': 0,
                'avg_win': 0,
                'avg_loss': 0,
                'profit_factor': 0,
                'avg_hold_hours': 0,
            }
        
        winning = [t for t in closed if t.pnl > 0]
        losing = [t for t in closed if t.pnl < 0]
        
        total_wins = sum(t.pnl for t in winning)
        total_losses = abs(sum(t.pnl for t in losing))
        
        return {
            'total_trades': len(closed),
            'winning_trades': len(winning),
            'losing_trades': len(losing),
            'win_rate': len(winning) / len(closed) * 100 if closed else 0,
            'total_pnl': sum(t.pnl for t in closed),
            'avg_pnl': sum(t.pnl for t in closed) / len(closed) if closed else 0,
            'avg_win': total_wins / len(winning) if winning else 0,
            'avg_loss': total_losses / len(losing) if losing else 0,
            'profit_factor': total_wins / total_losses if total_losses > 0 else float('inf'),
            'avg_hold_hours': sum(t.hold_duration_hours for t in closed) / len(closed) if closed else 0,
        }


# Singleton instance
_trade_service = None


def get_trade_service():
    """Get or create TradeService singleton."""
    global _trade_service
    if _trade_service is None:
        from .data_service import get_data_service
        _trade_service = TradeService(get_data_service())
    return _trade_service
