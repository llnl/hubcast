import time

import aiohttp
import gidgethub.apps as gha
from gidgethub import aiohttp as gh_aiohttp

from hubcast.clients.utils import TokenCache

# location for authenticated app to get a token for one of its installations
# bandit thinks this is a hardcoded password, we ignore security checks on this line
INSTALLATION_TOKEN_URL = "/app/installations/{installation_id}/access_tokens"  # nosec B105


class GitHubAuthenticator:
    """
    An authenticator and token handler for GitHub.

    Attributes:
    ----------
    requester: str
        A GitHub bot user to act as and perform actions as.
    private_key: str
        A pem encoded string of the GitHub App's private key
        which is used to generate JWTs and other access tokens.
    app_id: str
        A string of the numeric GitHub App's ID.
    """

    def __init__(self, requester: str, private_key: str, app_id: str):
        self.requester = requester
        self.private_key = private_key
        self.app_id = app_id
        self._tokens = TokenCache()
        self._id_dict: dict[tuple[str, str], str] = {}

    async def get_installation_id(self, owner: str, repo: str) -> str:
        if (owner, repo) not in self._id_dict:
            async with aiohttp.ClientSession() as session:
                gh = gh_aiohttp.GitHubAPI(session, self.requester)
                result = await gh.getitem(
                    f"/repos/{owner}/{repo}/installation",
                    accept="application/vnd.github+json",
                    jwt=await self.get_jwt(),
                )
                self._id_dict[(owner, repo)] = result["id"]

        return self._id_dict[(owner, repo)]

    async def authenticate_installation(self, owner: str, repo: str) -> str:
        """
        Get an installation access token for the application.
        Renew the JWT if necessary, then use it to get an installation access
        token from github, if necessary.
        """

        installation_id = await self.get_installation_id(owner, repo)

        async def renew_installation_token() -> tuple[int, str]:
            async with aiohttp.ClientSession() as session:
                gh = gh_aiohttp.GitHubAPI(session, self.requester)

                # Use the JWT to get a limited-life OAuth token for a particular
                # installation of the app. Note that we get a JWT only when
                # necessary -- when we need to renew the installation token.
                result = await gh.post(
                    INSTALLATION_TOKEN_URL,
                    {"installation_id": installation_id},
                    data=b"",
                    accept="application/vnd.github.machine-man-preview+json",
                    jwt=await self.get_jwt(),
                )

                expires = self.parse_isotime(result["expires_at"])
                token = result["token"]
                return (expires, token)

        return await self._tokens.get(installation_id, renew_installation_token)

    def parse_isotime(self, timestr: str) -> int:
        """Convert UTC ISO 8601 time stamp to seconds in epoch"""
        if timestr[-1] != "Z":
            raise ValueError(f"Time String '{timestr}' not in UTC")
        return int(time.mktime(time.strptime(timestr[:-1], "%Y-%m-%dT%H:%M:%S")))

    async def get_jwt(self) -> str:
        """Get a JWT from cache, creating a new one if necessary."""

        async def renew_jwt() -> tuple[float, str]:
            # GitHub requires that you create a JWT signed with the application's
            # private key. You need the app id and the private key, and you can
            # use this gidgethub method to create the JWT.
            now = int(time.time())
            jwt = gha.get_jwt(app_id=self.app_id, private_key=self.private_key)

            # JWT expires after 10 minutes, but cache for 9 to handle clock skew
            return (now + 9 * 60), jwt

        return await self._tokens.get("JWT", renew_jwt)
