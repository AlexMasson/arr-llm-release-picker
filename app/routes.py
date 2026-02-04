"""
Flask routes for arr-llm-release-picker.
"""

import logging
from typing import Tuple, Any, Dict, List

import requests
from flask import Blueprint, request, jsonify

from .config import get_config, reload_prompts
from .radarr import radarr_api_get, get_quality_profile_name, get_movie_tags
from .sonarr import sonarr_api_get, get_quality_profile_name as get_quality_profile_name_sonarr, get_series_tags
from .notifications import send_notification
from .llm import ask_ai_for_selection

logger = logging.getLogger(__name__)

bp = Blueprint('main', __name__)


@bp.route('/health', methods=['GET'])
def health() -> Tuple[Any, int]:
    """Simple health check endpoint."""
    return jsonify({'status': 'healthy'}), 200


@bp.route('/test', methods=['GET'])
def test_connections() -> Tuple[Any, int]:
    """
    Test connections to Radarr, Sonarr and LLM APIs.
    
    Returns:
        JSON with connection status for each service.
    """
    cfg = get_config()
    results: Dict[str, Any] = {}

    # Test Radarr
    if cfg.radarr is not None:
        try:
            status = radarr_api_get("system/status")
            profiles = radarr_api_get("qualityprofile")
            results['radarr'] = {
                'status': 'ok',
                'version': status.get('version'),
                'profiles': [p['name'] for p in profiles]
            }
        except Exception as e:
            results['radarr'] = {'status': 'error', 'error': str(e)}
    else:
        results['radarr'] = {'status': 'not configured'}

    # Test Sonarr
    if cfg.sonarr is not None:
        try:
            status = sonarr_api_get("system/status")
            profiles = sonarr_api_get("qualityprofile")
            results['sonarr'] = {
                'status': 'ok',
                'version': status.get('version'),
                'profiles': [p['name'] for p in profiles]
            }
        except Exception as e:
            results['sonarr'] = {'status': 'error', 'error': str(e)}
    else:
        results['sonarr'] = {'status': 'not configured'}

    # Test LLM API
    try:
        headers: Dict[str, str] = {}
        if cfg.llm_api_key:
            headers['Authorization'] = f'Bearer {cfg.llm_api_key}'
        requests.get(f"{cfg.llm_api_url}/models", headers=headers, timeout=10)
        results['llm'] = {'status': 'ok', 'model': cfg.llm_model}
    except Exception as e:
        results['llm'] = {'status': 'error', 'error': str(e)}

    # Config summary
    results['config'] = {
        'dry_run': cfg.dry_run,
        'skip_tag': cfg.skip_tag,
        'prompts_dir': cfg.prompts_dir,
        'radarr_profiles': list(cfg.service_prompts.get('radarr', {}).keys()),
        'sonarr_profiles': list(cfg.service_prompts.get('sonarr', {}).keys()),
        'radarr_configured': cfg.radarr is not None,
        'sonarr_configured': cfg.sonarr is not None
    }

    return jsonify(results), 200


@bp.route('/reload', methods=['POST'])
def reload() -> Tuple[Any, int]:
    """Reload prompts from disk."""
    reload_prompts()
    cfg = get_config()
    return jsonify({
        'status': 'reloaded',
        'radarr_profiles': list(cfg.service_prompts.get('radarr', {}).keys()),
        'sonarr_profiles': list(cfg.service_prompts.get('sonarr', {}).keys())
    }), 200


