# tests for Hubcast's GitHub route handlers

from collections.abc import Callable
from http import HTTPStatus
from typing import NamedTuple
from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiohttp.client_exceptions import ClientResponseError
from gidgethub import sansio
from gidgetlab.exceptions import BadRequest
from repligit.exceptions import RefUpdateRejected

from hubcast.exceptions import HubcastError, RepoConfigError, WebhookPermissionError
from hubcast.web.github.messages import (
    DEACTIVATED_ACCOUNT_MARKER,
    DEACTIVATED_ACCOUNT_MSG,
    HOOK_DECLINED_MSG,
    HOOK_DECLINED_SUMMARY,
    HOOK_DECLINED_TITLE,
    INTERNAL_ERROR_SUMMARY,
    INTERNAL_ERROR_TITLE,
    PERMISSION_DENIED_DELETE_LOG_MSG,
    PERMISSION_DENIED_SUMMARY,
    PERMISSION_DENIED_SYNC_LOG_MSG,
    PERMISSION_DENIED_TITLE,
    PIPELINE_FAILED_MSG,
    WEBHOOK_PERMISSION_DENIED_SUMMARY,
    WEBHOOK_PERMISSION_DENIED_TITLE,
)
from hubcast.web.github.routes import (
    ERROR_CHECK_NAME,
    remove_branch,
    remove_pr,
    rerun_check,
    respond_comment,
    respond_pr_comment,
    router,
    sync_branch,
    sync_pr_event,
)


def permission_error(status: int = 403) -> ClientResponseError:
    """Build the aiohttp error repligit raises on HTTP failures."""
    return ClientResponseError(request_info=Mock(), history=(), status=status)


def repo_config_error() -> RepoConfigError:
    return RepoConfigError(
        "Invalid repo config", title="config title", summary="config summary"
    )


### FIXTURES


@pytest.fixture
def mock_push_event():
    """Mocked branch push."""
    event = Mock()
    event.data = {
        "repository": {
            "clone_url": "https://github.com/owner/repo.git",
            "full_name": "owner/repo",
            "default_branch": "main",
        },
        "after": "sha-123",
        "head_commit": {"id": "sha-123", "message": "update app"},
        "ref": "refs/heads/main",
        "commits": [
            {"added": [], "modified": ["src/app.py"], "removed": []},
        ],
    }
    return event


@pytest.fixture
def mock_delete_event():
    """Mocked branch deletion."""
    event = Mock()
    event.data = {
        "repository": {"full_name": "owner/repo"},
        "ref": "refs/heads/feature-branch",
    }
    return event


@pytest.fixture
def mock_pr_event():
    """Mocked pull request creation/update."""
    event = Mock()
    event.data = {
        "repository": {
            "full_name": "owner/repo",
            "default_branch": "main",
        },
        "pull_request": {
            "number": 123,
            "draft": False,
            "head": {
                "repo": {
                    "clone_url": "https://github.com/fork-owner/repo.git",
                    "full_name": "fork-owner/repo",
                    "private": False,
                },
                "ref": "feature-branch",
            },
            "base": {"repo": {"full_name": "owner/repo"}},
        },
        "action": "synchronize",
        "after": "pr-sha-123",
    }
    return event


@pytest.fixture
def mock_pr_closed_event():
    """Mocked pull request closure."""
    event = Mock()
    event.data = {
        "pull_request": {
            "number": 123,
            "head": {"repo": {"full_name": "fork-owner/repo"}},
            "base": {"repo": {"full_name": "owner/repo"}},
        }
    }
    return event


@pytest.fixture
def mock_comment_event():
    """Mocked pull request comment."""
    event = Mock()
    event.data = {
        "issue": {
            "number": 123,
            "pull_request": {},  # indicates PR comment
        },
        "comment": {"node_id": 456, "body": "@hubcast-bot help"},
    }
    return event


@pytest.fixture
def mock_review_event(mock_pr_data_for_comment):
    """Mocked pull request review."""
    event = Mock()
    event.data = {
        "repository": {
            "full_name": "owner/repo",
            "default_branch": "main",
        },
        "review": {
            "node_id": 789,
            "body": "@hubcast-bot approve",
            "commit_id": "pr-sha-123",
        },
        "pull_request": mock_pr_data_for_comment,
    }
    return event


@pytest.fixture
def mock_pr_data_for_comment():
    """Mocked PR data returned by gh.get_pr()."""
    return {
        "number": 123,
        "draft": False,
        "head": {
            "repo": {
                "clone_url": "https://github.com/fork-owner/repo.git",
                "full_name": "fork-owner/repo",
                "private": False,
            },
            "sha": "pr-sha-123",
            "ref": "feature-branch",
        },
        "base": {"repo": {"full_name": "owner/repo"}},
    }


