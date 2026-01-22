import os

import pytest

from hubcast.config import ConfigError, env_get


def test_env_get_var_or_default():
    """Should return the environment variable if set, else the default."""

    os.environ["TEST_ENV_VAR"] = "value_from_env"
    assert env_get("TEST_ENV_VAR", default="default_value") == "value_from_env"
    del os.environ["TEST_ENV_VAR"]
    assert env_get("TEST_ENV_VAR", default="default_value") == "default_value"


def test_env_get_missing():
    """Should raise ConfigError if the environment variable is missing and no default is provided."""

    if "MISSING_ENV_VAR" in os.environ:
        del os.environ["MISSING_ENV_VAR"]

    # succeed if ConfigError is raised
    with pytest.raises(ConfigError):
        env_get("MISSING_ENV_VAR")
