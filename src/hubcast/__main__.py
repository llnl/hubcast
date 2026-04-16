import json
import logging
import logging.config
import sys
from pathlib import Path

from aiohttp import web
from aiojobs.aiohttp import setup

from hubcast.account_map import FileMap
from hubcast.account_map.abc import AccountMap
from hubcast.account_map.file import FileMapError
from hubcast.clients.github import GitHubClientFactory
from hubcast.clients.gitlab import GitLabClientFactory
from hubcast.config import (
    Config,
    ConfigError,
    FileAccountMapConfig,
    LDAPAccountMapConfig,
    load_config,
)
from hubcast.web.github import GitHubHandler
from hubcast.web.gitlab import GitLabHandler
from hubcast.web.health import health_check

try:
    from hubcast.account_map import LDAPMap

    LDAP_AVAILABLE = True
except ImportError:
    LDAP_AVAILABLE = False


log = logging.getLogger(__name__)

# Set requester for both GitHub and GitLab clients to
# identify Hubcast via the user-agent header
REQUESTER = "hubcast"


def initialize_logging(conf: Config) -> None:
    """Initialize logging based on configuration."""
    if not conf.logging_config_path:
        logging.basicConfig(level=logging.INFO)
        return

    config_path = Path(conf.logging_config_path)
    if not config_path.exists():
        log.error(
            "Logging config file not found",
            extra={"path": conf.logging_config_path},
        )
        sys.exit(1)

    try:
        logging_config = json.loads(config_path.read_text())
        logging.config.dictConfig(logging_config)
    except (
        json.JSONDecodeError,
        # calls to logging.config.dictConfig will raise the following exceptions (cf stdlib docs):
        ValueError,
        TypeError,
        AttributeError,
        ImportError,
    ) as exc:
        log.error(exc)
        sys.exit(1)


def initialize_account_map(conf: Config) -> AccountMap:
    """Initialize and return the appropriate account map based on config."""
    match conf.account_map:
        case FileAccountMapConfig(path=path):
            try:
                return FileMap(path)
            except FileMapError:
                log.exception("Error initializing file account map")
                sys.exit(1)

        case LDAPAccountMapConfig() as ldap_config:
            if not LDAP_AVAILABLE:
                log.error(
                    "LDAP account map requested but python-ldap is not installed. "
                    "Install hubcast with the ldap extra: pip install hubcast[ldap] "
                    "or: spack install hubcast+ldap"
                )
                sys.exit(1)
            return LDAPMap(
                ldap_config.uri,
                ldap_config.base,
                ldap_config.input,
                ldap_config.output,
                ldap_config.scope,
                ldap_config.bind_dn,
                ldap_config.bind_password,
            )


def main():
    app = web.Application()

    try:
        conf = load_config()
    except ConfigError as exc:
        log.error(exc)
        sys.exit(1)

    initialize_logging(conf)

    account_map = initialize_account_map(conf)
    gh_client_factory = GitHubClientFactory(
        conf.gh.app_id, conf.gh.private_key, REQUESTER, conf.gh.bot_caller
    )
    gl_client_factory = GitLabClientFactory(
        conf.gl.url,
        REQUESTER,
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

    app.router.add_get("/health", health_check)
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
