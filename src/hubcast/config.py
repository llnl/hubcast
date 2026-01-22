import os
from typing import Optional


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
            # optional settings: if None, the mapper will behave accordingly
            self.ldap_map_bind_dn = os.environ.get("HC_LDAP_MAP_BIND_DN")
            self.ldap_map_bind_password = os.environ.get("HC_LDAP_MAP_BIND_PASSWORD")

        self.gh = GitHubConfig()
        self.gl = GitLabConfig()


class GitHubConfig:
    def __init__(self):
        self.app_id = env_get("HC_GH_APP_IDENTIFIER")
        self.privkey = env_get("HC_GH_PRIVATE_KEY")
        self.requester = env_get("HC_GH_REQUESTER")
        self.webhook_secret = env_get("HC_GH_SECRET")
        self.bot_user = env_get("HC_GH_BOT_USER")


class GitLabConfig:
    def __init__(self):
        self.instance_url = env_get("HC_GL_URL")
        # requester identifies the app making requests, it doesn't
        # perform any auth function but is included in user-agent
        self.requester = env_get("HC_GL_REQUESTER")
        self.token = env_get("HC_GL_TOKEN")
        self.token_type = env_get("HC_GL_TOKEN_TYPE", default="impersonation")
        self.webhook_secret = env_get("HC_GL_SECRET")
        self.callback_url = env_get("HC_GL_CALLBACK_URL")


def env_get(key: str, default: Optional[str] = None) -> str:
    value = os.environ.get(key) or default
    if not value:
        raise ConfigError(f"Required environment variable not found: {key}")

    return value
