import logging
from typing import Any

import yaml
import yaml.reader
from cachetools import TTLCache
from pydantic import ValidationError

from hubcast.clients.github import GitHubClient
from hubcast.exceptions import HubcastError, RepoConfigError
from hubcast.repos.config import RepoConfig
from hubcast.web.github.messages import (
    CONFIG_INVALID_SUMMARY,
    CONFIG_INVALID_TITLE,
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


def _format_yaml_error(exc: yaml.YAMLError) -> str:
    """Render YAML parse errors with bullet points rather than pyyaml's default mess."""
    if isinstance(exc, yaml.reader.ReaderError):
        # encoding/control-character issues
        return f"- {exc.reason} (position {exc.position})"

    # the only other error we can hit via safe_load is MarkedYAMLError
    problem = f"{exc.context}; {exc.problem}" if exc.context else exc.problem
    mark = exc.problem_mark
    line = (
        f"- {problem} (line {mark.line + 1}, column {mark.column + 1})"
        if mark
        else f"- {problem}"
    )

    snippet = mark.get_snippet() if mark else None
    return f"{line}\n\n```\n{snippet}\n```" if snippet else line


def _format_validation_error(exc: ValidationError) -> str:
    """Render pydantic validation errors as a per-field bullet list."""
    lines = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in err["loc"])
        # pydantic prefixes messages from raised errors
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"- `{loc}`: {msg}" if loc else f"- {msg}")
    return "\n".join(lines)


def parse_repo_config(raw_config: str) -> RepoConfig:
    """Parse YAML as a RepoConfig.

    Raises RepoConfigError for invalid YAML or schema validation issues.
    """
    try:
        config_yaml = yaml.safe_load(raw_config)
    except yaml.YAMLError as e:
        raise RepoConfigError(
            "Invalid YAML in repo config",
            title=CONFIG_INVALID_TITLE,
            summary=f"{CONFIG_INVALID_SUMMARY}\n\n---\n\n{_format_yaml_error(e)}",
            error=str(e),
        )

    try:
        return RepoConfig.model_validate(config_yaml)
    except ValidationError as e:
        raise RepoConfigError(
            "Invalid repo config",
            title=CONFIG_INVALID_TITLE,
            summary=f"{CONFIG_INVALID_SUMMARY}\n\n---\n\n{_format_validation_error(e)}",
            error=str(e),
        )


async def get_repo_config(
    gh: GitHubClient, fullname: str, refresh: bool = False
) -> RepoConfig:
    """Get repository configuration from cache or fetch from GitHub.

    Args:
        gh: GitHub client instance
        fullname: Full repository name (e.g., "owner/repo")
        refresh: Whether to force refresh from GitHub

    Returns:
        RepoConfig instance

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
            # we don't want to raise this as a RepoConfigError because telling users
            # about the absence of the config will create noise and confusion
            raise HubcastError("Repo config file not found", log_level="INFO")
        return config

    # cache miss or refresh requested, fetch from GH
    fetched_config = await gh.get_repo_config()

    if fetched_config is None:  # 404
        config_cache[fullname] = None
        log.info("Cached absence of repo config")
        # raise so route handlers can't continue
        raise HubcastError("Repo config file not found", log_level="INFO")

    # parse and validate YAML
    config = parse_repo_config(fetched_config)

    config_cache[fullname] = config
    log.info("Repo config fetched from source forge")
    return config
