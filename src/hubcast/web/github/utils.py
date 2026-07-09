import logging
from typing import Any

import yaml
from cachetools import TTLCache

from hubcast.clients.github import GitHubClient
from hubcast.exceptions import RepoConfigError
from hubcast.repos.config import RepoConfig
from hubcast.web.github.messages import (
    CONFIG_INVALID_SUMMARY,
    CONFIG_INVALID_TITLE,
    CONFIG_NOT_FOUND_SUMMARY,
    CONFIG_NOT_FOUND_TITLE,
)

log = logging.getLogger(__name__)

# Shared cache for repository configs with 30-minute TTL
config_cache: TTLCache[str, RepoConfig | None] = TTLCache(maxsize=1000, ttl=1800)


def changed_files_from_push(payload: dict[str, Any]) -> set[str]:
    """Collect all file paths touched by the commits in a push payload."""
    return {
        f
        for c in payload["commits"]
        for key in ("added", "modified", "removed")
        for f in c.get(key, ())
    }


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
            raise RepoConfigError(
                "Repo config file not found",
                title=CONFIG_NOT_FOUND_TITLE,
                summary=CONFIG_NOT_FOUND_SUMMARY,
            )
        return config, False

    # cache miss or refresh requested, fetch from GH
    fetched_config = await gh.get_repo_config()

    if fetched_config is None:  # 404
        config_cache[fullname] = None
        log.info("Cached absence of repo config")
        # raise so route handlers can't continue
        raise RepoConfigError(
            "Repo config file not found",
            title=CONFIG_NOT_FOUND_TITLE,
            summary=CONFIG_NOT_FOUND_SUMMARY,
        )

    # parse and validate YAML
    try:
        config_yaml = yaml.safe_load(fetched_config)
    except yaml.YAMLError as e:
        raise RepoConfigError(
            "Invalid YAML in repo config",
            title=CONFIG_INVALID_TITLE,
            summary=CONFIG_INVALID_SUMMARY,
            error=str(e),
        )

    try:
        config = RepoConfig.model_validate(config_yaml)
    except ValueError as e:
        raise RepoConfigError(
            "Invalid repo config",
            title=CONFIG_INVALID_TITLE,
            summary=CONFIG_INVALID_SUMMARY,
            error=str(e),
        )

    config_cache[fullname] = config
    log.info("Repo config fetched from source forge")
    return config, True
