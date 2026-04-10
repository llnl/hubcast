import os


class ConfigError(Exception):
    pass


class Config:
    def __init__(self):
        self.port = int(env_get("HC_PORT", default="8080"))

        self.account_map_type = env_get("HC_ACCOUNT_MAP_TYPE")

        self.logging_config_path = env_get("HC_LOGGING_CONFIG_PATH")

        if self.account_map_type == "file":
            self.account_map_path = env_get("HC_ACCOUNT_MAP_PATH")
        elif self.account_map_type == "ldap":
            self.ldap_map_uri = env_get("HC_LDAP_MAP_URI")
            self.ldap_map_base = env_get("HC_LDAP_MAP_BASE")
            self.ldap_map_input = env_get("HC_LDAP_MAP_INPUT")
            self.ldap_map_output = env_get("HC_LDAP_MAP_OUTPUT")
            self.ldap_map_scope = env_get("HC_LDAP_MAP_SCOPE")
            self.ldap_map_bind_dn = env_get("HC_LDAP_MAP_BIND_DN", optional=True)
            self.ldap_map_bind_password = env_get(
                "HC_LDAP_MAP_BIND_PASSWORD", optional=True
            )

        self.gh = GitHubConfig()
        self.gl = GitLabConfig()


class GitHubConfig:
    def __init__(self):
        self.app_id = env_get("HC_GH_APP_IDENTIFIER")
        self.privkey = env_get("HC_GH_PRIVATE_KEY")
        self.webhook_secret = env_get("HC_GH_SECRET")

        self.bot_caller = env_get("HC_GH_BOT_USER", default="/hubcast")
        if not self.bot_caller.startswith(("/", "@")):
            self.bot_caller = f"@{self.bot_caller}"


class GitLabConfig:
    def __init__(self):
        self.instance_url = env_get("HC_GL_URL")
        self.token = env_get("HC_GL_TOKEN")
        self.token_type = env_get("HC_GL_TOKEN_TYPE", default="impersonation")
        self.webhook_secret = env_get("HC_GL_SECRET")
        self.callback_url = env_get("HC_GL_CALLBACK_URL")


def env_get(key: str, default: str | None = None, optional: bool = False) -> str | None:
    """
    Retrieve environment variables.

    Attributes:
    ----------
    key: str
        The environment variable key to retrieve.
    default: any, optional
        The default value to return if the environment variable is not set.
        If you want the return value to be None if not set, use optional=True instead.
    optional: bool, optional
        If True and no default is provided, return None when the environment variable is not set.
    """

    try:
        return os.environ[key]
    except KeyError:
        if default is not None:
            return default

        if optional:
            return None

        raise ConfigError(f"Required environment variable not found: {key}")
