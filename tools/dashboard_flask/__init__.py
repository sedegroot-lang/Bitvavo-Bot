"""Flask Dashboard Application Factory."""
import os
import logging
from flask import Flask
from flask_socketio import SocketIO

# Create SocketIO instance at module level
socketio = SocketIO()


def create_app(config_name: str = None) -> Flask:
    """
    Application factory pattern.
    
    Args:
        config_name: Configuration name ('development', 'production', 'testing')
        
    Returns:
        Configured Flask application instance
    """
    # Determine config from environment or parameter
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'production')
    
    # Create Flask app
    app = Flask(__name__)
    
    # Load configuration
    from .config import config_map
    app.config.from_object(config_map.get(config_name, config_map['production']))
    
    # Configure logging
    configure_logging(app)
    
    # Initialize SocketIO
    socketio.init_app(
        app, 
        cors_allowed_origins="*", 
        async_mode='threading',
        allow_unsafe_werkzeug=True
    )
    
    # Register blueprints
    register_all_blueprints(app)
    
    # Register error handlers
    register_error_handlers(app)
    
    # Register Jinja2 filters and context processors
    register_template_helpers(app)
    
    app.logger.info(f"Flask app created with config: {config_name}")
    
    return app


def configure_logging(app: Flask) -> None:
    """Configure application logging."""
    log_level = logging.DEBUG if app.config.get('DEBUG') else logging.INFO
    
    logging.basicConfig(
        level=log_level,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Reduce noise from external libraries
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('werkzeug').setLevel(logging.WARNING)


def register_all_blueprints(app: Flask) -> None:
    """Register all application blueprints."""
    # Main blueprint (portfolio, hodl, hedge)
    try:
        from .blueprints.main import main_bp
        app.register_blueprint(main_bp)
        app.logger.debug("Registered main blueprint")
    except ImportError as e:
        app.logger.warning(f"Could not load main blueprint: {e}")
    
    # API v1 blueprint
    try:
        from .blueprints.api import api_bp
        app.register_blueprint(api_bp, url_prefix='/api/v1')
        app.logger.debug("Registered API v1 blueprint")
    except ImportError as e:
        app.logger.warning(f"Could not load API blueprint: {e}")
    
    # Trading blueprint (grid, ai)
    try:
        from .blueprints.trading import trading_bp
        app.register_blueprint(trading_bp)
        app.logger.debug("Registered trading blueprint")
    except ImportError as e:
        app.logger.debug(f"Trading blueprint not available: {e}")
    
    # Analytics blueprint (performance, analytics, reports)
    try:
        from .blueprints.analytics import analytics_bp
        app.register_blueprint(analytics_bp)
        app.logger.debug("Registered analytics blueprint")
    except ImportError as e:
        app.logger.debug(f"Analytics blueprint not available: {e}")
    
    # Settings blueprint (parameters, settings, notifications)
    try:
        from .blueprints.settings import settings_bp
        app.register_blueprint(settings_bp)
        app.logger.debug("Registered settings blueprint")
    except ImportError as e:
        app.logger.debug(f"Settings blueprint not available: {e}")


def register_error_handlers(app: Flask) -> None:
    """Register error handlers."""
    from flask import render_template, jsonify, request
    
    @app.errorhandler(404)
    def not_found_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Not found', 'status': 404}), 404
        return render_template('error.html', error_code=404, error_message='Page not found'), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Internal server error', 'status': 500}), 500
        return render_template('error.html', error_code=500, error_message='Internal server error'), 500


def register_template_helpers(app: Flask) -> None:
    """Register Jinja2 filters and context processors."""
    
    @app.template_filter('euro')
    def format_euro(value):
        """Format value as Euro currency."""
        try:
            return f"€{float(value):,.2f}"
        except (ValueError, TypeError):
            return "€0.00"
    
    @app.template_filter('percent')
    def format_percent(value):
        """Format value as percentage."""
        try:
            return f"{float(value):+.2f}%"
        except (ValueError, TypeError):
            return "0.00%"
    
    @app.template_filter('crypto_amount')
    def format_crypto_amount(value):
        """Format crypto amount with appropriate precision."""
        try:
            val = float(value)
            if val >= 1:
                return f"{val:.4f}"
            elif val >= 0.001:
                return f"{val:.6f}"
            else:
                return f"{val:.8f}"
        except (ValueError, TypeError):
            return "0"
    
    @app.context_processor
    def inject_globals():
        """Inject global variables into templates."""
        return {
            'app_name': 'Quantum Bot Dashboard',
            'version': '2.0.0',
        }
