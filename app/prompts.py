"""
Prompt management and formatting.
"""

import logging
from typing import Optional, List, Dict, Any

from .config import get_config

logger = logging.getLogger(__name__)


def get_system_prompt_for_profile(service: str, profile_name: str) -> Optional[str]:
    """
    Get system prompt for a service and quality profile (exact match only).
    
    Args:
        service: Service name ('radarr' or 'sonarr').
        profile_name: Name of the quality profile.
        
    Returns:
        System prompt string if found, None if no prompt configured for this profile.
    """
    cfg = get_config()
    normalized_service = service.lower().strip()
    normalized_profile = profile_name.lower().strip()

    service_prompts = cfg.service_prompts.get(normalized_service, {})
    
    if normalized_profile in service_prompts:
        logger.info(f"Using prompt for {normalized_service}/{normalized_profile}")
        return service_prompts[normalized_profile]

    logger.info(f"No prompt configured for {service}/{profile_name}, AI bypassed")
    return None


def format_releases_for_ai(releases: List[Dict[str, Any]], movie_title: str) -> str:
    """
    Format releases from DDO payload for AI consumption.
    
    Each release is formatted with:
    - Index number and status (RADARR PREFERRED or available)
    - Release title
    - Size, quality, indexer
    - Seeders, custom format score, age
    - Languages, custom formats, indexer flags
    
    Args:
        releases: List of release dictionaries from Radarr.
        movie_title: Title of the movie.
        
    Returns:
        Formatted string for the AI prompt.
    """
    if not releases:
        return "No releases available."

    lines: List[str] = [
        f"Available releases for '{movie_title}' ({len(releases)} total):\n"
    ]

    for i, r in enumerate(releases, 1):
        size_gb = r.get('size', 0) / (1024 ** 3)
        seeders = r.get('seeders', 0)
        quality = r.get('quality', 'Unknown')
        indexer = r.get('indexer', 'Unknown')
        title = r.get('title', 'Unknown')
        score = r.get('customFormatScore', 0)
        languages = r.get('languages', [])
        custom_formats = r.get('customFormats', [])
        is_selected = r.get('isSelected', False)
        age_minutes = r.get('ageMinutes', 0)
        indexer_flags = r.get('indexerFlags', [])

        # Format age
        if age_minutes < 60:
            age_str = f"{int(age_minutes)}m"
        elif age_minutes < 1440:
            age_str = f"{int(age_minutes / 60)}h"
        else:
            age_str = f"{int(age_minutes / 1440)}d"

        status = "RADARR PREFERRED" if is_selected else ""
        flags_str = f" Flags: [{', '.join(indexer_flags)}]" if indexer_flags else ""
        status_line = f"   {status}\n" if status else ""

        lines.append(
            f"{i}. {title}\n"
            f"   Size: {size_gb:.2f} GB | Quality: {quality} | Indexer: {indexer}\n"
            f"   Seeders: {seeders} | CF Score: {score:+d} | Age: {age_str}\n"
            f"   Languages: {', '.join(languages) if languages else 'Unknown'}\n"
            f"   Custom Formats: {', '.join(custom_formats) if custom_formats else 'None'}"
            f"{flags_str}\n"
            f"{status_line}"
        )

    return "\n".join(lines)
