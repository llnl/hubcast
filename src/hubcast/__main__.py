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
from hubcast.clients.gitlab import GitLabDestClientFactory, GitLabSrcClientFactory
from hubcast.config import (
    Config,
    ConfigError,
    FileAccountMapConfig,
    GitHubConfig,
    GitLabSrcConfig,
    LDAPAccountMapConfig,
    load_config,
)
from hubcast.web.github import GitHubHandler
from hubcast.web.gitlab import GitLabDestHandler, GitLabSrcHandler
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
            f"Logging config file not found: {conf.logging_config_path}",
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
            except FileMapError as e:
                e.log(log)
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


def initialize_src(
    conf: Config,
    account_map: AccountMap,
    gl_client_factory: GitLabDestClientFactory,
) -> tuple[
    GitHubHandler | GitLabSrcHandler, GitHubClientFactory | GitLabSrcClientFactory
]:
    """Build source forge webhook handlers and client factories"""
    match conf.src:
        case GitHubConfig() as gh:
            gh_client_factory = GitHubClientFactory(
                gh.app_id, gh.private_key, REQUESTER, gh.bot_caller
            )
            handler = GitHubHandler(
                gh.webhook_secret,
                account_map,
                gh_client_factory,
                gl_client_factory,
            )
            return handler, gh_client_factory
        case GitLabSrcConfig() as gl_src:
            gl_src_client_factory = GitLabSrcClientFactory(
                gl_src.url,
                gl_src.access_token,
                REQUESTER,
                gl_src.bot_caller,
            )
            handler = GitLabSrcHandler(
                gl_src.webhook_secret,
                account_map,
                gl_src_client_factory,
                gl_client_factory,
            )
            return handler, gl_src_client_factory


def main():
    app = web.Application()

    try:
        conf = load_config()
    except ConfigError as exc:
        log.error(exc)
        sys.exit(1)

    initialize_logging(conf)

    account_map = initialize_account_map(conf)
    gl_client_factory = GitLabDestClientFactory(
        conf.gl.url,
        REQUESTER,
        conf.gl.token,
        conf.gl.callback_url,
        conf.gl.webhook_secret,
        conf.gl.token_type,
    )

    src_handler, src_client_factory = initialize_src(
        conf, account_map, gl_client_factory
    )

    gl_handler = GitLabDestHandler(
        conf.gl.webhook_secret,
        src_client_factory,
        gl_client_factory,
    )

    log.info("Starting HTTP server")

    app.router.add_get("/health", health_check)
    app.router.add_post(f"/v1/events/src/{conf.src.forge}", src_handler.handle)
    app.router.add_post("/v1/events/dest/gitlab", gl_handler.handle)

    setup(app)
    web.run_app(
        app,
        port=conf.port,
        access_log_format='"%r" %s %b "%{Referer}i" "%{User-Agent}i"',
    )


if __name__ == "__main__":
    main()
