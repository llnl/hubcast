import os

import pytest

from hubcast.config import Config, ConfigError, GitHubConfig


@pytest.fixture
def gh_defaults():
    """Default GitHub config values for testing."""
    return {"app_id": "123", "private_key": "key", "webhook_secret": "secret"}


def test_load_config_missing_required():
    """Should raise ConfigError if required environment variables are missing."""

    # Clear any existing config env vars
    env_vars_to_clear = [key for key in os.environ if key.startswith("HC_")]
    original_values = {}
    for key in env_vars_to_clear:
        original_values[key] = os.environ.pop(key)

    try:
        with pytest.raises(ConfigError, match="Configuration validation failed"):
            from hubcast.config import load_config

            load_config()
    finally:
        # Restore original values
        for key, value in original_values.items():
            os.environ[key] = value


def test_config_with_env_vars():
    """Should load config from environment variables."""

    # Set minimal required env vars
    os.environ["HC_GH_APP_ID"] = "123456"
    os.environ["HC_GH_PRIVATE_KEY"] = "test-key"
    os.environ["HC_GH_WEBHOOK_SECRET"] = "test-secret"
    os.environ["HC_GL_URL"] = "https://gitlab.com"
    os.environ["HC_GL_TOKEN"] = "test-token"
    os.environ["HC_GL_WEBHOOK_SECRET"] = "test-secret"
    os.environ["HC_GL_CALLBACK_URL"] = "https://example.com/callback"
    os.environ["HC_ACCOUNT_MAP_TYPE"] = "file"
    os.environ["HC_ACCOUNT_MAP_PATH"] = "/tmp/map.yaml"

    try:
        config = Config.model_validate({})
        assert config.gh.app_id == "123456"
        assert config.gh.private_key == "test-key"
        assert config.gl.url == "https://gitlab.com"
        assert config.account_map.type == "file"
    finally:
        # Clean up
        for key in list(os.environ.keys()):
            if key.startswith("HC_"):
                del os.environ[key]


def test_bot_caller_normalization(gh_defaults):
    """Should normalize bot_caller to start with @ or /."""

    # Bare username should add @
    config = GitHubConfig(**gh_defaults, bot_caller="hubcast")
    assert config.bot_caller == "@hubcast"

    # @ prefix should keep as is
    config = GitHubConfig(**gh_defaults, bot_caller="@hubcast")
    assert config.bot_caller == "@hubcast"

    # / prefix should keep as is
    config = GitHubConfig(**gh_defaults, bot_caller="/hubcast")
    assert config.bot_caller == "/hubcast"
