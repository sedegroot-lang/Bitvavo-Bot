"""Blueprints package - Route modules."""


def register_blueprints(app):
    """Register all blueprints with the app."""
    from .main import main_bp
    from .api import api_bp
    
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp, url_prefix='/api/v1')
