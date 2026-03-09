"""Trading blueprint routes - Grid and AI pages."""
from flask import render_template, jsonify, request
from . import trading_bp

# Import services with fallback
try:
    from ...services import get_data_service, get_price_service
except ImportError:
    import sys
    from pathlib import Path
    services_path = Path(__file__).parent.parent.parent / 'services'
    if str(services_path.parent) not in sys.path:
        sys.path.insert(0, str(services_path.parent))
    from services import get_data_service, get_price_service


@trading_bp.route('/grid')
def grid():
    """Grid trading page - delegated to main app.py for now."""
    # Grid page is complex, keep in app.py until full migration
    from flask import redirect, url_for
    # For now, return empty template or redirect
    # The actual grid route is still in app.py
    pass


@trading_bp.route('/ai')
def ai_copilot():
    """AI Copilot page."""
    data_service = get_data_service()
    
    # Load AI data
    ai_suggestions = data_service.load_json_file('ai/ai_suggestions.json', {})
    ai_metrics = data_service.load_json_file('ai/ai_model_metrics.json', {})
    
    return render_template(
        'ai.html',
        suggestions=ai_suggestions,
        metrics=ai_metrics,
        active_tab='ai',
    )
