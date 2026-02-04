#!/usr/bin/env python3
"""Entry point for arr-llm-release-picker."""
from app import create_app

app = create_app()

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
