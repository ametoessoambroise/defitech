from app import create_app, socketio
import os

app = create_app()

if __name__ == "__main__":
    # Get port from environment variable or default to 5000
    port = int(os.environ.get("PORT", 5000))
    # Run the application with SocketIO
    socketio.run(app, debug=True, port=port)