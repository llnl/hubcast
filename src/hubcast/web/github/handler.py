import logging

from aiohttp import web
from aiojobs.aiohttp import spawn
from gidgethub import sansio

from .routes import router

log = logging.getLogger(__name__)


class GitHubHandler:
    def __init__(
        self, webhook_secret, account_map, github_client_factory, gitlab_client_factory
    ):
        self.webhook_secret = webhook_secret
        self.account_map = account_map
        self.gh = github_client_factory
        self.gl = gitlab_client_factory

    async def handle(self, request):
        try:
            # read the GitHub webhook payload
            body = await request.read()
            event = sansio.Event.from_http(
                request.headers, body, secret=self.webhook_secret
            )

            log.info(
                "GitHub webhook received",
                extra={"event_type": event.event, "delivery_id": event.delivery_id},
            )

            # TODO if gitlab_oauth is the account mapper and github is the provider
            # we'll need to input the numerical github user id (not username) into the account map
            # what the best way to address this/propagate the config down here so we can input the right user id?
            github_user = event.data["sender"]["login"]
            gitlab_user = self.account_map(github_user)

            if gitlab_user is None:
                log.info("Unauthorized GitHub user", extra={"github_user": github_user})
                return web.Response(status=200)

            gh_repo_owner = event.data["repository"]["owner"]["login"]
            gh_repo = event.data["repository"]["name"]

            gh = self.gh.create_client(gh_repo_owner, gh_repo)
            gl = self.gl.create_client(gitlab_user)

            await spawn(request, router.dispatch(event, gh, gl, gitlab_user))

            # return a "Success"
            return web.Response(status=200)
        except Exception:
            log.exception("Failed to handle Github webhook")
            return web.Response(status=500)
