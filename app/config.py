"""
Configuration management for arr-llm-release-picker.

Handles environment variables, dataclasses, and prompt loading.
Prompts are loaded with fallback:
1. User-provided: /config/prompts (volume mount)
2. Bundled defaults: /app/prompts (shipped with image)"""

import os
import logging
from dataclasses import dataclass, field
from typing import Optional, Dict, List

# -----------------------------------------------------------------------------
# Logging setup
# -----------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Default prompts directory (bundled in image, can be overridden via volume mount)
DEFAULT_PROMPTS_DIR = '/config/prompts'


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


class PromptsError(Exception):
    """Raised when prompts cannot be loaded."""
    pass


# -----------------------------------------------------------------------------
# Data classes
# -----------------------------------------------------------------------------

@dataclass
class RadarrConfig:
    """Radarr connection configuration."""
    url: str
    api_key: str


@dataclass
class SonarrConfig:
    """Sonarr connection configuration."""
    url: str
    api_key: str


@dataclass
class Config:
    """Application configuration loaded from environment variables."""
    llm_api_url: str
    llm_model: str
    llm_api_key: Optional[str]
    llm_timeout: int
    prompts_dir: str
    radarr: Optional[RadarrConfig] = None
    sonarr: Optional[SonarrConfig] = None
    # Nested dict: service -> profile -> system_prompt
    # e.g. {'radarr': {'hd-1080p': 'prompt...'}, 'sonarr': {'hd-1080p': 'prompt...'}}
    service_prompts: Dict[str, Dict[str, str]] = field(default_factory=dict)
    dry_run: bool = False
    ntfy_url: Optional[str] = None
    ntfy_topic: str = "arr-llm-release-picker"
    skip_tag: str = "no-ai"


# -----------------------------------------------------------------------------
# Private helpers
# -----------------------------------------------------------------------------

def _load_system_prompt(dir_path: str) -> Optional[str]:
    """
    Load system.txt from a directory.
    
    Args:
        dir_path: Path to directory containing system.txt.
        
    Returns:
        System prompt string if file exists and is non-empty, None otherwise.
    """
    system_path = os.path.join(dir_path, 'system.txt')

    if not os.path.exists(system_path):
        return None

    with open(system_path, 'r', encoding='utf-8') as f:
        system = f.read().strip()

    return system if system else None


# -----------------------------------------------------------------------------
# Configuration loading
# -----------------------------------------------------------------------------

def load_config() -> Config:
    """
    Load and validate configuration from environment variables.
    
    Required environment variables:
        LLM_API_URL: OpenAI-compatible API endpoint
        LLM_MODEL: Model name (e.g. gpt-4o)
        At least one of: RADARR_URL+RADARR_API_KEY or SONARR_URL+SONARR_API_KEY
    
    Optional environment variables:
        RADARR_URL, RADARR_API_KEY: Radarr connection
        SONARR_URL, SONARR_API_KEY: Sonarr connection
        LLM_API_KEY: API key for LLM (optional for local LLMs)
        NTFY_URL: Notification URL
        NTFY_TOPIC: Notification topic (default: arr-llm-release-picker)
        SKIP_TAG: Tag to skip AI selection (default: no-ai)
        DRY_RUN: Dry run mode (default: false)
        PROMPTS_DIR: Directory for prompts (default: /config/prompts)
    
    Returns:
        Validated Config object.
        
    Raises:
        ConfigurationError: If required variables are missing.
    """
    errors: List[str] = []

    # Required LLM config
    llm_api_url = os.environ.get('LLM_API_URL', '').strip()
    llm_model = os.environ.get('LLM_MODEL', '').strip()
    
    if not llm_api_url:
        errors.append('LLM_API_URL')
    if not llm_model:
        errors.append('LLM_MODEL')

    # Optional Radarr config (both URL and API key needed if configured)
    radarr_url = os.environ.get('RADARR_URL', '').strip()
    radarr_api_key = os.environ.get('RADARR_API_KEY', '').strip()
    radarr: Optional[RadarrConfig] = None
    
    if radarr_url and radarr_api_key:
        radarr = RadarrConfig(url=radarr_url.rstrip('/'), api_key=radarr_api_key)
    elif radarr_url or radarr_api_key:
        errors.append('RADARR_URL and RADARR_API_KEY (both required if using Radarr)')

    # Optional Sonarr config (both URL and API key needed if configured)
    sonarr_url = os.environ.get('SONARR_URL', '').strip()
    sonarr_api_key = os.environ.get('SONARR_API_KEY', '').strip()
    sonarr: Optional[SonarrConfig] = None
    
    if sonarr_url and sonarr_api_key:
        sonarr = SonarrConfig(url=sonarr_url.rstrip('/'), api_key=sonarr_api_key)
    elif sonarr_url or sonarr_api_key:
        errors.append('SONARR_URL and SONARR_API_KEY (both required if using Sonarr)')

    # At least one arr must be configured
    if not radarr and not sonarr and not errors:
        errors.append('At least one of RADARR or SONARR must be configured')

    if errors:
        raise ConfigurationError(
            f"Configuration errors: {', '.join(errors)}"
        )

    # Optional env vars
    llm_api_key = os.environ.get('LLM_API_KEY', '').strip() or None
    ntfy_url = os.environ.get('NTFY_URL', '').strip() or None
    ntfy_topic = os.environ.get('NTFY_TOPIC', '').strip() or 'arr-llm-release-picker'
    skip_tag = os.environ.get('SKIP_TAG', '').strip() or 'no-ai'
    
    dry_run_env = os.environ.get('DRY_RUN', '').lower().strip()
    dry_run = dry_run_env in ('true', '1', 'yes')
    
    # LLM timeout (default 90 seconds)
    llm_timeout_str = os.environ.get('LLM_TIMEOUT', '90').strip()
    try:
        llm_timeout = int(llm_timeout_str)
    except ValueError:
        llm_timeout = 90

    # Prompts directory - structure: prompts/SERVICE/PROFILE/system.txt
    prompts_dir = os.environ.get('PROMPTS_DIR', '').strip() or DEFAULT_PROMPTS_DIR
    
    # Load system prompts for each service and profile
    service_prompts: Dict[str, Dict[str, str]] = {'radarr': {}, 'sonarr': {}}
    
    if os.path.isdir(prompts_dir):
        for service in ['radarr', 'sonarr']:
            service_dir = os.path.join(prompts_dir, service)
            if os.path.isdir(service_dir):
                for profile in os.listdir(service_dir):
                    profile_path = os.path.join(service_dir, profile)
                    if os.path.isdir(profile_path):
                        system_prompt = _load_system_prompt(profile_path)
                        if system_prompt:
                            service_prompts[service][profile.lower()] = system_prompt
                            logger.info(f"Loaded prompt for {service}/{profile}")
        
        total_prompts = sum(len(p) for p in service_prompts.values())
        if not total_prompts:
            logger.info(
                f"No prompts found in {prompts_dir}. "
                "AI selection disabled for all profiles."
            )
    else:
        logger.info(
            f"Prompts directory not found: {prompts_dir}. "
            "AI selection disabled for all profiles."
        )

    return Config(
        radarr=radarr,
        sonarr=sonarr,
        llm_api_url=llm_api_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_timeout=llm_timeout,
        prompts_dir=prompts_dir,
        service_prompts=service_prompts,
        dry_run=dry_run,
        ntfy_url=ntfy_url,
        ntfy_topic=ntfy_topic,
        skip_tag=skip_tag.lower()
    )


