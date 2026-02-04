"""
Sonarr API interactions.
"""

import logging
from typing import Any, List

import requests

from .config import get_config

logger = logging.getLogger(__name__)


def sonarr_api_get(endpoint: str) -> Any:
    """
    Make a GET request to Sonarr API.
    
    Args:
        endpoint: API endpoint (without /api/v3 prefix).
        
    Returns:
        Parsed JSON response.
        
    Raises:
        requests.HTTPError: If the request fails.
    """
    cfg = get_config()
    if not cfg.sonarr:
        raise RuntimeError("Sonarr not configured")
    url = f"{cfg.sonarr.url}/api/v3/{endpoint}"
    headers = {'X-Api-Key': cfg.sonarr.api_key}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def get_quality_profile_name(series_id: int) -> str:
    """
    Get quality profile name for a series.
    
    Args:
        series_id: Sonarr series ID.
        
    Returns:
        Profile name or 'default' if lookup fails.
    """
    try:
        series = sonarr_api_get(f"series/{series_id}")
        profile_id = series.get('qualityProfileId', 0)
        profiles = sonarr_api_get("qualityprofile")
        for p in profiles:
            if p.get('id') == profile_id:
                return p.get('name', 'default')
    except Exception as e:
        logger.warning(f"Failed to get quality profile: {e}")
    return 'default'


def get_series_tags(series_id: int) -> List[str]:
    """
    Get tag names for a series.
    
    Args:
        series_id: Sonarr series ID.
        
    Returns:
        List of lowercase tag names.
    """
    try:
        series = sonarr_api_get(f"series/{series_id}")
        tag_ids = series.get('tags', [])
        if not tag_ids:
            return []

        all_tags = sonarr_api_get("tag")
        tag_map = {t['id']: t['label'].lower() for t in all_tags}
        return [tag_map[tid] for tid in tag_ids if tid in tag_map]
    except Exception as e:
        logger.error(f"Failed to get series tags: {e}")
        return []
