# tests for gitlab route handlers

from unittest.mock import AsyncMock, Mock

import pytest

from hubcast.exceptions import HubcastError
from hubcast.web.gitlab.routes import GitLabRouter, job_status_relay, pipeline_status_relay

### FIXTURES


@pytest.fixture
def base_pipeline_event():
    """Base GitLab pipeline event data."""
    return {
        "object_attributes": {
            "sha": "test-sha",
            "status": "success",
            "url": "https://gitlab.com/org/repo/-/pipelines/123",
            "id": 123,
        },
        "project": {"path_with_namespace": "org/repo"},
    }


@pytest.fixture
def base_job_event():
    """Base GitLab job event data."""
    return {
        "sha": "test-sha",
        "ref": "refs/heads/main",
        "build_id": 789,
        "build_name": "test-job",
        "build_status": "success",
        "project": {
            "path_with_namespace": "org/repo",
            "web_url": "https://gitlab.com/org/repo",
        },
    }


@pytest.fixture
def mock_gh():
    """Mocked GitHub client."""
    gh = AsyncMock()
    gh.set_check_status = AsyncMock()
    return gh


@pytest.fixture
def mock_gl():
    """Mocked GitLab client."""
    gl = AsyncMock()
    gl.get_pipeline = AsyncMock(return_value={"ref": "refs/heads/main"})
    gl.get_commit = AsyncMock(return_value={"parent_ids": ["target", "source"]})
    return gl


def make_event(data):
    """Helper to create mock event from data dict."""
    event = Mock()
    event.data = data
    event.object_attributes = data.get("object_attributes", {})
    return event


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "gitlab_status,github_status",
    [
        ("pending", "queued"),
        ("running", "in_progress"),
        ("failed", "failure"),
        ("canceled", "cancelled"),
        ("success", "success"),
    ],
)
async def test_pipeline_status_mapping(
    gitlab_status, github_status, base_pipeline_event, mock_gh, mock_gl
):
    """Should map GitLab pipeline status to GitHub status."""
    base_pipeline_event["object_attributes"]["status"] = gitlab_status
    event = make_event(base_pipeline_event)

    result = await pipeline_status_relay(event, mock_gh, mock_gl, "ci", create_mr=False)

    assert result == github_status
    commit, name, status = mock_gh.set_check_status.call_args[0][:3]
    assert commit == "test-sha"
    assert name == "ci"
    assert status == github_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "merge_request,ref_suffix,expected_commit,expected_type",
    [
        (None, None, "test-sha", "non-mr-branch"),
        ({"id": 1}, "/head", "test-sha", "branch"),
        ({"id": 1}, "/merge", "source", "merge request"),
    ],
)
async def test_pipeline_commit_resolution(
    merge_request, ref_suffix, expected_commit, expected_type,
    base_pipeline_event, mock_gh, mock_gl
):
    """Should resolve correct commit SHA for different pipeline types."""
    if merge_request:
        base_pipeline_event["merge_request"] = merge_request
        mock_gl.get_pipeline.return_value = {"ref": f"refs/merge-requests/1{ref_suffix}"}

    event = make_event(base_pipeline_event)
    await pipeline_status_relay(event, mock_gh, mock_gl, "ci", create_mr=True)

    commit, name, _ = mock_gh.set_check_status.call_args[0][:3]
    assert commit == expected_commit
    assert name == f"ci [{expected_type}]"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref,expected_commit,expected_suffix",
    [
        ("refs/heads/main", "test-sha", " [non-mr-branch]"),
        ("refs/merge-requests/1/head", "test-sha", " [branch]"),
        ("refs/merge-requests/1/merge", "source", " [merge request]"),
    ],
)
async def test_job_commit_resolution(
    ref, expected_commit, expected_suffix, base_job_event, mock_gh, mock_gl
):
    """Should resolve correct commit SHA for different job types."""
    base_job_event["ref"] = ref
    event = make_event(base_job_event)

    await job_status_relay(event, mock_gh, mock_gl, "ci", create_mr=True)

    commit, name, _ = mock_gh.set_check_status.call_args[0][:3]
    assert commit == expected_commit
    assert name == f"ci / test-job{expected_suffix}"


@pytest.mark.asyncio
async def test_router_hubcast_error_handling():
    """Should log HubcastError and continue dispatching."""
    router = GitLabRouter()
    callback = AsyncMock(side_effect=HubcastError("test error"))
    router.register("Test Hook")(callback)

    event = make_event({"object_attributes": {}})
    event.event = "Test Hook"

    await router.dispatch(event)
    callback.assert_called_once()
