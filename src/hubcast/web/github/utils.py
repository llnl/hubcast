import logging

import yaml

from hubcast.clients.github import GitHubClient
from hubcast.repos.config import RepoConfig

config_cache: dict[str, RepoConfig] = {}
log = logging.getLogger(__name__)


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
        yaml.YAMLError: If config file contains invalid YAML
        KeyError: If config is missing required top-level "Repo" key
        ValueError: If config is missing required fields
    """
    fetched = False
    if fullname in config_cache and not refresh:
        config = config_cache[fullname]
    else:
        config_str = await gh.get_repo_config()

        try:
            config_yaml = yaml.safe_load(config_str)
        except yaml.YAMLError:
            log.exception(
                f"Repo config is invalid YAML",
                extra={"repo_owner": gh.repo_owner, "repo_name": gh.repo_name},
            )
            raise

        try:
            config = RepoConfig.from_yaml_data(config_yaml["Repo"])
        except KeyError as exc:
            log.exception(
                f"Repo config is missing required top-level key,
                extra={"repo_owner": gh.repo_owner, "repo_name": gh.repo_name},
            )
            raise
        except ValueError:
            log.exception(
                f"Repo config is invalid",
                extra={"repo_owner": gh.repo_owner, "repo_name": gh.repo_name},
            )
            raise

        config_cache[fullname] = config
        fetched = True

    return config, fetched
