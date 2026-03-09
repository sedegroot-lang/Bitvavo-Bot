"""API blueprint routes - v1 endpoints."""
from flask import jsonify, request
from . import api_bp

# Import services with proper path handling
try:
    from ...services import get_portfolio_service, get_data_service, get_price_service
except ImportError:
    import sys
    from pathlib import Path
    services_path = Path(__file__).parent.parent.parent / 'services'
    if str(services_path.parent) not in sys.path:
        sys.path.insert(0, str(services_path.parent))
    from services import get_portfolio_service, get_data_service, get_price_service


@api_bp.route('/health')
def health():
    """Health check endpoint."""
    return jsonify({
        'status': 'ok',
        'version': '1.0',
    })


@api_bp.route('/portfolio')
def portfolio():
    """Get portfolio data."""
    portfolio_service = get_portfolio_service()
    data = portfolio_service.get_portfolio_data()
    return jsonify(data)


@api_bp.route('/trades')
def trades():
    """Get all trades."""
    data_service = get_data_service()
    trades = data_service.load_trades()
    return jsonify(trades)


@api_bp.route('/trades/open')
def open_trades():
    """Get open trades."""
    data_service = get_data_service()
    open_trades = data_service.get_open_trades()
    return jsonify(open_trades)


@api_bp.route('/trades/closed')
def closed_trades():
    """Get closed trades."""
    data_service = get_data_service()
    closed = data_service.get_closed_trades()
    return jsonify(closed)


@api_bp.route('/config')
def config():
    """Get bot configuration."""
    data_service = get_data_service()
    config = data_service.load_config()
    return jsonify(config)


@api_bp.route('/heartbeat')
def heartbeat():
    """Get heartbeat status."""
    data_service = get_data_service()
    heartbeat = data_service.load_heartbeat()
    bot_online = data_service.is_bot_online()
    return jsonify({
        **heartbeat,
        'bot_online': bot_online,
    })


@api_bp.route('/prices')
def prices():
    """Get all EUR prices."""
    price_service = get_price_service()
    prices = price_service.prefetch_all_prices()
    return jsonify(prices)


@api_bp.route('/prices/<market>')
def price(market):
    """Get price for specific market."""
    price_service = get_price_service()
    price = price_service.get_price(market)
    if price is None:
        return jsonify({'error': 'Price not found'}), 404
    return jsonify({'market': market, 'price': price})


@api_bp.route('/deposits')
def deposits():
    """Get deposits data."""
    data_service = get_data_service()
    deposits = data_service.load_deposits()
    total = data_service.get_total_deposited()
    return jsonify({
        'deposits': deposits,
        'total': total,
    })


@api_bp.route('/ai/suggestions')
def ai_suggestions():
    """Get AI suggestions."""
    data_service = get_data_service()
    suggestions = data_service.load_ai_suggestions()
    return jsonify(suggestions)


@api_bp.route('/cache/invalidate', methods=['POST'])
def invalidate_cache():
    """Invalidate cache."""
    data_service = get_data_service()
    key = request.json.get('key') if request.is_json else None
    data_service.invalidate_cache(key)
    return jsonify({'status': 'ok', 'invalidated': key or 'all'})
