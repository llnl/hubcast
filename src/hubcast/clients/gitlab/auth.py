from datetime import datetime, timedelta, timezone
from typing import Iterable

import aiohttp
import gidgetlab.aiohttp

from hubcast.clients.utils import TokenCache

TOKEN_NAME = "hubcast-impersonation"  # nosec B105
# api scope needed for reading pipelines, setting webhooks
# read_repository and write_repository needed for repo access
GL_SCOPES = ("api", "read_repository", "write_repository")


class GitLabAuthenticator:
    """
    An authenticator and token handler for GitLab.

    Attributes:
    ----------
    instance_url: str
        URL of the GitLab instance.
    requester: str
        A string identifying who is responsible for the requests.
    admin_token: str
        A personal access token with `api` scope and created by an administrator.
    """

    def __init__(self, instance_url: str, requester: str, admin_token: str):
        self.instance_url = instance_url
        self.requester = requester
        self.admin_token = admin_token
        self._tokens = TokenCache()

    async def authenticate_user(
        self,
        username: str,
        scopes: Iterable[str] = GL_SCOPES,
        expire_days: int = 1,
    ) -> str:
        """
        Returns an impersonation token for a user with specified scopes; maintains a cache of previously created tokens.
        GitLab does not allow granular expiration times for tokens, so we set expiration in days (defaulting to 1)

        Parameters:
        ----------
        username: str
            username of the user to impersonate
        scopes: list
            scopes assigned to any impersonation token created. see gitlab docs for options:
            https://docs.gitlab.com/user/profile/personal_access_tokens/#personal-access-token-scopes.
        expire_days: int
            the number of days after which the token will expire on the gitlab server
        """

        async def renew_impersonation_token() -> tuple[int, str]:
            # the tokens API requires user IDs, but hubcast's account mapping returns usernames
            user_id = await self._get_user_id(username)

            async with aiohttp.ClientSession() as session:
                gl = gidgetlab.aiohttp.GitLabAPI(
                    session,
                    self.requester,
                    access_token=self.admin_token,
                    url=self.instance_url,
                )

                # temporary fix to support gitlab deployments in sub-paths
                gl.api_url = f"{self.instance_url}/api/v4/"

                url = f"/users/{user_id}/impersonation_tokens"
                expires_day, expires_timestamp = self._date_after_days(expire_days)

                token = await gl.post(
                    url,
                    data={
                        "user_id": user_id,
                        "name": TOKEN_NAME,
                        "description": "Created by Hubcast for CI sync and status reporting.",
                        "expires_at": expires_day,
                        "scopes": scopes,
                    },
                )

                return (expires_timestamp, token["token"])

        # the caching key is username so that _get_user_id can be avoided on cache hits
        return await self._tokens.get(
            f"impersonation:{username}", renew_impersonation_token
        )

    async def _get_user_id(self, username: str) -> int:
        """Retrieve the user ID for a given username from the GitLab instance."""
        async with aiohttp.ClientSession() as session:
            gl = gidgetlab.aiohttp.GitLabAPI(
                session,
                self.requester,
                access_token=self.admin_token,
                url=self.instance_url,
            )

            # temporary fix to support gitlab deployments in sub-paths
            gl.api_url = f"{self.instance_url}/api/v4/"

            res = await gl.getitem(f"/users?username={username}")
            if not res:
                raise ValueError(f"user '{username}' not found on GitLab instance.")
            return res[0]["id"]

    @staticmethod
    def _date_after_days(days: int) -> tuple[str, int]:
        """Returns UTC date string in YYYY-MM-DD format and midnight UTC timestamp."""
        dt = (datetime.now(timezone.utc) + timedelta(days=days)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return dt.strftime("%Y-%m-%d"), int(dt.timestamp())


class GitLabSingleUserAuthenticator:
    """
    An authenticator for developers and users without admin access to a GitLab instance.

    The token should have the scopes defined in GL_SCOPES for the repos Hubcast will access.
    """

    def __init__(self, access_token: str):
        self.access_token = access_token

    async def authenticate_user(self, username: str, *args, **kwargs) -> str:
        """Returns the pre-configured token. Keeps the same signature as GitLabAuthenticator for compatibility."""
        return self.access_token