@bp.route('/hook/radarr/override', methods=['POST'])
def webhook_radarr_override() -> Tuple[Any, int]:
    """
    Handle Radarr Download Decision Override webhook.
    
    Radarr sends all candidate releases BEFORE making a download decision.
    We select the best one using AI and return the GUID.
    
    Payload format:
        {eventType, instanceName, movie, releases[]}
        
    Response format:
        {approved, selectedReleaseGuid?, reason}
    """
    cfg = get_config()

    if cfg.radarr is None:
        return jsonify({'approved': True, 'reason': 'Radarr not configured'}), 200

    payload = request.json

    if not payload:
        return jsonify({'approved': True, 'reason': 'Empty payload'}), 200

    event_type = payload.get('eventType', '')
    if event_type != 'DownloadDecisionOverride':
        return jsonify({
            'approved': True,
            'reason': f'Ignored event type: {event_type}'
        }), 200

    movie = payload.get('movie', {})
    movie_id = movie.get('id')
    movie_title = movie.get('title', 'Unknown')
    releases = payload.get('releases', [])

    logger.info(
        f"Download Decision Override: '{movie_title}' ({len(releases)} releases)"
    )

    if not releases:
        logger.warning("No releases in payload")
        return jsonify({'approved': True, 'reason': 'No releases to evaluate'}), 200

    # Check for skip tag
    if movie_id:
        tags = get_movie_tags(movie_id)
        if cfg.skip_tag in tags:
            logger.info(f"Skipping AI for '{movie_title}' (tag '{cfg.skip_tag}')")
            return jsonify({
                'approved': True,
                'reason': f'Skipped: tag {cfg.skip_tag} present'
            }), 200

    # Get quality profile name
    profile_name = get_quality_profile_name(movie_id) if movie_id else 'unknown'

    # Ask AI to select
    choice, reason = ask_ai_for_selection(releases, movie_title, profile_name, service='radarr')

    # No prompts for this profile - let Radarr choose normally
    if choice is None and "AI bypassed" in reason:
        logger.info(f"No prompts for profile '{profile_name}', Radarr will choose")
        return jsonify({
            'approved': True,
            'reason': reason
        }), 200

    if choice is None or choice < 1 or choice > len(releases):
        logger.warning(f"AI made no valid selection: {reason}")
        send_notification(
            f"AI Warning: {movie_title}",
            f"Selection failed: {reason}\nUsing Radarr default",
            priority="low",
            tags=["warning"]
        )
        return jsonify({
            'approved': True,
            'reason': f'AI failed: {reason}, using default'
        }), 200

    selected = releases[choice - 1]
    selected_guid = selected.get('guid')
    selected_title = selected.get('title', 'Unknown')
    size_gb = round(selected.get('size', 0) / (1024 ** 3), 2)

    # Check if AI chose the same as Radarr's default
    default_selected = next((r for r in releases if r.get('isSelected')), None)
    is_same_as_default = (
        default_selected and default_selected.get('guid') == selected_guid
    )

    if is_same_as_default:
        logger.info(f"AI confirms Radarr selection: {selected_title}")
        return jsonify({
            'approved': True,
            'reason': f'AI confirms default: {reason}'
        }), 200

    logger.info(f"AI overrides to: {selected_title} ({size_gb} GB)")

    if cfg.dry_run:
        logger.info(f"[DRY RUN] Would select: {selected_title}")
        return jsonify({
            'approved': True,
            'reason': f'[DRY RUN] Would select: {selected_title}'
        }), 200

    send_notification(
        title=f"AI Override: {movie_title}",
        message=(
            f"Profile: {profile_name}\n"
            f"Release: {selected_title}\n"
            f"Size: {size_gb} GB\n"
            f"Reason: {reason}"
        ),
        tags=["movie_camera"]
    )

    return jsonify({
        'approved': True,
        'selectedReleaseGuid': selected_guid,
        'reason': reason
    }), 200


