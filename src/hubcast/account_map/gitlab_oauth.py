import logging
from typing import Union

import aiohttp
import gidgetlab.aiohttp

from .abc import AccountMap

log = logging.getLogger(__name__)


class GitlabOauthMap(AccountMap):
    """
    Maps destination GitLab users to external accounts linked via OAuth.

    Example: when GitHub is configured as an OAuth provider, users can link their GitHub and GitLab accounts.
    Incoming GitHub push events are then resolved to the corresponding GitLab user using this map.
    This map is agnostic to which provider is used.

    Attributes:
    ----------
    gitlab_url : str
        URL of the destination GitLab instance
    access_token : str
        GitLab access token; must be created by an administrator with the `read_api` scope
    oauth_provider : str
        name of the provider used to map accounts,
        see https://docs.gitlab.com/integration/omniauth for options
    """

    def __init__(self, gitlab_url: str, access_token: str, oauth_provider: str):
        self.gitlab_url = gitlab_url
        self.access_token = access_token
        self.oauth_provider = oauth_provider

    async def __call__(self, uid: str) -> Union[str, None]:
        """
        Queries list of all GitLab users for a match of uid and oauth_provider.

        Returns username of the matched GitLab user, None if not found.
        """
        # TODO does it make sense to use the GitLabClient/GitLabClientFactory for this?
        async with aiohttp.ClientSession() as session:
            # TODO do we need user= here?
            gl = gidgetlab.aiohttp.GitLabAPI(
                session, access_token=self.access_token, url=self.gitlab_url
            )

            # https://docs.gitlab.com/api/users/#as-an-administrator
            url = f"/users?extern_uid={uid}&provider={self.oauth_provider}"
            users = await gl.getitem(url)

            # technically an iterable, but we don't expect there to be more than one value
            for user in users:
                return user["username"]
            return None
