import logging
from typing import Any

import yaml

from hubcast.clients.github import GitHubClient
from hubcast.repos.config import RepoConfig

config_cache: dict[str, RepoConfig] = {}
log = logging.getLogger(__name__)


def create_config(fullname: str, data: dict[str, Any]) -> RepoConfig:
    return RepoConfig(
        fullname=fullname,
        dest_org=data["Repo"]["owner"],
        dest_name=data["Repo"]["name"],
        sync_drafts=data["Repo"].get("sync_drafts", True),
        sync_drafts_msg=data["Repo"].get("sync_drafts_msg", True),
    )


async def get_repo_config(
    gh: GitHubClient, fullname: str, refresh: bool = False
) -> tuple[RepoConfig, bool]:
    fetched = False
    if fullname in config_cache and not refresh:
        config = config_cache[fullname]
    else:
        config_str = await gh.get_repo_config()

        try:
            config_yaml = yaml.safe_load(config_str)
        except yaml.YAMLError:
            log.info(
                "Repo config is invalid YAML",
                extra={"repo_owner": gh.repo_owner, "repo_name": gh.repo_name},
            )

        try:
            config = create_config(fullname, config_yaml)
        except KeyError as exc:
            log.info(
                f"Repo config is missing required fields: {exc}",
                extra={"repo_owner": gh.repo_owner, "repo_name": gh.repo_name},
            )

        config_cache[fullname] = config
        fetched = True

    return config, fetched