@pytest.fixture
def mock_check_run_event():
    """Mocked check run rerequested."""
    event = Mock()
    event.data = {
        "repository": {"full_name": "owner/repo"},
        "check_run": {
            "check_suite": {"head_branch": "main"},
            "head_sha": "check-run-sha-123",
        },
    }
    return event


@pytest.fixture
def mock_gh():
    """Mocked GitHub client"""
    gh = Mock()
    gh.get_prs = AsyncMock(return_value=[])
    gh.get_branch = AsyncMock(return_value={"commit": {"sha": "default-sha"}})
    gh.set_check_status = AsyncMock()
    gh.bot_caller = "hubcast-bot"
    gh.post_comment = AsyncMock()
    gh.react_to_comment = AsyncMock()
    gh.auth.authenticate_installation = AsyncMock(return_value="gh-token-123")
    return gh


@pytest.fixture
def mock_gl():
    """Mocked GitLab client"""
    gl = AsyncMock()
    return gl


@pytest.fixture
def mock_repligit_ops():
    """Mocked repligit operations (ls_remote, fetch_pack, send_pack)"""
    with (
        # patch modules at import location not at implementation
        patch("hubcast.web.github.routes.get_repo_config") as mock_get_config,
        patch("hubcast.web.github.routes.ls_remote") as mock_ls,
        patch("hubcast.web.github.routes.fetch_pack") as mock_fetch,
        patch("hubcast.web.github.routes.send_pack") as mock_send,
    ):
        # get_repo_config returns a tuple (config, fetched)
        default_config = Mock(
            dest_org="owner",
            dest_name="repo",
            sync_drafts=True,
            sync_drafts_msg=True,
            delete_closed=True,
            check_name="hubcast",
            check_types=["pipeline"],
        )
        mock_get_config.return_value = (default_config, True)

        mock_ls.return_value = {"refs/heads/main": "old-sha-456"}

        mock_fetch.return_value = b"packfile-data"
        mock_send.return_value = None

        yield {
            "get_repo_config": mock_get_config,
            "ls_remote": mock_ls,
            "fetch_pack": mock_fetch,
            "send_pack": mock_send,
        }


@pytest.fixture
def internal_pr_data(mock_pr_data_for_comment):
    """PR from same repo (not a fork)."""
    mock_pr_data_for_comment["head"]["repo"]["full_name"] = "owner/repo"
    mock_pr_data_for_comment["base"]["repo"]["full_name"] = "owner/repo"
    mock_pr_data_for_comment["head"]["ref"] = "feature-branch"
    return mock_pr_data_for_comment


@pytest.fixture
def setup_pr_mocks(mock_gh, mock_repligit_ops):
    """Configure mocks for PR-based tests."""

    def _setup(pr_data, needs_sync=True):
        mock_gh.get_pr = AsyncMock(return_value=pr_data)
        if needs_sync:
            mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    return _setup


@pytest.fixture
def setup_pipeline_mocks(mock_gl):
    """Configure mocks for pipeline operations."""

    def _setup(pipeline_exists=True):
        mock_gl.run_pipeline = AsyncMock(return_value="https://gitlab.com/pipeline/123")

        if pipeline_exists:
            mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
            mock_gl.retry_pipeline_jobs = AsyncMock(
                return_value="https://gitlab.com/pipeline/789"
            )
        else:
            mock_gl.get_latest_pipeline = AsyncMock(return_value=None)

    return _setup


@pytest.fixture
def call_respond_comment(mock_comment_event, mock_gh, mock_gl):
    """Helper to call respond_comment with a given command."""

    async def _call(command_body):
        mock_comment_event.data["comment"]["body"] = command_body
        return await respond_comment(mock_comment_event, mock_gh, mock_gl, "gl-user")

    return _call


@pytest.fixture
def call_respond_pr_comment(mock_review_event, mock_gh, mock_gl):
    """Helper to call respond_pr_comment with a given command."""

    async def _call(command_body):
        mock_review_event.data["review"]["body"] = command_body
        return await respond_pr_comment(mock_review_event, mock_gh, mock_gl, "gl-user")

    return _call


### UNIT TESTS

# Tests for router error handling


@pytest.mark.asyncio
async def test_github_dispatch_logs_hubcast_errors():
    """Should log HubcastError without crashing."""

    async def failing_handler(event, *args, **kwargs):
        raise HubcastError("Test error message", log_level="ERROR")

    event = sansio.Event({"ref": "refs/heads/main"}, event="push", delivery_id="123")

    # Temporarily register our failing handler
    original_handlers = router._shallow_routes.get("push", [])
    router._shallow_routes["push"] = [failing_handler]

    try:
        # Should not raise - error should be logged
        await router.dispatch(event)
    finally:
        router._shallow_routes["push"] = original_handlers


