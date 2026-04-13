import yaml

from hubcast.clients.github import GitHubClient
from hubcast.exceptions import HubcastError
from hubcast.repos.config import RepoConfig

config_cache: dict[str, RepoConfig] = {}


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
    fetched = False
    if fullname in config_cache and not refresh:
        config = config_cache[fullname]
    else:
        config_str = await gh.get_repo_config()

        try:
            config_yaml = yaml.safe_load(config_str)
        except yaml.YAMLError as e:
            raise HubcastError(
                f"Invalid YAML in repo config for {fullname}: {e}",
                log_level="INFO",
                repo=fullname,
            )

        try:
            config = RepoConfig.from_yaml_data(config_yaml["Repo"])
        except KeyError as e:
            raise HubcastError(
                f"Repo config for {fullname} is missing required key: {e}",
                log_level="INFO",
                repo=fullname,
            ) from None
        except ValueError as e:
            raise HubcastError(
                f"Invalid repo config for {fullname}: {e}",
                log_level="INFO",
                repo=fullname,
            ) from None

        config_cache[fullname] = config
        fetched = True

    return config, fetched
