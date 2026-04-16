from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    pass


class GitHubConfig(BaseModel):
    """GitHub source forge configuration."""

    # GitHub App ID
    app_id: str

    # Contents of the app private key file (do not strip newlines)
    private_key: str

    # Webhook secret for verifying requests from GitHub
    webhook_secret: str

    # Bot mention prefix for PR commands (e.g., "@lc-hubcast" or "/hubcast")
    bot_caller: str = "/hubcast"

    @field_validator("bot_caller")
    @classmethod
    def normalize_bot_caller(cls, v: str) -> str:
        """Ensure bot_caller starts with @ or /."""
        if not v.startswith(("/", "@")):
            return f"@{v}"
        return v


class GitLabConfig(BaseModel):
    """GitLab destination forge configuration."""

    # URL of the GitLab instance (e.g., https://gitlab.com)
    url: str

    # Token type: "impersonation" (default) or "single"
    token_type: str = "impersonation"

    # Personal access token with api scope
    token: str

    # Webhook secret for verifying requests from GitLab
    webhook_secret: str

    # URL where Hubcast receives GitLab events (e.g., https://hubcast.example.com/v1/events/dest/gitlab)
    callback_url: str


class FileAccountMapConfig(BaseModel):
    """File-based account map configuration."""

    type: Literal["file"] = "file"

    # Path to YAML file mapping source forge usernames to destination forge usernames
    path: str


class LDAPAccountMapConfig(BaseModel):
    """LDAP-based account map configuration."""

    type: Literal["ldap"] = "ldap"

    # URI of the LDAP instance (e.g., ldap://ldap.example.com)
    uri: str

    # Base DN for LDAP searches (e.g., dc=example,dc=com)
    base: str

    # LDAP attribute containing source forge user id (e.g., githubId)
    input: str

    # LDAP attribute containing destination forge user id (e.g., uid)
    output: str

    # LDAP search scope: 0 (base), 1 (one level), 2 (subtree)
    scope: int

    # Bind distinguished name (optional, uses SASL/GSSAPI if not provided)
    bind_dn: str | None = None

    # Bind password (optional)
    bind_password: str | None = None


AccountMapConfig = Annotated[
    Union[FileAccountMapConfig, LDAPAccountMapConfig],
    Field(discriminator="type"),
]


class Config(BaseSettings):
    """Main application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="HC_",
        env_nested_delimiter="__",
    )

    # Port for Hubcast to listen on
    port: int = 8080

    # Path to logging config JSON file (dictConfig format, optional)
    logging_config_path: str | None = None

    # Account mapper configuration (file or ldap)
    account_map: AccountMapConfig

    gh: GitHubConfig
    gl: GitLabConfig


def load_config() -> Config:
    """Load configuration from environment variables.

    Returns:
        Config: Validated configuration loaded from environment.

    Raises:
        ConfigError: Any validation failures.
    """
    try:
        return Config.model_validate({})
    except ValidationError as e:
        errors = "\n".join(
            f"  {'.'.join(map(str, err['loc']))}: {err['msg']}"
            for err in e.errors(include_url=False, include_input=False)
        )
        raise ConfigError(f"Configuration validation failed:\n{errors}") from None
