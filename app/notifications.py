"""
Notification handling via ntfy.
"""

import logging
from typing import Optional, List, Dict, Any

import requests

from .config import get_config

logger = logging.getLogger(__name__)


def send_notification(
    title: str,
    message: str,
    priority: str = "default",
    tags: Optional[List[str]] = None
) -> None:
    """
    Send a notification via ntfy.
    
    Args:
        title: Notification title.
        message: Notification body.
        priority: Priority level (default, high, low).
        tags: Optional list of tags.
    """
    cfg = get_config()
    if not cfg.ntfy_url:
        return

    try:
        priority_map = {"low": 1, "default": 3, "high": 5}
        payload: Dict[str, Any] = {
            'topic': cfg.ntfy_topic,
            'title': title,
            'message': message,
            'priority': priority_map.get(priority, 3),
        }
        if tags:
            payload['tags'] = tags

        requests.post(cfg.ntfy_url.rstrip('/'), json=payload, timeout=10)
        logger.info(f"Notification sent: {title}")
    except Exception as e:
        logger.error(f"Failed to send notification: {e}")