@bp.route('/simulate/radarr/<int:movie_id>', methods=['GET'])
def simulate_radarr(movie_id: int) -> Tuple[Any, int]:
    """
    Simulate AI selection for a movie (dry run).
    
    Fetches releases from Radarr and runs AI selection without
    actually changing anything.
    
    Args:
        movie_id: Radarr movie ID.
        
    Returns:
        JSON with simulation results.
    """
    cfg = get_config()

    if cfg.radarr is None:
        return jsonify({'error': 'Radarr not configured'}), 404

    try:
        movie = radarr_api_get(f"movie/{movie_id}")
    except Exception as e:
        return jsonify({'error': f'Movie not found: {e}'}), 404

    try:
        releases = radarr_api_get(f"release?movieId={movie_id}")
    except Exception as e:
        return jsonify({'error': f'Failed to get releases: {e}'}), 500

    if not releases:
        return jsonify({'error': 'No releases found'}), 404

    profile_name = get_quality_profile_name(movie_id)

    # Transform releases to match DDO format
    ddo_releases: List[Dict[str, Any]] = []
    for i, r in enumerate(releases):
        quality = r.get('quality', {})
        quality_name = quality.get('quality', {}).get('name', 'Unknown')
        
        ddo_releases.append({
            'guid': r.get('guid'),
            'title': r.get('title'),
            'indexer': r.get('indexer'),
            'quality': quality_name,
            'size': r.get('size', 0),
            'seeders': r.get('seeders', 0),
            'customFormatScore': r.get('customFormatScore', 0),
            'languages': [lang.get('name', '') for lang in r.get('languages', [])],
            'customFormats': [cf.get('name', '') for cf in r.get('customFormats', [])],
            'isSelected': i == 0,
            'ageMinutes': r.get('ageMinutes', 0),
            'indexerFlags': r.get('indexerFlags', [])
        })

    movie_title = movie.get('title', 'Unknown')
    choice, reason = ask_ai_for_selection(ddo_releases, movie_title, profile_name, service='radarr')

    if choice is None or choice < 1 or choice > len(ddo_releases):
        return jsonify({
            'status': 'ai_failed',
            'movie': movie_title,
            'profile': profile_name,
            'reason': reason,
            'total_releases': len(releases)
        }), 200

    selected = ddo_releases[choice - 1]

    return jsonify({
        'status': 'simulated',
        'movie': movie_title,
        'profile': profile_name,
        'selected': {
            'index': choice,
            'title': selected['title'],
            'size_gb': round(selected.get('size', 0) / (1024 ** 3), 2),
            'quality': selected['quality'],
            'seeders': selected['seeders']
        },
        'reason': reason,
        'total_releases': len(releases)
    }), 200


@bp.route('/hook/sonarr/override', methods=['POST'])
def webhook_sonarr_override() -> Tuple[Any, int]:
    """
    Handle Sonarr Download Decision Override webhook.
    
    Sonarr sends all candidate releases BEFORE making a download decision.
    We select the best one using AI and return the GUID.
    
    Payload format:
        {eventType, instanceName, series, releases[]}
        
    Response format:
        {approved, selectedReleaseGuid?, reason}
    """
    cfg = get_config()

    if cfg.sonarr is None:
        return jsonify({'approved': True, 'reason': 'Sonarr not configured'}), 200

    payload = request.json

    if not payload:
        return jsonify({'approved': True, 'reason': 'Empty payload'}), 200

    event_type = payload.get('eventType', '')
    if event_type != 'DownloadDecisionOverride':
        return jsonify({
            'approved': True,
            'reason': f'Ignored event type: {event_type}'
        }), 200

    series = payload.get('series', {})
    series_id = series.get('id')
    series_title = series.get('title', 'Unknown')
    releases = payload.get('releases', [])

    logger.info(
        f"Download Decision Override: '{series_title}' ({len(releases)} releases)"
    )

    if not releases:
        logger.warning("No releases in payload")
        return jsonify({'approved': True, 'reason': 'No releases to evaluate'}), 200

    # Check for skip tag
    if series_id:
        tags = get_series_tags(series_id)
        if cfg.skip_tag in tags:
            logger.info(f"Skipping AI for '{series_title}' (tag '{cfg.skip_tag}')")
            return jsonify({
                'approved': True,
                'reason': f'Skipped: tag {cfg.skip_tag} present'
            }), 200

    # Get quality profile name
    profile_name = get_quality_profile_name_sonarr(series_id) if series_id else 'unknown'

    # Ask AI to select
    choice, reason = ask_ai_for_selection(releases, series_title, profile_name, service='sonarr')

    # No prompts for this profile - let Sonarr choose normally
    if choice is None and "AI bypassed" in reason:
        logger.info(f"No prompts for profile '{profile_name}', Sonarr will choose")
        return jsonify({
            'approved': True,
            'reason': reason
        }), 200

    if choice is None or choice < 1 or choice > len(releases):
        logger.warning(f"AI made no valid selection: {reason}")
        send_notification(
            f"AI Warning: {series_title}",
            f"Selection failed: {reason}\nUsing Sonarr default",
            priority="low",
            tags=["warning"]
        )
        return jsonify({
            'approved': True,
            'reason': f'AI failed: {reason}, using default'
        }), 200

    selected = releases[choice - 1]
    selected_guid = selected.get('guid')
    selected_title = selected.get('title', 'Unknown')
    size_gb = round(selected.get('size', 0) / (1024 ** 3), 2)

    # Check if AI chose the same as Sonarr's default
    default_selected = next((r for r in releases if r.get('isSelected')), None)
    is_same_as_default = (
        default_selected and default_selected.get('guid') == selected_guid
    )

    if is_same_as_default:
        logger.info(f"AI confirms Sonarr selection: {selected_title}")
        return jsonify({
            'approved': True,
            'reason': f'AI confirms default: {reason}'
        }), 200

    logger.info(f"AI overrides to: {selected_title} ({size_gb} GB)")

    if cfg.dry_run:
        logger.info(f"[DRY RUN] Would select: {selected_title}")
        return jsonify({
            'approved': True,
            'reason': f'[DRY RUN] Would select: {selected_title}'
        }), 200

    send_notification(
        title=f"AI Override: {series_title}",
        message=(
            f"Profile: {profile_name}\n"
            f"Release: {selected_title}\n"
            f"Size: {size_gb} GB\n"
            f"Reason: {reason}"
        ),
        tags=["tv"]
    )

    return jsonify({
        'approved': True,
        'selectedReleaseGuid': selected_guid,
        'reason': reason
    }), 200


