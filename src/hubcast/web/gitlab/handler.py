import logging

from aiohttp import web
from aiojobs.aiohttp import spawn
from gidgetlab import sansio
from gidgetlab.exceptions import ValidationFailure

from hubcast.account_map.abc import AccountMap
from hubcast.clients.github import GitHubClientFactory
from hubcast.clients.gitlab import GitLabDestClientFactory, GitLabSrcClientFactory
from hubcast.exceptions import HubcastError
from hubcast.logging import update_log_context
from hubcast.web.gitlab.routes import router
from hubcast.web.gitlab.src_routes import router as src_router
from hubcast.webhook import RoutingTokenError, decode_routing_token

log = logging.getLogger(__name__)


class GitLabDestHandler:
    """Handles CI status callbacks from the GitLab destination instance."""

    def __init__(
        self,
        webhook_secret: str,
        src_client_factory: GitHubClientFactory | GitLabSrcClientFactory,
        gitlab_client_factory: GitLabDestClientFactory,
    ):
        self.webhook_secret = webhook_secret
        self.src_client_factory = src_client_factory
        self.gitlab_client_factory = gitlab_client_factory

    async def handle(self, request: web.Request) -> web.Response:
        try:
            token = request.headers.get("x-gitlab-token")
            if not token:
                log.warning("Missing webhook token in headers")
                return web.Response(status=401, text="Unauthorized")

            # Validate token signature and extract routing information
            try:
                routing_token = decode_routing_token(self.webhook_secret, token)
            except RoutingTokenError as e:
                e.log(log)
                return web.Response(status=401, text="Unauthorized")

            body = await request.read()

            # Pass token as secret for gidgetlab's string validation
            # (redundant from security perspective, but required by library)
            event = sansio.Event.from_http(request.headers, body, secret=token)

            update_log_context(event_type=event.event)

            log.info("GitLab webhook received")

            src_forge = routing_token.src_forge
            if routing_token.src_forge == "github":
                src_check_name = routing_token.gh_check
                update_log_context(
                    src_repo_org=routing_token.gh_owner,
                    src_repo_name=routing_token.gh_repo,
                )
            else:
                src_check_name = routing_token.gl_check
                update_log_context(src_repo_id=routing_token.gl_repo_id)

            src_client = self.src_client_factory.create_client_from_token(routing_token)

            gl_user = event.data["user"]["username"]
            gitlab_client = self.gitlab_client_factory.create_client(gl_user)
            await spawn(
                request,
                router.dispatch(
                    event,
                    src_client,
                    gitlab_client,
                    src_forge,
                    src_check_name,
                    routing_token.check_types,
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


class GitLabSrcHandler:
    """Handles inbound webhooks from a GitLab source instance."""

    def __init__(
        self,
        webhook_secret: str,
        account_map: AccountMap,
        gitlab_src_client_factory: GitLabSrcClientFactory,
        gitlab_client_factory: GitLabDestClientFactory,
    ):
        self.webhook_secret = webhook_secret
        self.account_map = account_map
        self.src = gitlab_src_client_factory
        self.dest = gitlab_client_factory

    async def handle(self, request: web.Request) -> web.Response:
        try:
            body = await request.read()
            event = sansio.Event.from_http(
                request.headers, body, secret=self.webhook_secret
            )

            update_log_context(event_type=event.event)

            log.info("GitLab webhook received")

            # the Push Hook payload exposes the acting user as a flat
            # `user_username` field, while other hooks (Merge Request, Note)
            # nest it under `user.username` -- these are equivalent (verifiable
            # via user ID/avatar URL)
            src_user = event.data.get("user", {}).get("username") or event.data.get(
                "user_username"
            )

            update_log_context(src_user=src_user)

            dest_user = await self.account_map(src_user)

            if dest_user is None:
                log.info("Unauthorized GitLab user")
                return web.Response(status=200)

            update_log_context(dest_user=dest_user)
            log.info("User authorized")

            src_repo_id = event.data["project"]["id"]
            gl_src = self.src.create_client(src_repo_id)
            gl_dest = self.dest.create_client(dest_user)

            await spawn(
                request,
                src_router.dispatch(event, gl_src, gl_dest, dest_user),
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
