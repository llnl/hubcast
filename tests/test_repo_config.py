from unittest.mock import AsyncMock

import pytest

from hubcast.web.github.utils import config_cache, create_config, get_repo_config


### FIXTURES
@pytest.fixture
def mock_github_client():
    """Mock GitHub client."""
    client = AsyncMock()
    client.get_repo_config = AsyncMock(
        return_value={
            "Repo": {
                "owner": "owner",
                "name": "repo",
            }
        }
    )
    return client


@pytest.fixture(autouse=True)
def clear_config_cache():
    """Clear config cache before each test."""
    config_cache.clear()
    yield
    config_cache.clear()


### TESTS


def test_create_config_minimal():
    """Should create RepoConfig with minimal settings."""

    config = create_config("owner/repo", {"Repo": {"owner": "owner", "name": "repo"}})

    assert config.fullname == "owner/repo"
    assert config.dest_org == "owner"
    assert config.dest_name == "repo"
    assert config.draft_sync is True  # default
    assert config.draft_sync_msg is True  # default


def test_create_config_full():
    """Should create RepoConfig with all settings."""

    config = create_config(
        "owner/repo",
        {
            "Repo": {
                "owner": "owner",
                "name": "repo",
                "draft_sync": False,
                "draft_sync_msg": False,
            }
        },
    )

    assert config.fullname == "owner/repo"
    assert config.dest_org == "owner"
    assert config.dest_name == "repo"
    assert config.draft_sync is False
    assert config.draft_sync_msg is False


@pytest.mark.asyncio
async def test_get_repo_config_uses_cache(mock_github_client):
    """Should use cached config on second call."""

    # first call -- fetches from client
    config1 = await get_repo_config(mock_github_client, "owner/repo")

    # second call -- uses cache
    config2 = await get_repo_config(mock_github_client, "owner/repo")

    assert config1.dest_org == config2.dest_org
    mock_github_client.get_repo_config.assert_called_once()  # should only be called once


@pytest.mark.asyncio
async def test_get_repo_config_refreshes(mock_github_client):
    """Should refresh cache when requested."""

    # first call
    await get_repo_config(mock_github_client, "owner/repo")

    # update mock to return different data
    mock_github_client.get_repo_config.return_value = {
        "Repo": {"owner": "new-org", "name": "new-repo"}
    }

    # second call with refresh
    config = await get_repo_config(mock_github_client, "owner/repo", refresh=True)

    assert config.dest_org == "new-org"
    assert config.dest_name == "new-repo"
    # should be called twice due to refresh
    assert mock_github_client.get_repo_config.call_count == 2
