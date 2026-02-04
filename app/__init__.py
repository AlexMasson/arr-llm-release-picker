"""
arr-llm-release-picker - Intelligent release selection for Radarr using LLM.

Uses the Download Decision Override webhook feature (Radarr fork).
Radarr sends all candidate releases BEFORE making a download decision,
allowing AI to select the best release without double indexer queries.
"""

from flask import Flask

from .config import init_app
from .routes import bp


def create_app() -> Flask:
    """
    Create and configure the Flask application.
    
    Returns:
        Configured Flask application instance.
    """
    # Initialize configuration first
    init_app()
    
    # Create Flask app
    application = Flask(__name__)
    
    # Register routes blueprint
    application.register_blueprint(bp)
    
    return application


# Create app instance for gunicorn
app = create_app()
