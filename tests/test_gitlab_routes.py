# tests for gitlab route handlers

from unittest.mock import AsyncMock, Mock

import pytest

from hubcast.web.gitlab.routes import status_relay

### FIXTURES


@pytest.fixture
def mock_pipeline_event():
    """Mocked GitLab pipeline event"""

    event = Mock()
    event.data = {
        "object_attributes": {
            "sha": "commit-sha-123",
            "status": "pending",
            "url": "https://gitlab.com/org/repo/-/pipelines/456",
        }
    }
    return event


@pytest.fixture
def mock_gh():
    """Mocked GitHub client"""
    gh = AsyncMock()
    gh.set_check_status = AsyncMock()
    return gh


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gitlab_status,expected_github_status",
    [
        ("pending", "queued"),
        ("running", "in_progress"),
        ("failed", "failure"),
        ("canceled", "cancelled"),
        ("success", "success"),
    ],
)
async def test_status_relay_translates_statuses(
    gitlab_status, expected_github_status, mock_pipeline_event, mock_gh
):
    """Should map GitLab status to GitHub status."""

    mock_pipeline_event.data["object_attributes"]["status"] = gitlab_status

    result = await status_relay(mock_pipeline_event, mock_gh, "ci-check")

    assert result == expected_github_status
    mock_gh.set_check_status.assert_called_once_with(
        "commit-sha-123",
        "ci-check",
        expected_github_status,
        "https://gitlab.com/org/repo/-/pipelines/456",
    )
