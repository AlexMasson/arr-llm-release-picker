"""
LLM integration for AI-powered release selection.
"""

import json
import logging
from typing import Optional, Tuple, List, Dict, Any

import requests

from .config import get_config
from .prompts import get_system_prompt_for_profile, format_releases_for_ai

logger = logging.getLogger(__name__)

# Hardcoded user prompt template - system prompt is configurable per profile
USER_PROMPT_TEMPLATE = """Media: {media_title}
Quality Profile: {profile_name}

{releases_text}

Select the best release. Respond with JSON only: {{"choice": <number>, "reason": "<brief reason>"}}"""


def ask_ai_for_selection(
    releases: List[Dict[str, Any]],
    media_title: str,
    profile_name: str,
    service: str = 'radarr'
) -> Tuple[Optional[int], str]:
    """
    Ask AI to select the best release.
    
    Args:
        releases: List of releases to choose from.
        media_title: Title of the movie/series.
        profile_name: Quality profile name.
        service: Service name ('radarr' or 'sonarr').
        
    Returns:
        Tuple of (1-based index or None, reason string).
    """
    cfg = get_config()
    system_prompt = get_system_prompt_for_profile(service, profile_name)
    
    if system_prompt is None:
        return None, "AI bypassed - no prompt for this profile"

    releases_text = format_releases_for_ai(releases, media_title)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        media_title=media_title,
        releases_text=releases_text,
        profile_name=profile_name
    )

    logger.info(
        f"Asking AI ({cfg.llm_model}) for '{media_title}' "
        f"[{service}/{profile_name}] with {len(releases)} releases"
    )

    try:
        headers: Dict[str, str] = {'Content-Type': 'application/json'}
        if cfg.llm_api_key:
            headers['Authorization'] = f'Bearer {cfg.llm_api_key}'

        response = requests.post(
            f"{cfg.llm_api_url}/chat/completions",
            headers=headers,
            json={
                'model': cfg.llm_model,
                'messages': [
                    {'role': 'system', 'content': system_prompt},
                    {'role': 'user', 'content': user_prompt}
                ],
                'temperature': 0.1,
                'max_tokens': 300
            },
            timeout=cfg.llm_timeout
        )
        response.raise_for_status()

        result = response.json()
        content = result['choices'][0]['message']['content'].strip()

        # Parse JSON from potential markdown code block
        if content.startswith('```'):
            lines = content.split('\n')
            json_lines = []
            in_block = False
            for line in lines:
                if line.startswith('```') and not in_block:
                    in_block = True
                    continue
                if line.startswith('```') and in_block:
                    break
                if in_block:
                    json_lines.append(line)
            content = '\n'.join(json_lines)

        parsed = json.loads(content)
        choice = parsed.get('choice')
        reason = parsed.get('reason', 'No reason provided')

        if not isinstance(choice, int):
            return None, f"Invalid choice type: {type(choice)}"

        logger.info(f"AI selected release #{choice}: {reason}")
        return choice, reason

    except json.JSONDecodeError as e:
        logger.error(f"AI response parsing failed: {e}")
        return None, f"Invalid JSON response: {e}"
    except Exception as e:
        logger.error(f"AI selection failed: {e}")
        return None, str(e)