@bp.route('/simulate/sonarr/<int:series_id>', methods=['GET'])
def simulate_sonarr(series_id: int) -> Tuple[Any, int]:
    """
    Simulate AI selection for a series (dry run).
    
    Fetches releases from Sonarr and runs AI selection without
    actually changing anything.
    
    Args:
        series_id: Sonarr series ID.
        
    Returns:
        JSON with simulation results.
    """
    cfg = get_config()

    if cfg.sonarr is None:
        return jsonify({'error': 'Sonarr not configured'}), 404

    try:
        series = sonarr_api_get(f"series/{series_id}")
    except Exception as e:
        return jsonify({'error': f'Series not found: {e}'}), 404

    try:
        releases = sonarr_api_get(f"release?seriesId={series_id}")
    except Exception as e:
        return jsonify({'error': f'Failed to get releases: {e}'}), 500

    if not releases:
        return jsonify({'error': 'No releases found'}), 404

    profile_name = get_quality_profile_name_sonarr(series_id)

    # Transform releases to match DDO format
    ddo_releases: List[Dict[str, Any]] = []
    for i, r in enumerate(releases):
        quality = r.get('quality', {})
        quality_name = quality.get('quality', {}).get('name', 'Unknown')
        
        ddo_releases.append({
            'guid': r.get('guid'),
            'title': r.get('title'),
            'indexer': r.get('indexer'),
            'quality': quality_name,
            'size': r.get('size', 0),
            'seeders': r.get('seeders', 0),
            'customFormatScore': r.get('customFormatScore', 0),
            'languages': [lang.get('name', '') for lang in r.get('languages', [])],
            'customFormats': [cf.get('name', '') for cf in r.get('customFormats', [])],
            'isSelected': i == 0,
            'ageMinutes': r.get('ageMinutes', 0),
            'indexerFlags': r.get('indexerFlags', [])
        })

    series_title = series.get('title', 'Unknown')
    choice, reason = ask_ai_for_selection(ddo_releases, series_title, profile_name, service='sonarr')

    if choice is None or choice < 1 or choice > len(ddo_releases):
        return jsonify({
            'status': 'ai_failed',
            'series': series_title,
            'profile': profile_name,
            'reason': reason,
            'total_releases': len(releases)
        }), 200

    selected = ddo_releases[choice - 1]

    return jsonify({
        'status': 'simulated',
        'series': series_title,
        'profile': profile_name,
        'selected': {
            'index': choice,
            'title': selected['title'],
            'size_gb': round(selected.get('size', 0) / (1024 ** 3), 2),
            'quality': selected['quality'],
            'seeders': selected['seeders']
        },
        'reason': reason,
        'total_releases': len(releases)
    }), 200
