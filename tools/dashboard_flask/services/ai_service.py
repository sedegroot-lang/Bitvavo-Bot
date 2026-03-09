"""AI Service - Business logic for AI suggestions and metrics."""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class AISuggestion:
    """AI trading suggestion."""
    market: str
    symbol: str
    action: str  # 'buy', 'sell', 'hold'
    confidence: float
    reason: str
    timestamp: Optional[datetime]
    price_target: Optional[float]
    stop_loss: Optional[float]


@dataclass
class AIModelMetrics:
    """AI model performance metrics."""
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    total_predictions: int
    correct_predictions: int
    last_trained: Optional[datetime]
    feature_importance: Dict[str, float]


class AIService:
    """Service for AI trading suggestions and model metrics."""
    
    def __init__(self, data_service):
        self.data_service = data_service
    
    def get_suggestions(self) -> List[AISuggestion]:
        """Get current AI trading suggestions."""
        data = self.data_service.load_json_file('ai/ai_suggestions.json', {})
        suggestions_list = data.get('suggestions', [])
        
        result = []
        for s in suggestions_list:
            try:
                suggestion = AISuggestion(
                    market=s.get('market', ''),
                    symbol=s.get('market', '').replace('-EUR', ''),
                    action=s.get('action', 'hold'),
                    confidence=float(s.get('confidence', 0)),
                    reason=s.get('reason', ''),
                    timestamp=self._parse_timestamp(s.get('timestamp')),
                    price_target=s.get('price_target'),
                    stop_loss=s.get('stop_loss'),
                )
                result.append(suggestion)
            except Exception as e:
                logger.warning(f"Error parsing AI suggestion: {e}")
        
        # Sort by confidence descending
        result.sort(key=lambda x: x.confidence, reverse=True)
        return result
    
    def get_model_metrics(self) -> Optional[AIModelMetrics]:
        """Get AI model performance metrics."""
        data = self.data_service.load_json_file('ai/ai_model_metrics.json', {})
        
        if not data:
            return None
        
        try:
            return AIModelMetrics(
                accuracy=float(data.get('accuracy', 0)),
                precision=float(data.get('precision', 0)),
                recall=float(data.get('recall', 0)),
                f1_score=float(data.get('f1_score', 0)),
                total_predictions=int(data.get('total_predictions', 0)),
                correct_predictions=int(data.get('correct_predictions', 0)),
                last_trained=self._parse_timestamp(data.get('last_trained')),
                feature_importance=data.get('feature_importance', {}),
            )
        except Exception as e:
            logger.error(f"Error parsing AI metrics: {e}")
            return None
    
    def get_market_analysis(self) -> Dict[str, Any]:
        """Get AI market analysis data."""
        return self.data_service.load_json_file('ai/ai_advanced_analysis.json', {})
    
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


# Singleton instance
_ai_service = None


def get_ai_service():
    """Get or create AIService singleton."""
    global _ai_service
    if _ai_service is None:
        from .data_service import get_data_service
        _ai_service = AIService(get_data_service())
    return _ai_service