def log_config_summary(cfg: Config) -> None:
    """
    Log configuration summary without exposing secrets.
    
    Args:
        cfg: Configuration object.
    """
    logger.info("=== Configuration ===")
    if cfg.radarr:
        logger.info(f"  Radarr URL: {cfg.radarr.url}")
    else:
        logger.info("  Radarr: not configured")
    if cfg.sonarr:
        logger.info(f"  Sonarr URL: {cfg.sonarr.url}")
    else:
        logger.info("  Sonarr: not configured")
    logger.info(f"  LLM API URL: {cfg.llm_api_url}")
    logger.info(f"  LLM Model: {cfg.llm_model}")
    logger.info(f"  LLM API Key: {'set' if cfg.llm_api_key else 'not set'}")
    logger.info(f"  LLM Timeout: {cfg.llm_timeout}s")
    logger.info(f"  Prompts directory: {cfg.prompts_dir}")
    for service, profiles in cfg.service_prompts.items():
        if profiles:
            logger.info(f"  {service.capitalize()} profiles: {list(profiles.keys())}")
        else:
            logger.info(f"  {service.capitalize()} profiles: none")
    logger.info(f"  Skip tag: {cfg.skip_tag}")
    logger.info(f"  Dry run: {cfg.dry_run}")
    logger.info(f"  Notifications: {'enabled' if cfg.ntfy_url else 'disabled'}")
    logger.info("=====================")


# -----------------------------------------------------------------------------
# Global state
# -----------------------------------------------------------------------------

_config: Optional[Config] = None


def get_config() -> Config:
    """Get the current configuration singleton."""
    global _config
    if _config is None:
        _config = load_config()
        log_config_summary(_config)
    return _config


def reload_prompts() -> None:
    """
    Reload prompts from disk without reloading env vars.
    """
    global _config
    if _config is None:
        _config = load_config()
        return

    prompts_dir = _config.prompts_dir
    service_prompts: Dict[str, Dict[str, str]] = {'radarr': {}, 'sonarr': {}}
    
    if os.path.isdir(prompts_dir):
        for service in ['radarr', 'sonarr']:
            service_dir = os.path.join(prompts_dir, service)
            if os.path.isdir(service_dir):
                for profile in os.listdir(service_dir):
                    profile_path = os.path.join(service_dir, profile)
                    if os.path.isdir(profile_path):
                        system_prompt = _load_system_prompt(profile_path)
                        if system_prompt:
                            service_prompts[service][profile.lower()] = system_prompt
                            logger.info(f"Reloaded prompt for {service}/{profile}")

    _config.service_prompts = service_prompts
    for service, profiles in service_prompts.items():
        if profiles:
            logger.info(f"Prompts reloaded for {service}: {list(profiles.keys())}")


# -----------------------------------------------------------------------------
# App initialization
# -----------------------------------------------------------------------------

def init_app() -> None:
    """Initialize the application and validate configuration."""
    try:
        cfg = get_config()
        total_prompts = sum(len(p) for p in cfg.service_prompts.values())
        if total_prompts:
            for service, profiles in cfg.service_prompts.items():
                if profiles:
                    logger.info(f"AI enabled for {service}: {list(profiles.keys())}")
        else:
            logger.info("Application initialized - no prompts configured (passthrough mode)")
    except ConfigurationError as e:
        logger.critical(f"Startup failed: {e}")
        raise SystemExit(1)