# Tests for sync_branch


@pytest.mark.asyncio
async def test_sync_branch_skip_open_pr(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branches should not be synced if there is an open PR for the branch."""

    # mocking hubcast.clients.github.client.GitHubClient.get_prs
    mock_gh.get_prs.return_value = [123]  # Simulate an open PR exists

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Skipped branch sync - branch has open PR" in caplog.text


@pytest.mark.asyncio
async def test_sync_branch_skip_up_to_date(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branches should not be synced if already up to date."""

    # no open PRs for the branch
    mock_gh.get_prs.return_value = []

    # mock ls_remote returning refs that already contain the want_sha
    # (the destination forge already has the commit)
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/main": "sha-123",  # Same as event's head_commit.id
    }

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Skipped branch sync - already up-to-date" in caplog.text


@pytest.mark.asyncio
async def test_sync_branch_synced(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branches should sync if all conditions are met."""

    # no open PRs for the branch
    mock_gh.get_prs.return_value = []

    # mock ls_remote returning refs that do NOT contain the want_sha
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha-456"}

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced branch" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref,modified,expected_refresh",
    [
        ("refs/heads/main", [".github/hubcast.yml"], True),
        ("refs/heads/main", ["src/app.py"], False),
        ("refs/heads/feature", [".github/hubcast.yml"], False),
    ],
)
async def test_sync_branch_config_refresh(
    ref,
    modified,
    expected_refresh,
    mock_push_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
):
    """Config should only be refreshed when a default branch push touches the config file."""

    mock_push_event.data["ref"] = ref
    mock_push_event.data["commits"] = [
        {"added": [], "modified": modified, "removed": []}
    ]

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_repligit_ops["get_repo_config"].assert_awaited_once_with(
        mock_gh, "owner/repo", refresh=expected_refresh
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "ref,fetched,commit_msg,webhook_expected",
    [
        # config was (re)fetched on a default branch push
        ("refs/heads/main", True, "update app", True),
        # cached config, no marker: nothing to do
        ("refs/heads/main", False, "update app", False),
        # manual trigger via commit message marker
        ("refs/heads/main", False, "empty commit [hubcast config]", True),
        # never set webhooks from non-default branches
        ("refs/heads/feature", True, "update app", False),
    ],
)
async def test_sync_branch_webhook_gating(
    ref,
    fetched,
    commit_msg,
    webhook_expected,
    mock_push_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
):
    """Webhook should only be set on default branch pushes with a config fetch or marker."""

    mock_push_event.data["ref"] = ref
    mock_push_event.data["head_commit"]["message"] = commit_msg
    config, _ = mock_repligit_ops["get_repo_config"].return_value
    mock_repligit_ops["get_repo_config"].return_value = (config, fetched)

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    if webhook_expected:
        mock_gl.set_webhook.assert_awaited_once()
    else:
        mock_gl.set_webhook.assert_not_called()


@pytest.mark.asyncio
async def test_sync_branch_webhook_permission_denied(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops
):
    """A non-maintainer pushing config changes should get a failed check explaining the fix."""

    mock_gl.set_webhook.side_effect = WebhookPermissionError("not a maintainer")

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_gh.set_check_status.assert_awaited_once_with(
        "sha-123",
        ERROR_CHECK_NAME,
        "failure",
        title=WEBHOOK_PERMISSION_DENIED_TITLE,
        summary=WEBHOOK_PERMISSION_DENIED_SUMMARY,
    )
    # the sync should not proceed
    mock_repligit_ops["send_pack"].assert_not_called()


@pytest.mark.asyncio
async def test_sync_branch_webhook_internal_error(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops
):
    """A broken hubcast credential should be reported as an internal error."""

    mock_gl.set_webhook.side_effect = HubcastError("GitLab rejected hubcast's token")

    await sync_branch(event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_gh.set_check_status.assert_awaited_once_with(
        "sha-123",
        ERROR_CHECK_NAME,
        "failure",
        title=INTERNAL_ERROR_TITLE,
        summary=INTERNAL_ERROR_SUMMARY,
    )
    mock_repligit_ops["send_pack"].assert_not_called()


# Tests for remove_branch


@pytest.mark.asyncio
async def test_remove_branch_skip_no_ref(
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branch removal should be skipped if the ref cannot be found on the destination."""

    # ls_remote returns some other refs, not the one being deleted
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "some-sha"}

    await remove_branch(
        event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Skipped branch removal - ref not found" in caplog.text


@pytest.mark.asyncio
async def test_remove_branch_deleted(
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branch removal should proceed if the ref exists."""

    # ls_remote has the ref we want to delete
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/feature-branch": "branch-sha-123",
    }

    await remove_branch(
        event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Deleted branch" in caplog.text


# Tests for sync_pr_event


@pytest.mark.asyncio
async def test_sync_pr_skip_private_fork(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR sync should be skipped for private forks."""

    mock_pr_event.data["pull_request"]["head"]["repo"]["private"] = True

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Skipped PR sync - private fork" in caplog.text


@pytest.mark.asyncio
async def test_sync_pr_skip_draft(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR sync should be skipped for draft PRs (when sync_drafts is False)."""

    mock_pr_event.data["pull_request"]["draft"] = True
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(sync_drafts=False, dest_org="owner", dest_name="repo"),
        True,
    )

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Skipped PR sync - draft PR" in caplog.text


@pytest.mark.asyncio
async def test_sync_pr_skip_draft_without_message(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Draft PR skips should not set a check status when sync_drafts_msg is False."""

    mock_pr_event.data["pull_request"]["draft"] = True
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(
            sync_drafts=False,
            sync_drafts_msg=False,
            dest_org="owner",
            dest_name="repo",
        ),
        True,
    )

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Skipped PR sync - draft PR" in caplog.text
    mock_gh.set_check_status.assert_not_called()


@pytest.mark.asyncio
async def test_sync_pr_skip_up_to_date(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR sync should be skipped if already up to date."""

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/pr-123": "pr-sha-123"}

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")
    assert "Skipped PR sync - already up-to-date" in caplog.text


@pytest.mark.asyncio
async def test_sync_pr_synced_fork(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR sync should proceed if all conditions are met (from fork)."""

    # ls_remote does not have the PR branch sha
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced PR" in caplog.text


@pytest.mark.asyncio
async def test_sync_pr_synced_internal(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR sync should proceed if all conditions are met (internal branch)."""

    # make head and base the same repo to simulate internal branch
    mock_pr_event.data["pull_request"]["head"]["repo"]["full_name"] = "owner/repo"
    mock_pr_event.data["pull_request"]["base"]["repo"]["full_name"] = "owner/repo"

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced PR" in caplog.text


@pytest.mark.asyncio
async def test_sync_pr_opened_uses_head_sha(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR opened event should use head sha instead of after field."""

    # Change action to "opened" instead of "synchronize"
    mock_pr_event.data["action"] = "opened"
    mock_pr_event.data["pull_request"]["head"]["sha"] = "head-sha-456"

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced PR" in caplog.text
    assert any(
        hasattr(record, "want_sha") and record.want_sha == "head-sha-456"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_sync_pr_creates_mr_when_configured(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Should create MR on GitLab when create_mr config is enabled and MR doesn't exist."""

    # Add title and html_url to PR data
    mock_pr_event.data["pull_request"]["title"] = "Test PR"
    mock_pr_event.data["pull_request"]["html_url"] = (
        "https://github.com/owner/repo/pull/123"
    )

    # Configure repo to create MRs
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(
            dest_org="owner",
            dest_name="repo",
            create_mr=True,
        ),
        True,
    )

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}
    mock_gl.get_mr = AsyncMock(return_value=None)  # No MR exists yet
    mock_gl.create_mr = AsyncMock()

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced PR" in caplog.text
    assert "Created MR" in caplog.text
    mock_gl.create_mr.assert_called_once()


@pytest.mark.asyncio
async def test_sync_pr_skips_mr_when_already_exists(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Should skip MR creation when MR already exists."""

    # Configure repo to create MRs
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(
            dest_org="owner",
            dest_name="repo",
            create_mr=True,
        ),
        True,
    )

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}
    mock_gl.get_mr = AsyncMock(return_value={"id": 42})  # MR already exists
    mock_gl.create_mr = AsyncMock()

    await sync_pr_event(event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert "Synced PR" in caplog.text
    assert "Created MR" not in caplog.text
    mock_gl.create_mr.assert_not_called()


# Shared error-handling tests for sync_branch and sync_pr_event


class SyncCase(NamedTuple):
    """A sync handler plus the event fixture and expectations its error tests share."""

    handler: Callable
    event_fixture: str
    sha: str
    success_log: str


sync_cases = pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            SyncCase(sync_branch, "mock_push_event", "sha-123", "Synced branch"),
            id="sync_branch",
        ),
        pytest.param(
            SyncCase(sync_pr_event, "mock_pr_event", "pr-sha-123", "Synced PR"),
            id="sync_pr",
        ),
    ],
)


@pytest.mark.asyncio
@sync_cases
async def test_sync_config_error_sets_error_check(
    case, request, mock_gh, mock_gl, mock_repligit_ops
):
    """An invalid repo config should be reported as a failed hubcast-error check."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["get_repo_config"].side_effect = repo_config_error()

    await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_gh.set_check_status.assert_awaited_once_with(
        case.sha,
        ERROR_CHECK_NAME,
        "failure",
        title="config title",
        summary="config summary",
    )
    mock_repligit_ops["send_pack"].assert_not_called()


@pytest.mark.asyncio
@sync_cases
@pytest.mark.parametrize(
    "failing_op,error,expected_title,expected_summary",
    [
        (
            "ls_remote",
            permission_error(401),
            PERMISSION_DENIED_TITLE,
            PERMISSION_DENIED_SUMMARY,
        ),
        (
            "ls_remote",
            permission_error(403),
            PERMISSION_DENIED_TITLE,
            PERMISSION_DENIED_SUMMARY,
        ),
        (
            "send_pack",
            permission_error(403),
            PERMISSION_DENIED_TITLE,
            PERMISSION_DENIED_SUMMARY,
        ),
        (
            "send_pack",
            RefUpdateRejected(HOOK_DECLINED_MSG),
            HOOK_DECLINED_TITLE,
            HOOK_DECLINED_SUMMARY,
        ),
    ],
    ids=["ls_remote-401", "ls_remote-403", "send_pack-403", "send_pack-hook-declined"],
)
async def test_sync_expected_error_fails_check(
    case,
    failing_op,
    error,
    expected_title,
    expected_summary,
    request,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    caplog,
):
    """Permission and hook-declined errors during sync should fail the pipeline check."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops[failing_op].side_effect = error

    await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_gh.set_check_status.assert_awaited_once_with(
        case.sha,
        "hubcast",
        "failure",
        title=expected_title,
        summary=expected_summary,
    )
    assert case.success_log not in caplog.text
    if failing_op == "ls_remote":
        assert PERMISSION_DENIED_SYNC_LOG_MSG in caplog.text
        mock_repligit_ops["send_pack"].assert_not_called()


@pytest.mark.asyncio
@sync_cases
async def test_sync_ref_update_rejected_other_reason_reports_and_raises(
    case, request, mock_gh, mock_gl, mock_repligit_ops
):
    """A RefUpdateRejected reason other than the hook-declined message should still
    fail the check for user visibility, but raise so Hubcast admins can debug."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["send_pack"].side_effect = RefUpdateRejected("non-fast-forward")

    with pytest.raises(RefUpdateRejected):
        await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    mock_gh.set_check_status.assert_awaited_once_with(
        case.sha,
        "hubcast",
        "failure",
        title=INTERNAL_ERROR_TITLE,
        summary=INTERNAL_ERROR_SUMMARY,
    )


@pytest.mark.asyncio
@sync_cases
async def test_sync_fetch_pack_failure_raises(
    case, request, mock_gh, mock_gl, mock_repligit_ops
):
    """A missing packfile should raise instead of pushing nothing."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["fetch_pack"].return_value = None

    with pytest.raises(HubcastError, match="Failed to fetch packfile"):
        await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")


@pytest.mark.asyncio
@sync_cases
@pytest.mark.parametrize(
    "failing_op,error",
    [
        ("ls_remote", permission_error(500)),
        ("send_pack", permission_error(500)),
        ("send_pack", Exception("connection reset")),
    ],
    ids=["ls_remote-http-500", "send_pack-http-500", "send_pack-generic"],
)
async def test_sync_other_error_raises(
    case, failing_op, error, request, mock_gh, mock_gl, mock_repligit_ops
):
    """Unrecognized repligit errors during sync should propagate."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops[failing_op].side_effect = error

    with pytest.raises(type(error)):
        await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")
    mock_gh.set_check_status.assert_not_called()


# Tests for remove_pr


@pytest.mark.asyncio
async def test_remove_pr_skip_delete_closed_false(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR branch removal should be skipped when delete_closed=False (PR 280)."""

    # Configure repo to NOT delete branches on PR close
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(delete_closed=False, dest_org="owner", dest_name="repo"),
        True,
    )

    await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Skipped PR branch removal - delete_closed disabled" in caplog.text


@pytest.mark.asyncio
async def test_remove_pr_skip_internal(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR branch removal should be skipped for internal branches."""

    # PR base and head are the same repo
    mock_pr_closed_event.data["pull_request"]["head"]["repo"]["full_name"] = (
        "owner/repo"
    )

    await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Skipped PR branch removal - internal branch" in caplog.text


@pytest.mark.asyncio
async def test_remote_pr_skip_no_ref(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR branch removal should be skipped if the ref cannot be found on the destination."""

    # ls_remote doesn't have the pr branch
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "some-sha"}

    await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Skipped PR branch removal - ref not found" in caplog.text


@pytest.mark.asyncio
async def test_remove_pr_deleted(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """PR branch removal should proceed if the ref exists."""

    # ls_remote has the pr branch
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/pr-123": "pr-sha-123",
    }

    await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Deleted PR branch" in caplog.text


# Shared error-handling tests for remove_branch and remove_pr


class RemoveCase(NamedTuple):
    """A removal handler plus the event fixture and expectations its error tests share."""

    handler: Callable
    event_fixture: str
    ref: str
    success_log: str


remove_cases = pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            RemoveCase(
                remove_branch,
                "mock_delete_event",
                "refs/heads/feature-branch",
                "Deleted branch",
            ),
            id="remove_branch",
        ),
        pytest.param(
            RemoveCase(
                remove_pr,
                "mock_pr_closed_event",
                "refs/heads/pr-123",
                "Deleted PR branch",
            ),
            id="remove_pr",
        ),
    ],
)


@pytest.mark.asyncio
@remove_cases
async def test_remove_ls_remote_permission_denied(
    case, request, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Permission errors on deletion should be logged; there is no sha to attach a check to."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["ls_remote"].side_effect = permission_error()

    await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert PERMISSION_DENIED_DELETE_LOG_MSG in caplog.text
    mock_gh.set_check_status.assert_not_called()
    mock_repligit_ops["send_pack"].assert_not_called()


@pytest.mark.asyncio
@remove_cases
@pytest.mark.parametrize(
    "error,expected_log",
    [
        (permission_error(), PERMISSION_DENIED_DELETE_LOG_MSG),
        (RefUpdateRejected(HOOK_DECLINED_MSG), HOOK_DECLINED_MSG),
    ],
    ids=["permission-denied", "hook-declined"],
)
async def test_remove_send_pack_swallowed_errors(
    case, error, expected_log, request, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Expected send_pack failures on deletion should be logged and not propagate."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["ls_remote"].return_value = {case.ref: "dest-sha-123"}
    mock_repligit_ops["send_pack"].side_effect = error

    await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")

    assert expected_log in caplog.text
    assert case.success_log not in caplog.text
    mock_gh.set_check_status.assert_not_called()


@pytest.mark.asyncio
@remove_cases
@pytest.mark.parametrize(
    "failing_op,error",
    [
        ("ls_remote", permission_error(500)),
        ("send_pack", permission_error(500)),
        ("send_pack", Exception("connection reset")),
        ("send_pack", RefUpdateRejected("non-fast-forward")),
    ],
    ids=[
        "ls_remote-http-500",
        "send_pack-http-500",
        "send_pack-generic",
        "send_pack-ref-rejected-other-reason",
    ],
)
async def test_remove_other_error_raises(
    case, failing_op, error, request, mock_gh, mock_gl, mock_repligit_ops
):
    """Unrecognized errors during deletion should propagate."""

    event = request.getfixturevalue(case.event_fixture)
    mock_repligit_ops["ls_remote"].return_value = {case.ref: "dest-sha-123"}
    mock_repligit_ops[failing_op].side_effect = error

    with pytest.raises(type(error)):
        await case.handler(event=event, gh=mock_gh, gl=mock_gl, gl_user="gl-user")


# Tests for respond_comment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,expected_log,is_pr",
    [
        ("@hubcast-bot help", "Help message sent", True),
        ("@hubcast-bot approve", "Approval reminder sent", True),
        ("random text", "Skipped comment - no command matched", True),
        (
            "@hubcast-bot help",
            "Skipped comment - not PR comment",
            False,
        ),  # issue comment
    ],
)
async def test_respond_comment_simple_commands(
    command,
    expected_log,
    is_pr,
    mock_comment_event,
    mock_repligit_ops,
    call_respond_comment,
    caplog,
):
    """Should handle simple commands (help, approve, unmatched) and non-PR comments."""
    if not is_pr:
        del mock_comment_event.data["issue"]["pull_request"]

    await call_respond_comment(command)

    assert expected_log in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,expected_log,needs_pr_setup",
    [
        (
            "@hubcast-bot approve",
            "Mirrored ref with approval from review comment",
            True,
        ),
        ("Looks good to me!", "Skipped PR review comment - no command matched", False),
        (None, "Skipped comment - no command matched", False),
    ],
)
async def test_respond_pr_comment_commands(
    command,
    expected_log,
    needs_pr_setup,
    mock_gh,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    call_respond_pr_comment,
    caplog,
):
    """Should handle PR review comments (approve or no command)."""
    if needs_pr_setup:
        mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
        mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    await call_respond_pr_comment(command)

    assert expected_log in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "@hubcast-bot rerun pipeline",
        "@hubcast-bot re-run pipeline",
        "@hubcast-bot restart pipeline",
        "@hubcast-bot re-start pipeline",
    ],
)
async def test_respond_comment_run_pipeline(
    command,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    caplog,
):
    """Should handle all variations of rerun/restart pipeline command."""
    mock_comment_event.data["comment"]["body"] = command
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.run_pipeline = AsyncMock(return_value="https://gitlab.com/pipeline/123")
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Pipeline started for branch" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_internal,expected_log,expected_branch",
    [
        (
            True,
            "Pipeline started for branch",
            "feature-branch",
        ),  # internal PR success
        (False, "Pipeline started for branch", "pr-123"),  # fork PR success
    ],
)
async def test_respond_comment_run_pipeline_variations(
    is_internal,
    expected_log,
    expected_branch,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_pr_data_for_comment,
    setup_pr_mocks,
    setup_pipeline_mocks,
    caplog,
):
    """Should handle pipeline start for internal/fork PRs and success/failure."""
    mock_comment_event.data["comment"]["body"] = "@hubcast-bot rerun pipeline"

    if is_internal:
        mock_pr_data_for_comment["head"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["base"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["head"]["ref"] = "feature-branch"

    setup_pr_mocks(mock_pr_data_for_comment)
    setup_pipeline_mocks()

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert expected_log in caplog.text
    assert any(
        hasattr(record, "branch") and record.branch == expected_branch
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "@hubcast-bot restart failed",
        "@hubcast-bot restart failed jobs",
        "@hubcast-bot restart failedjobs",
        "@hubcast-bot restart failed-jobs",
    ],
)
async def test_respond_comment_restart_jobs(
    command,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    caplog,
):
    """Should restart failed jobs."""

    mock_comment_event.data["comment"]["body"] = command
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
    mock_gl.retry_pipeline_jobs = AsyncMock(
        return_value="https://gitlab.com/pipeline/789"
    )

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Jobs restarted for branch" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_internal,pipeline_exists,expected_log,expected_branch",
    [
        (
            True,
            True,
            "Jobs restarted for branch",
            "feature-branch",
        ),  # internal success
        (False, True, "Jobs restarted for branch", "pr-123"),  # fork success
        (
            True,
            False,
            "No pipeline found for branch",
            "feature-branch",
        ),  # no pipeline
    ],
)
async def test_respond_comment_restart_jobs_variations(
    is_internal,
    pipeline_exists,
    expected_log,
    expected_branch,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_pr_data_for_comment,
    setup_pr_mocks,
    setup_pipeline_mocks,
    caplog,
):
    """Should handle restart jobs for various scenarios."""
    mock_comment_event.data["comment"]["body"] = "@hubcast-bot restart failed"

    if is_internal:
        mock_pr_data_for_comment["head"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["base"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["head"]["ref"] = "feature-branch"

    setup_pr_mocks(mock_pr_data_for_comment)
    setup_pipeline_mocks(pipeline_exists=pipeline_exists)

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert expected_log in caplog.text
    assert any(
        hasattr(record, "branch") and record.branch == expected_branch
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected_response,expected_log",
    [
        (
            BadRequest(HTTPStatus(403), "forbidden"),
            PERMISSION_DENIED_SUMMARY,
            "Pipeline failed to start - insufficient permissions",
        ),
        (
            BadRequest(HTTPStatus(403), DEACTIVATED_ACCOUNT_MARKER),
            DEACTIVATED_ACCOUNT_MSG,
            "Pipeline failed to start - insufficient permissions",
        ),
        (
            BadRequest(HTTPStatus(400), "invalid CI config"),
            PIPELINE_FAILED_MSG,
            "Pipeline failed to start",
        ),
    ],
)
async def test_respond_comment_run_pipeline_errors(
    error,
    expected_response,
    expected_log,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    caplog,
):
    """Pipeline start failures should be explained to the user in a comment."""

    mock_comment_event.data["comment"]["body"] = "@hubcast-bot rerun pipeline"
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.run_pipeline = AsyncMock(side_effect=error)

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert expected_log in caplog.text
    mock_gh.post_comment.assert_awaited_once()
    _, response = mock_gh.post_comment.await_args.args
    assert expected_response in response
    mock_gh.react_to_comment.assert_not_called()


@pytest.mark.asyncio
async def test_respond_comment_run_pipeline_other_error_raises(
    mock_comment_event, mock_gh, mock_gl, mock_repligit_ops, mock_pr_data_for_comment
):
    """Unrecognized pipeline start failures should propagate."""

    mock_comment_event.data["comment"]["body"] = "@hubcast-bot rerun pipeline"
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.run_pipeline = AsyncMock(side_effect=BadRequest(HTTPStatus(500), "oops"))

    with pytest.raises(BadRequest):
        await respond_comment(
            event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failing_call,expected_log",
    [
        ("get_latest_pipeline", "Pipeline ID fetch failed - insufficient permissions"),
        ("retry_pipeline_jobs", "Jobs restart failed - insufficient permissions"),
    ],
)
async def test_respond_comment_restart_jobs_permission_denied(
    failing_call,
    expected_log,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    caplog,
):
    """Permission errors restarting jobs should be explained to the user in a comment."""

    mock_comment_event.data["comment"]["body"] = "@hubcast-bot restart failed"
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
    getattr(mock_gl, failing_call).side_effect = BadRequest(
        HTTPStatus(403), "forbidden"
    )

    await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert expected_log in caplog.text
    mock_gh.post_comment.assert_awaited_once()
    _, response = mock_gh.post_comment.await_args.args
    assert PERMISSION_DENIED_SUMMARY in response
    mock_gh.react_to_comment.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_call", ["get_latest_pipeline", "retry_pipeline_jobs"])
async def test_respond_comment_restart_jobs_other_error_raises(
    failing_call,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
):
    """Unrecognized errors restarting jobs should propagate."""

    mock_comment_event.data["comment"]["body"] = "@hubcast-bot restart failed"
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
    getattr(mock_gl, failing_call).side_effect = BadRequest(HTTPStatus(500), "oops")

    with pytest.raises(BadRequest):
        await respond_comment(
            event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
        )


# Tests for rerun_check


@pytest.mark.asyncio
async def test_check_rerun_skip_old_commit(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Check rerun should be skipped if the latest commit on the branch does not equal the check run commit."""

    # the branch's latest commit is different from the check run's head_sha
    mock_gh.get_branch.return_value = {"commit": {"sha": "latest-sha-456"}}

    await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Skipped check rerun - old commit" in caplog.text


@pytest.mark.asyncio
async def test_check_rerun_requested(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Check rerun should be requested if all conditions are met."""

    # latest commit on the branch matches the check run head_sha
    mock_gh.get_branch.return_value = {"commit": {"sha": "check-run-sha-123"}}

    await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert "Rerun check requested for branch" in caplog.text


@pytest.mark.asyncio
async def test_rerun_check_config_error_sets_error_check(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops
):
    """An invalid repo config should be reported as a failed hubcast-error check."""

    mock_gh.get_branch.return_value = {"commit": {"sha": "check-run-sha-123"}}
    mock_repligit_ops["get_repo_config"].side_effect = repo_config_error()

    await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    mock_gh.set_check_status.assert_awaited_once_with(
        "check-run-sha-123",
        ERROR_CHECK_NAME,
        "failure",
        title="config title",
        summary="config summary",
    )
    mock_gl.run_pipeline.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected_title,expected_summary",
    [
        (
            BadRequest(HTTPStatus(403), "forbidden"),
            PERMISSION_DENIED_TITLE,
            PERMISSION_DENIED_SUMMARY,
        ),
        (
            BadRequest(HTTPStatus(403), DEACTIVATED_ACCOUNT_MARKER),
            DEACTIVATED_ACCOUNT_MSG,
            "",
        ),
        (
            BadRequest(HTTPStatus(400), "invalid CI config"),
            PIPELINE_FAILED_MSG,
            "invalid CI config",
        ),
    ],
)
async def test_rerun_check_pipeline_errors(
    error,
    expected_title,
    expected_summary,
    mock_check_run_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
):
    """Pipeline start failures during a check rerun should fail the check with details."""

    mock_gh.get_branch.return_value = {"commit": {"sha": "check-run-sha-123"}}
    mock_gl.run_pipeline = AsyncMock(side_effect=error)

    await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    mock_gh.set_check_status.assert_awaited_once_with(
        "check-run-sha-123",
        "hubcast",
        "failure",
        title=expected_title,
        summary=expected_summary,
    )


@pytest.mark.asyncio
async def test_rerun_check_pipeline_other_error_raises(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Unrecognized pipeline start failures should propagate."""

    mock_gh.get_branch.return_value = {"commit": {"sha": "check-run-sha-123"}}
    mock_gl.run_pipeline = AsyncMock(side_effect=BadRequest(HTTPStatus(500), "oops"))

    with pytest.raises(BadRequest):
        await rerun_check(
            event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
        )
