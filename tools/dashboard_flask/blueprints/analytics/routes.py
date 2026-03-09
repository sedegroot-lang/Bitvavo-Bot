"""Analytics blueprint routes."""
from flask import render_template
from . import analytics_bp

# Import services with fallback
try:
    from ...services import get_data_service
except ImportError:
    import sys
    from pathlib import Path
    services_path = Path(__file__).parent.parent.parent / 'services'
    if str(services_path.parent) not in sys.path:
        sys.path.insert(0, str(services_path.parent))
    from services import get_data_service


# Note: These routes are placeholders. The actual complex routes
# remain in app.py until full migration is complete.
# Blueprint registration allows gradual migration.
