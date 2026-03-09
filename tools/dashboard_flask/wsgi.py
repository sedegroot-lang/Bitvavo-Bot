"""WSGI entrypoint for production deployment."""
from . import create_app, socketio

# Create application instance
app = create_app('production')

if __name__ == '__main__':
    # Production run with SocketIO
    socketio.run(
        app,
        host='0.0.0.0',
        port=5001,
        debug=False,
        allow_unsafe_werkzeug=True
    )
