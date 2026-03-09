"""Settings blueprint - Parameters, Settings, Notifications routes."""
from flask import Blueprint

settings_bp = Blueprint('settings', __name__)

from . import routes
