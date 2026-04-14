from unittest.mock import AsyncMock

import pytest

from hubcast.exceptions import HubcastError
from hubcast.repos.config import RepoConfig
from hubcast.web.github.utils import config_cache, get_repo_config


### FIXTURES
@pytest.fixture
def mock_github_client():
    """Mock GitHub client."""
    client = AsyncMock()
    client.get_repo_config = AsyncMock(
        return_value="Repo:\n  dest_org: owner\n  dest_name: repo\n"
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

    config = RepoConfig.from_yaml_data({"dest_org": "owner", "dest_name": "repo"})

    assert config.dest_org == "owner"
    assert config.dest_name == "repo"
    assert config.sync_drafts is True  # default
    assert config.sync_drafts_msg is True  # default


def test_create_config_full():
    """Should create RepoConfig with all settings."""

    config = RepoConfig.from_yaml_data(
        {
            "dest_org": "owner",
            "dest_name": "repo",
            "sync_drafts": False,
            "sync_drafts_msg": False,
        }
    )

    assert config.dest_org == "owner"
    assert config.dest_name == "repo"
    assert config.sync_drafts is False
    assert config.sync_drafts_msg is False


@pytest.mark.asyncio
async def test_get_repo_config_uses_cache(mock_github_client):
    """Should use cached config on second call."""

    # first call -- fetches from client
    config1, fetched1 = await get_repo_config(mock_github_client, "owner/repo")

    # second call -- uses cache
    config2, fetched2 = await get_repo_config(mock_github_client, "owner/repo")

    assert config1.dest_org == config2.dest_org
    assert fetched1 is True  # first call should fetch from GitHub
    assert fetched2 is False  # second call should use cache
    mock_github_client.get_repo_config.assert_called_once()  # should only be called once


@pytest.mark.asyncio
async def test_get_repo_config_refreshes(mock_github_client):
    """Should refresh cache when requested."""

    # first call
    config1, fetched1 = await get_repo_config(mock_github_client, "owner/repo")

    # update mock to return different data
    mock_github_client.get_repo_config.return_value = (
        "Repo:\n  dest_org: new-org\n  dest_name: new-repo\n"
    )

    # second call with refresh
    config2, fetched2 = await get_repo_config(
        mock_github_client, "owner/repo", refresh=True
    )

    assert config1.dest_org == "owner"
    assert config2.dest_org == "new-org"
    assert config2.dest_name == "new-repo"
    assert fetched1 is True  # first call should fetch
    assert fetched2 is True  # refresh should also fetch (not use cache)
    # should be called twice due to refresh
    assert mock_github_client.get_repo_config.call_count == 2


@pytest.mark.asyncio
async def test_get_repo_config_invalid_yaml():
    """Test handling of invalid YAML in repo config."""
    gh = AsyncMock()
    gh.get_repo_config = AsyncMock(return_value="invalid: yaml: :")
    gh.repo_owner = "owner"
    gh.repo_name = "repo"

    with pytest.raises(HubcastError, match="Invalid YAML in repo config"):
        await get_repo_config(gh, "owner/repo")


@pytest.mark.asyncio
async def test_get_repo_config_missing_repo_key():
    """Test handling of missing 'Repo' top-level key."""
    gh = AsyncMock()
    # valid YAML but missing the required 'Repo' key
    gh.get_repo_config = AsyncMock(return_value="NotRepo:\n  dest_org: owner\n")
    gh.repo_owner = "owner"
    gh.repo_name = "repo"

    with pytest.raises(HubcastError, match="missing required key"):
        await get_repo_config(gh, "owner/repo")


@pytest.mark.asyncio
async def test_get_repo_config_missing_required_fields():
    """Test handling of missing required fields within Repo config."""
    gh = AsyncMock()
    # valid YAML with 'Repo' key but missing required fields
    gh.get_repo_config = AsyncMock(return_value="Repo:\n  dest_org: owner\n")
    gh.repo_owner = "owner"
    gh.repo_name = "repo"

    with pytest.raises(HubcastError, match="Missing required fields: dest_name"):
        await get_repo_config(gh, "owner/repo")
