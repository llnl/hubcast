# tests for gitlab route handlers

from unittest.mock import AsyncMock, Mock

import pytest

from hubcast.exceptions import HubcastError
from hubcast.web.gitlab.routes import (
    GitLabRouter,
    job_status_relay,
    pipeline_status_relay,
)

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
            "source": "",
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
    "gitlab_status,github_status,check_types,should_relay",
    [
        ("pending", "queued", ["pipeline"], True),
        ("running", "in_progress", ["pipeline"], True),
        ("failed", "failure", ["pipeline"], True),
        ("canceled", "cancelled", ["pipeline"], True),
        ("success", "success", ["pipeline"], True),
        ("manual", None, ["pipeline"], False),  # unmapped status
        ("created", None, ["pipeline"], False),  # unmapped status
        ("success", "success", ["jobs"], False),  # wrong check_type
    ],
)
async def test_pipeline_status_mapping(
    gitlab_status, github_status, check_types, should_relay, base_pipeline_event, mock_gh, mock_gl, caplog
):
    """Should map GitLab pipeline status to GitHub status and respect filters."""
    base_pipeline_event["object_attributes"]["status"] = gitlab_status
    event = make_event(base_pipeline_event)

    await pipeline_status_relay(event, mock_gh, mock_gl, "ci", check_types)

    if should_relay:
        assert "Relayed pipeline status" in caplog.text
        assert any(
            hasattr(record, "status") and record.status == github_status
            for record in caplog.records
        )
        commit, name, status = mock_gh.set_check_status.call_args[0][:3]
        assert commit == "test-sha"
        assert name == "ci"
        assert status == github_status
    else:
        mock_gh.set_check_status.assert_not_called()
        if github_status is None:
            assert "Skipped pipeline status relay" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "merge_request,ref_suffix,expected_commit,pipeline_source,check_types,should_relay",
    [
        (None, None, "test-sha", "", ["pipeline"], True),
        ({"id": 1}, "/head", "test-sha", "", ["pipeline"], True),
        ({"id": 1}, "/merge", "source", "", ["pipeline"], True),
        (None, None, "test-sha", "parent_pipeline", ["child-pipelines"], True),
        (None, None, "test-sha", "parent_pipeline", ["pipeline"], False),  # child filtered out
    ],
)
async def test_pipeline_commit_resolution(
    merge_request,
    ref_suffix,
    expected_commit,
    pipeline_source,
    check_types,
    should_relay,
    base_pipeline_event,
    mock_gh,
    mock_gl,
    caplog,
):
    """Should resolve correct commit SHA and respect event type filters."""
    base_pipeline_event["object_attributes"]["source"] = pipeline_source
    if merge_request:
        base_pipeline_event["merge_request"] = merge_request
        mock_gl.get_pipeline.return_value = {
            "ref": f"refs/merge-requests/1{ref_suffix}"
        }

    event = make_event(base_pipeline_event)
    await pipeline_status_relay(event, mock_gh, mock_gl, "ci", check_types)

    if should_relay:
        assert "Relayed pipeline status" in caplog.text
        commit, name, _ = mock_gh.set_check_status.call_args[0][:3]
        assert commit == expected_commit
        if pipeline_source == "parent_pipeline":
            assert name.startswith("ci / ")
        else:
            assert name == "ci"
    else:
        mock_gh.set_check_status.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref,expected_commit,job_status,check_types,pipeline_source,expected_name,should_relay",
    [
        ("refs/heads/main", "test-sha", "success", ["jobs"], "", "ci / test-job", True),
        ("refs/merge-requests/1/head", "test-sha", "success", ["jobs"], "", "ci / test-job", True),
        ("refs/merge-requests/1/merge", "source", "success", ["jobs"], "", "ci / test-job", True),
        ("refs/heads/main", "test-sha", "created", ["jobs"], "", "ci / test-job", False),  # unmapped
        ("refs/heads/main", "test-sha", "success", ["child-pipelines"], "parent_pipeline", "ci / child-pipe / test-job", True),
        ("refs/heads/main", "test-sha", "success", ["child-pipelines"], "", "ci / test-job", True),  # not child
        ("refs/heads/main", "test-sha", "success", ["jobs"], "parent_pipeline", "ci / test-job", True),  # child not tracked
    ],
)
async def test_job_commit_resolution(
    ref, expected_commit, job_status, check_types, pipeline_source, expected_name, should_relay, base_job_event, mock_gh, mock_gl, caplog
):
    """Should resolve correct commit SHA, respect status mapping, and handle child pipeline naming."""
    base_job_event["ref"] = ref
    base_job_event["build_status"] = job_status
    base_job_event["pipeline_id"] = 456
    event = make_event(base_job_event)

    mock_gl.get_pipeline.return_value = {
        "ref": "refs/heads/main",
        "source": pipeline_source,
        "name": "child-pipe" if pipeline_source == "parent_pipeline" else None,
    }

    await job_status_relay(event, mock_gh, mock_gl, "ci", check_types)

    if should_relay:
        assert "Relayed job status" in caplog.text
        commit, name, _ = mock_gh.set_check_status.call_args[0][:3]
        assert commit == expected_commit
        assert name == expected_name
    else:
        mock_gh.set_check_status.assert_not_called()
        assert "Skipped job status relay" in caplog.text


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
