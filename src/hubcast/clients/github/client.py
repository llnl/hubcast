import logging
from typing import Any

import aiohttp
from gidgethub import HTTPException
from gidgethub import aiohttp as gh_aiohttp

from hubcast.exceptions import HubcastError
from hubcast.webhook import GitHubRoutingToken, GitLabRoutingToken

from .auth import GitHubAuthenticator

log = logging.getLogger(__name__)

GH_REACTIONS = {
    "+1": "THUMBS_UP",
    "-1": "THUMBS_DOWN",
    "laugh": "LAUGH",
    "confused": "CONFUSED",
    "heart": "HEART",
    "hooray": "HOORAY",
    "rocket": "ROCKET",
    "eyes": "EYES",
}


class GitHubClientFactory:
    def __init__(self, app_id: str, private_key: str, requester: str, bot_caller: str):
        self.requester = requester
        self.auth = GitHubAuthenticator(requester, private_key, app_id)
        self.bot_caller = bot_caller

    def create_client(self, repo_owner: str, repo_name: str) -> "GitHubClient":
        return GitHubClient(
            self.auth, self.requester, repo_owner, repo_name, self.bot_caller
        )

    def create_client_from_token(
        self, routing_token: GitHubRoutingToken | GitLabRoutingToken
    ) -> "GitHubClient":
        """creates a GitHubClient for the repo identified by a routing token"""
        if routing_token.src_forge != "github":
            # needed to pass type checking b/c RoutingToken is a discriminated union with different fields
            raise HubcastError(
                "routing token is GitLabRoutingToken; this Hubcast instance mirrors from GitHub"
            )
        return self.create_client(routing_token.gh_owner, routing_token.gh_repo)


class GitHubClient:
    # check-status states specific to this forge
    FAILURE_STATUS = "failure"
    SUCCESS_STATUS = "success"

    def __init__(
        self,
        auth: GitHubAuthenticator,
        requester: str,
        repo_owner: str,
        repo_name: str,
        bot_caller: str,
    ):
        self.auth = auth
        self.requester = requester
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.bot_caller = bot_caller
        # path to the hubcast config file within a repository, relative to its root
        self.repo_config_path = ".github/hubcast.yml"

    async def set_check_status(
        self,
        ref: str,
        check_name: str,
        status: str,
        title: str,
        summary: str = "",  # github does not accept None values for this field
        details_url: str | None = None,
    ) -> None:
        """
        Set the status of a GitHub check.

        Attributes:
        ----------
        ref: str
            The git SHA reference for the check.
        check_name: str
            The name of the check.
        status: str
            The status of the check.
        title: str
            This message will be shown inline with the list of checks.
        summary: str, optional
            This message will be shown on the check's detail page.
        details_url: str, optional
            This URL will be included on the check's detail page to point users to external information.

        """
        # construct upload payload
        payload: dict[str, Any] = {
            "name": check_name,
            "head_sha": ref,
        }

        payload["output"] = {"title": title, "summary": summary}
        if details_url is not None:
            payload["details_url"] = details_url

        # for success and failure status write out a conclusion
        if status in ("skipped", "success", "failure", "cancelled", "neutral"):
            payload["status"] = "completed"
            payload["conclusion"] = status
        else:
            payload["status"] = status

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            # get a list of the checks on a commit
            url = f"/repos/{self.repo_owner}/{self.repo_name}/commits/{ref}/check-runs"
            data = await gh.getitem(url)

            # search for existing check with GH_CHECK_NAME
            existing_check = None
            for check in data["check_runs"]:
                if check["name"] == check_name:
                    existing_check = check
                    break

            # create a new check if no previous check is found, or if the previous
            # existing check was marked as completed. (This allows to check re-runs.)
            if existing_check is None or existing_check["status"] == "completed":
                url = f"/repos/{self.repo_owner}/{self.repo_name}/check-runs"
                await gh.post(url, data=payload)
            else:
                url = f"/repos/{self.repo_owner}/{self.repo_name}/check-runs/{existing_check['id']}"
                await gh.patch(url, data=payload)

    async def get_repo_config(self, ref: str | None = None) -> str | None:
        """Get the contents of the repo's hubcast config file.

        Args:
            ref: Where to read the file from. Defaults to the repo's default branch.
        """
        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            # get the contents of the repository hubcast.yml file
            url = f"/repos/{self.repo_owner}/{self.repo_name}/contents/{self.repo_config_path}"
            if ref is not None:
                url = f"{url}?ref={ref}"
            # get raw contents rather than base64 encoded text
            try:
                return await gh.getitem(url, accept="application/vnd.github.raw")
            except HTTPException as exc:
                if exc.status_code == 404:
                    # the repo config was not found: the caller will handle this case
                    return
                # all others are unhandled
                raise

    async def get_pr_files(self, pr_number: int) -> list[str]:
        """Return the files changed in a PR."""
        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{pr_number}/files"
            files = await gh.getitem(url)
            return [f["filename"] for f in files]

    async def get_pr(self, id: int) -> dict[str, Any]:
        """Return individual PR data."""
        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{id}"
            return await gh.getitem(url)

    async def get_prs(self, branch: str | None = None) -> list[int] | None:
        """Returns a list of all open PR numbers; can be filtered by internal branches."""

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            # https://docs.github.com/en/rest/pulls/pulls?apiVersion=2022-11-28#list-pull-requests
            # default is open pull requests
            url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls"
            if branch:
                # head: filter pulls by head user or head organization and branch name
                url = f"{url}?head={self.repo_owner}:{branch}"
                prs_res = await gh.getitem(url)
                return [pr["number"] for pr in prs_res]
        return None

    async def post_comment(self, issue_number: int, body: str) -> None:
        payload = {"body": body}

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/issues/{issue_number}/comments"
            await gh.post(url, data=payload)

    async def react_to_comment(self, node_id: str, reaction: str) -> None:
        """
        Add an emoji reaction to a GitHub issue comment or PR review.
        See `GH_REACTIONS.keys()` for a list of emoji options.

        Done via GraphQL due to inability to react to reviews via REST API:
        https://github.com/orgs/community/discussions/29018
        """
        # https://docs.github.com/en/graphql/reference/mutations#addreaction
        mutation = """
        mutation($subjectId: ID!, $content: ReactionContent!) {
        addReaction(input: { subjectId: $subjectId, content: $content }) {
            reaction { content }
            subject { id }
        }
        }
        """

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            # graphql expects a string to represent the reaction
            await gh.graphql(
                mutation, subjectId=node_id, content=GH_REACTIONS[reaction]
            )

    async def get_branch(self, name: str) -> dict[str, Any]:
        """Return individual branch data."""

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/branches/{name}"
            return await gh.getitem(url)
