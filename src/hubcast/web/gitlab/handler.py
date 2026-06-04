import logging

from aiohttp import web
from aiojobs.aiohttp import spawn
from gidgetlab import sansio
from gidgetlab.exceptions import ValidationFailure

from hubcast.clients.github import GitHubClientFactory
from hubcast.clients.gitlab import GitLabClientFactory
from hubcast.exceptions import HubcastError
from hubcast.logging import update_log_context
from hubcast.web.gitlab.routes import router
from hubcast.webhook import RoutingToken, RoutingTokenError

log = logging.getLogger(__name__)


class GitLabHandler:
    def __init__(
        self,
        webhook_secret: str,
        github_client_factory: GitHubClientFactory,
        gitlab_client_factory: GitLabClientFactory,
    ):
        self.webhook_secret = webhook_secret
        self.github_client_factory = github_client_factory
        self.gitlab_client_factory = gitlab_client_factory

    async def handle(self, request: web.Request) -> web.Response:
        try:
            token = request.headers.get("x-gitlab-token")
            if not token:
                log.warning("Missing webhook token in headers")
                return web.Response(status=401, text="Unauthorized")

            # Validate token signature and extract routing information
            try:
                routing_token = RoutingToken.decode(self.webhook_secret, token)
            except RoutingTokenError as e:
                e.log(log)
                return web.Response(status=401, text="Unauthorized")

            gh_repo_owner = routing_token.gh_owner
            gh_repo = routing_token.gh_repo
            gh_check_name = routing_token.gh_check

            relayed_check_types = routing_token.check_types

            body = await request.read()

            # Pass token as secret for gidgetlab's string validation
            # (redundant from security perspective, but required by library)
            event = sansio.Event.from_http(request.headers, body, secret=token)

            # Set request metadata in context
            update_log_context(
                event_type=event.event,
                dest_repo_org=gh_repo_owner,
                dest_repo_name=gh_repo,
            )

            log.info("GitLab webhook received")

            github_client = self.github_client_factory.create_client(
                gh_repo_owner, gh_repo
            )

            gl_user = event.data["user"]["username"]
            gitlab_client = self.gitlab_client_factory.create_client(gl_user)
            await spawn(
                request,
                router.dispatch(
                    event,
                    github_client,
                    gitlab_client,
                    gh_check_name,
                    relayed_check_types,
                ),
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
