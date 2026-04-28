import logging

from aiohttp import web
from aiojobs.aiohttp import spawn
from gidgetlab import sansio
from gidgetlab.exceptions import ValidationFailure

from hubcast.clients.github import GitHubClientFactory
from hubcast.exceptions import HubcastError

from .routing_token import RoutingTokenError, validate_routing_token
from .routes import router

log = logging.getLogger(__name__)


class GitLabHandler:
    def __init__(self, webhook_secret: str, github_client_factory: GitHubClientFactory):
        self.webhook_secret = webhook_secret
        self.github_client_factory = github_client_factory

    async def handle(self, request: web.Request) -> web.Response:
        try:
            token = request.headers.get("x-gitlab-token")
            if not token:
                log.warning("Missing webhook token in headers")
                return web.Response(status=401, text="Unauthorized")

            # Validate token signature and extract routing information
            try:
                routing_data = validate_routing_token(self.webhook_secret, token)
            except RoutingTokenError as e:
                e.log(log)
                return web.Response(status=401, text="Unauthorized")

            gh_repo_owner = routing_data["gh_owner"]
            gh_repo = routing_data["gh_repo"]
            gh_check_name = routing_data["gh_check"]

            body = await request.read()

            # Pass token as secret for gidgetlab's string validation
            # (redundant from security perspective, but required by library)
            event = sansio.Event.from_http(request.headers, body, secret=token)
            log.info("GitLab webhook received", extra={"event_type": event.event})

            github_client = self.github_client_factory.create_client(
                gh_repo_owner, gh_repo
            )

            await spawn(
                request,
                router.dispatch(event, github_client, gh_check_name),
            )

            # return a "Success"
            return web.Response(status=200)
        except HubcastError as e:
            e.log(log)
            return web.Response(status=500)
        except ValidationFailure:
            log.exception(
                "Failed to validate Gitlab webhook request",
            )
            return web.Response(status=500)
        except Exception:
            log.exception("Failed to handle GitLab webhook")
            return web.Response(status=500)
