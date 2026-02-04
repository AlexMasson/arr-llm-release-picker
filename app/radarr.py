"""
Radarr API interactions.
"""

import logging
from typing import Any, List

import requests

from .config import get_config

logger = logging.getLogger(__name__)


def radarr_api_get(endpoint: str) -> Any:
    """
    Make a GET request to Radarr API.
    
    Args:
        endpoint: API endpoint (without /api/v3 prefix).
        
    Returns:
        Parsed JSON response.
        
    Raises:
        requests.HTTPError: If the request fails.
    """
    cfg = get_config()
    url = f"{cfg.radarr.url}/api/v3/{endpoint}"
    headers = {'X-Api-Key': cfg.radarr.api_key}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def get_quality_profile_name(movie_id: int) -> str:
    """
    Get quality profile name for a movie.
    
    Args:
        movie_id: Radarr movie ID.
        
    Returns:
        Profile name or 'default' if lookup fails.
    """
    try:
        movie = radarr_api_get(f"movie/{movie_id}")
        profile_id = movie.get('qualityProfileId', 0)
        profiles = radarr_api_get("qualityprofile")
        for p in profiles:
            if p.get('id') == profile_id:
                return p.get('name', 'default')
    except Exception as e:
        logger.warning(f"Failed to get quality profile: {e}")
    return 'default'


def get_movie_tags(movie_id: int) -> List[str]:
    """
    Get tag names for a movie.
    
    Args:
        movie_id: Radarr movie ID.
        
    Returns:
        List of lowercase tag names.
    """
    try:
        movie = radarr_api_get(f"movie/{movie_id}")
        tag_ids = movie.get('tags', [])
        if not tag_ids:
            return []

        all_tags = radarr_api_get("tag")
        tag_map = {t['id']: t['label'].lower() for t in all_tags}
        return [tag_map[tid] for tid in tag_ids if tid in tag_map]
    except Exception as e:
        logger.error(f"Failed to get movie tags: {e}")
        return []
