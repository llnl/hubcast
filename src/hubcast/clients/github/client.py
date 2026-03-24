from urllib.parse import urlparse

import aiohttp
from gidgethub import aiohttp as gh_aiohttp

from .auth import GitHubAuthenticator

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
    def __init__(self, app_id, privkey, requester, bot_caller):
        self.requester = requester
        self.auth = GitHubAuthenticator(requester, privkey, app_id)
        self.bot_caller = bot_caller

    def create_client(self, repo_owner, repo_name):
        return GitHubClient(
            self.auth, self.requester, repo_owner, repo_name, self.bot_caller
        )


class GitHubClient:
    def __init__(self, auth, requester, repo_owner, repo_name, bot_caller):
        self.auth = auth
        self.requester = requester
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.bot_caller = bot_caller

    async def set_check_status(
        self,
        ref: str,
        check_name: str,
        status: str,
        details_url: str = None,
        message: str = None,
    ):
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
        details_url: str, optional
            A URL with more details about the check. Required if message is not provided.
        message: str, optional
            Used to convey a small message in the check output
            (for example, to indicate a skipped sync, rather than forwarding pipeline status).

        """
        # construct upload payload
        payload = {
            "name": check_name,
            "head_sha": ref,
        }

        if message:
            payload["output"] = {
                "title": message,
                "summary": "",  # summary can't be None
            }
        else:
            gitlab_netloc = urlparse(details_url).netloc
            payload["details_url"] = details_url
            payload["output"] = {
                "title": "External Pipeline Run",
                "summary": f"[View this pipeline on {gitlab_netloc}]({details_url})",
            }

        # for success and failure status write out a conclusion
        if status in ("skipped", "success", "failure", "cancelled"):
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

    async def get_repo_config(self):
        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            # get the contents of the repository hubcast.yml file
            url = f"/repos/{self.repo_owner}/{self.repo_name}/contents/.github/hubcast.yml"
            # get raw contents rather than base64 encoded text
            return await gh.getitem(url, accept="application/vnd.github.raw")

    async def get_pr(self, id):
        """Return individual PR data."""
        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/pulls/{id}"
            return await gh.getitem(url)

    async def get_prs(self, branch=None):
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

    async def post_comment(self, issue_number: int, body: str):
        payload = {"body": body}

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/issues/{issue_number}/comments"
            await gh.post(url, data=payload)

    async def react_to_comment(self, node_id: str, reaction: str):
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

    async def get_branch(self, name: str):
        """Return individual branch data."""

        gh_token = await self.auth.authenticate_installation(
            self.repo_owner, self.repo_name
        )

        async with aiohttp.ClientSession() as session:
            gh = gh_aiohttp.GitHubAPI(session, self.requester, oauth_token=gh_token)

            url = f"/repos/{self.repo_owner}/{self.repo_name}/branches/{name}"
            return await gh.getitem(url)
