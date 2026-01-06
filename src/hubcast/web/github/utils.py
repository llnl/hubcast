import logging
from typing import Dict

from hubcast.clients.github import GitHubClient
from hubcast.clients.github.client import InvalidConfigYAMLError
from hubcast.repos.config import RepoConfig

config_cache = dict()
log = logging.getLogger(__name__)


def create_config(fullname: str, data: Dict) -> RepoConfig:
    return RepoConfig(
        fullname=fullname,
        dest_org=data["Repo"]["owner"],
        dest_name=data["Repo"]["name"],
        draft_sync=data["Repo"].get("draft_sync", True),
        draft_sync_msg=data["Repo"].get("draft_sync_msg", True),
    )


async def get_repo_config(gh: GitHubClient, fullname: str, refresh: bool = False):
    if fullname in config_cache and not refresh:
        config = config_cache[fullname]
    else:
        try:
            data = await gh.get_repo_config()
        except InvalidConfigYAMLError:
            log.exception("Repo config parse failed")

        config = create_config(fullname, data)
        config_cache[fullname] = config

    return config
