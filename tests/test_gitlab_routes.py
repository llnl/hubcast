# tests for gitlab route handlers

from unittest.mock import AsyncMock, Mock

import pytest

from hubcast.web.gitlab.routes import pipeline_status_relay

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


@pytest.fixture
def mock_gl():
    """Mocked GitLab client"""
    return AsyncMock()


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
    gitlab_status, expected_github_status, mock_pipeline_event, mock_gh, mock_gl
):
    """Should map GitLab status to GitHub status."""

    mock_pipeline_event.data["object_attributes"]["status"] = gitlab_status
    mock_pipeline_event.data["project"] = {"path_with_namespace": "org/repo"}

    result = await pipeline_status_relay(
        mock_pipeline_event, mock_gh, mock_gl, "ci-check", create_mr=False
    )

    assert result == expected_github_status
    mock_gh.set_check_status.assert_called_once()
    call_args = mock_gh.set_check_status.call_args
    assert call_args[0][0] == "commit-sha-123"
    assert call_args[0][1] == "ci-check"
    assert call_args[0][2] == expected_github_status
