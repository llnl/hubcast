import json
import logging
import logging.config
import os
import sys

from aiohttp import web
from aiojobs.aiohttp import setup

from hubcast.account_map.file import FileMap, FileMapError
from hubcast.account_map.gitlab_oauth import GitlabOauthMap
from hubcast.clients.github import GitHubClientFactory
from hubcast.clients.gitlab import GitLabClientFactory
from hubcast.config import Config, ConfigError
from hubcast.web.github import GitHubHandler
from hubcast.web.gitlab import GitLabHandler

log = logging.getLogger(__name__)


def main():
    app = web.Application()

    try:
        conf = Config()
    except ConfigError as exc:
        log.error(exc)
        sys.exit(1)

    if os.path.exists(conf.logging_config_path):
        try:
            with open(conf.logging_config_path) as f:
                logging_config = json.load(f)
            logging.config.dictConfig(logging_config)
        except (
            json.decoder.JSONDecodeError,
            # calls to logging.config.dictConfig will raise the following exceptions (cf stdlib docs):
            ValueError,
            TypeError,
            AttributeError,
            ImportError,
        ) as exc:
            log.error(exc)
            sys.exit(1)
    else:
        logging.basicConfig(level=logging.INFO)

    # error if we're unable to initialize an account map
    if conf.account_map_type == "file":
        try:
            account_map = FileMap(conf.account_map_path)
        except FileMapError:
            log.exception("Error initializing file account map")
            sys.exit(1)
    elif conf.account_map_type == "gitlab_oauth":
        account_map = GitlabOauthMap(
            gitlab_url=conf.gl.instance_url,
            access_token=conf.gl_oauth_access_token,
            oauth_provider=conf.gl_oauth_provider,
        )

    else:
        log.error(
            "Unknown account map type",
            extra={"account_map_type": conf.account_map_type},
        )
        sys.exit(1)

    gh_client_factory = GitHubClientFactory(
        conf.gh.app_id, conf.gh.privkey, conf.gh.requester, conf.gh.bot_user
    )
    gl_client_factory = GitLabClientFactory(
        conf.gl.instance_url,
        conf.gl.requester,
        conf.gl.token,
        conf.gl.callback_url,
        conf.gl.webhook_secret,
        conf.gl.token_type,
    )

    gh_handler = GitHubHandler(
        conf.gh.webhook_secret,
        account_map,
        gh_client_factory,
        gl_client_factory,
    )

    gl_handler = GitLabHandler(
        conf.gl.webhook_secret,
        gh_client_factory,
    )

    log.info("Starting HTTP server")

    app.router.add_post("/v1/events/src/github", gh_handler.handle)
    app.router.add_post("/v1/events/dest/gitlab", gl_handler.handle)

    setup(app)
    web.run_app(
        app,
        port=conf.port,
        access_log_format='"%r" %s %b "%{Referer}i" "%{User-Agent}i"',
    )


if __name__ == "__main__":
    main()
