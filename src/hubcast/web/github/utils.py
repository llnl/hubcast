import logging

import yaml
from cachetools import TTLCache

from hubcast.clients.github import GitHubClient
from hubcast.exceptions import HubcastError
from hubcast.repos.config import RepoConfig

log = logging.getLogger(__name__)

# Shared cache for repository configs with 30-minute TTL
config_cache: TTLCache[str, RepoConfig] = TTLCache(maxsize=1000, ttl=1800)


async def get_repo_config(
    gh: GitHubClient, fullname: str, refresh: bool = False
) -> tuple[RepoConfig, bool]:
    """Get repository configuration from cache or fetch from GitHub.

    Args:
        gh: GitHub client instance
        fullname: Full repository name (e.g., "owner/repo")
        refresh: Whether to force refresh from GitHub

    Returns:
        Tuple of (RepoConfig instance, whether it was freshly fetched)

    Raises:
        HubcastError: If config file contains invalid YAML, is missing required keys,
            or has validation errors
    """
    # check cache first unless refresh is requested
    if fullname in config_cache and not refresh:
        config = config_cache[fullname]
        log.info("Repo config retrieved from cache")
        if config is None:
            # raise so route handlers can't continue
            raise HubcastError(
                "Config file not found",
                log_level="INFO",
            )
        return config, False

    # cache miss or refresh requested, fetch from GH
    fetched_config = await gh.get_repo_config()

    if fetched_config is None:  # 404
        config_cache[fullname] = None
        log.info("Cached absence of repo config")
        # raise so route handlers can't continue
        raise HubcastError(
            "Repo config file not found",
            log_level="INFO",
        )

    # parse and validate YAML
    try:
        config_yaml = yaml.safe_load(fetched_config)
    except yaml.YAMLError as e:
        raise HubcastError(
            f"Invalid YAML in repo config for {fullname}: {e}",
            log_level="INFO",
        )

    try:
        config = RepoConfig.model_validate(config_yaml)
    except ValueError as e:
        raise HubcastError(
            f"Invalid repo config for {fullname}: {e}",
            log_level="INFO",
        )

    config_cache[fullname] = config
    log.info("Repo config fetched from source forge")
    return config, True
