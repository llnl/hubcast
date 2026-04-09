import logging

from aiohttp import web
from aiojobs.aiohttp import spawn
from gidgetlab import sansio
from gidgetlab.exceptions import ValidationFailure

from hubcast.clients.github import GitHubClientFactory

from .routes import router

log = logging.getLogger(__name__)


class GitLabHandler:
    def __init__(self, webhook_secret: str, github_client_factory: GitHubClientFactory):
        self.webhook_secret = webhook_secret
        self.github_client_factory = github_client_factory

    async def handle(self, request: web.Request) -> web.Response:
        try:
            # read the GitLab webhook payload
            body = await request.read()
            event = sansio.Event.from_http(
                request.headers, body, secret=self.webhook_secret
            )
            log.info("GitLab webhook received", extra={"event_type": event.event})

            # get coorisponding GitHub repo owner and name from event
            # request variables
            gh_repo_owner = request.rel_url.query["gh_owner"]
            gh_repo = request.rel_url.query["gh_repo"]

            github_client = self.github_client_factory.create_client(
                gh_repo_owner, gh_repo
            )

            gh_check_name = request.rel_url.query["gh_check"]

            await spawn(
                request,
                router.dispatch(event, github_client, gh_check_name),
            )

            # return a "Success"
            return web.Response(status=200)
        except ValidationFailure:
            log.exception(
                "Failed to validate Gitlab webhook request",
            )
            return web.Response(status=500)

        except Exception:
            log.exception("Failed to handle GitLab webhook")
            return web.Response(status=500)
