# tests for Hubcast's GitHub route handlers

from unittest.mock import AsyncMock, Mock, patch

import pytest
from gidgethub import sansio

from hubcast.exceptions import HubcastError
from hubcast.web.github.routes import (
    remove_branch,
    remove_pr,
    rerun_check,
    respond_comment,
    respond_pr_comment,
    router,
    sync_branch,
    sync_pr_event,
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
        "head_commit": {"id": "sha-123"},
        "ref": "refs/heads/main",
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

    def _setup(run_success=True, pipeline_exists=True, retry_success=True):
        if run_success:
            mock_gl.run_pipeline = AsyncMock(
                return_value="https://gitlab.com/pipeline/123"
            )
        else:
            mock_gl.run_pipeline = AsyncMock(return_value=None)

        if pipeline_exists:
            mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
            if retry_success:
                mock_gl.retry_pipeline_jobs = AsyncMock(
                    return_value="https://gitlab.com/pipeline/789"
                )
            else:
                mock_gl.retry_pipeline_jobs = AsyncMock(return_value=None)
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
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Branches should not be synced if there is an open PR for the branch."""

    # mocking hubcast.clients.github.client.GitHubClient.get_prs
    mock_gh.get_prs.return_value = [123]  # Simulate an open PR exists

    result = await sync_branch(
        event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "branch_has_open_pr"


@pytest.mark.asyncio
async def test_sync_branch_skip_up_to_date(
    mock_push_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Branches should not be synced if already up to date."""

    # no open PRs for the branch
    mock_gh.get_prs.return_value = []

    # mock ls_remote returning refs that already contain the want_sha
    # (the destination forge already has the commit)
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/main": "sha-123",  # Same as event's head_commit.id
    }

    result = await sync_branch(
        event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "up_to_date"


@pytest.mark.asyncio
async def test_sync_branch_synced(mock_push_event, mock_gh, mock_gl, mock_repligit_ops):
    """Branches should sync if all conditions are met."""

    # no open PRs for the branch
    mock_gh.get_prs.return_value = []

    # mock ls_remote returning refs that do NOT contain the want_sha
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha-456"}

    result = await sync_branch(
        event=mock_push_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"


# Tests for remove_branch


@pytest.mark.asyncio
async def test_remove_branch_skip_no_ref(
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branch removal should be skipped if the ref cannot be found on the destination."""

    # ls_remote returns some other refs, not the one being deleted
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "some-sha"}

    with caplog.at_level("INFO", logger="hubcast.web.github.routes"):
        await remove_branch(
            event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
        )

    record = caplog.records[-1]
    assert record.action == "skipped"
    assert record.reason == "ref_not_found"


@pytest.mark.asyncio
async def test_remove_branch_deleted(
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops, caplog
):
    """Branch removal should proceed if the ref exists."""

    # ls_remote has the ref we want to delete
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/feature-branch": "branch-sha-123",
    }

    with caplog.at_level("INFO", logger="hubcast.web.github.routes"):
        await remove_branch(
            event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
        )

    record = caplog.records[-1]
    assert record.action == "deleted"


# Tests for sync_pr_event


@pytest.mark.asyncio
async def test_sync_pr_skip_private_fork(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR sync should be skipped for private forks."""

    mock_pr_event.data["pull_request"]["head"]["repo"]["private"] = True

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "private_fork"


@pytest.mark.asyncio
async def test_sync_pr_skip_draft(mock_pr_event, mock_gh, mock_gl, mock_repligit_ops):
    """PR sync should be skipped for draft PRs (when sync_drafts is False)."""

    mock_pr_event.data["pull_request"]["draft"] = True
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(sync_drafts=False, dest_org="owner", dest_name="repo"),
        True,
    )

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "draft_pr"


@pytest.mark.asyncio
async def test_sync_pr_skip_up_to_date(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR sync should be skipped if already up to date."""

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/pr-123": "pr-sha-123"}

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )
    assert result["action"] == "skipped"
    assert result["reason"] == "up_to_date"


@pytest.mark.asyncio
async def test_sync_pr_synced_fork(mock_pr_event, mock_gh, mock_gl, mock_repligit_ops):
    """PR sync should proceed if all conditions are met (from fork)."""

    # ls_remote does not have the PR branch sha
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"


@pytest.mark.asyncio
async def test_sync_pr_synced_internal(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR sync should proceed if all conditions are met (internal branch)."""

    # make head and base the same repo to simulate internal branch
    mock_pr_event.data["pull_request"]["head"]["repo"]["full_name"] = "owner/repo"
    mock_pr_event.data["pull_request"]["base"]["repo"]["full_name"] = "owner/repo"

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"


@pytest.mark.asyncio
async def test_sync_pr_opened_uses_head_sha(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR opened event should use head sha instead of after field."""

    # Change action to "opened" instead of "synchronize"
    mock_pr_event.data["action"] = "opened"
    mock_pr_event.data["pull_request"]["head"]["sha"] = "head-sha-456"

    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"
    assert result["sha"] == "head-sha-456"


@pytest.mark.asyncio
async def test_sync_pr_creates_mr_when_configured(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
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

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"
    assert result["mr_created"] is True
    mock_gl.create_mr.assert_called_once()


@pytest.mark.asyncio
async def test_sync_pr_skips_mr_when_already_exists(
    mock_pr_event, mock_gh, mock_gl, mock_repligit_ops
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

    result = await sync_pr_event(
        event=mock_pr_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "synced"
    assert "mr_created" not in result
    mock_gl.create_mr.assert_not_called()


# Tests for remove_pr


@pytest.mark.asyncio
async def test_remove_pr_skip_delete_closed_false(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR branch removal should be skipped when delete_closed=False (PR 280)."""

    # Configure repo to NOT delete branches on PR close
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(delete_closed=False, dest_org="owner", dest_name="repo"),
        True,
    )

    result = await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "delete_closed_disabled"


@pytest.mark.asyncio
async def test_remove_pr_skip_internal(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR branch removal should be skipped for internal branches."""

    # PR base and head are the same repo
    mock_pr_closed_event.data["pull_request"]["head"]["repo"]["full_name"] = (
        "owner/repo"
    )

    result = await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "internal_branch"


@pytest.mark.asyncio
async def test_remote_pr_skip_no_ref(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR branch removal should be skipped if the ref cannot be found on the destination."""

    # ls_remote doesn't have the pr branch
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "some-sha"}

    result = await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "ref_not_found"


@pytest.mark.asyncio
async def test_remove_pr_deleted(
    mock_pr_closed_event, mock_gh, mock_gl, mock_repligit_ops
):
    """PR branch removal should proceed if the ref exists."""

    # ls_remote has the pr branch
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/pr-123": "pr-sha-123",
    }

    result = await remove_pr(
        event=mock_pr_closed_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "deleted"


# Tests for respond_comment


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,expected_action,expected_reason,is_pr",
    [
        ("@hubcast-bot help", "help_sent", None, True),
        ("@hubcast-bot approve", "approval_reminder_sent", None, True),
        ("random text", "skipped", "no_command_matched", True),
        ("@hubcast-bot help", "skipped", "not_pr_comment", False),  # issue comment
    ],
)
async def test_respond_comment_simple_commands(
    command,
    expected_action,
    expected_reason,
    is_pr,
    mock_comment_event,
    mock_repligit_ops,
    call_respond_comment,
):
    """Should handle simple commands (help, approve, unmatched) and non-PR comments."""
    if not is_pr:
        del mock_comment_event.data["issue"]["pull_request"]

    result = await call_respond_comment(command)

    assert result["action"] == expected_action
    if expected_reason:
        assert result["reason"] == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command,expected_action,expected_reason,needs_pr_setup",
    [
        ("@hubcast-bot approve", "approve_sent", None, True),
        ("Looks good to me!", "skipped", "no_command_matched", False),
    ],
)
async def test_respond_pr_comment_commands(
    command,
    expected_action,
    expected_reason,
    needs_pr_setup,
    mock_gh,
    mock_repligit_ops,
    mock_pr_data_for_comment,
    call_respond_pr_comment,
):
    """Should handle PR review comments (approve or no command)."""
    if needs_pr_setup:
        mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
        mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await call_respond_pr_comment(command)

    assert result["action"] == expected_action
    if expected_reason:
        assert result["reason"] == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "command",
    [
        "@hubcast-bot run pipeline",
        "@hubcast-bot start pipeline",
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
):
    """Should handle all variations of run/start pipeline command."""
    mock_comment_event.data["comment"]["body"] = command
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.run_pipeline = AsyncMock(return_value="https://gitlab.com/pipeline/123")
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "pipeline_started"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_internal,run_success,expected_action,expected_branch",
    [
        (True, True, "pipeline_started", "feature-branch"),  # internal PR success
        (False, True, "pipeline_started", "pr-123"),  # fork PR success
        (True, False, "pipeline_failed", "feature-branch"),  # internal PR failed
    ],
)
async def test_respond_comment_run_pipeline_variations(
    is_internal,
    run_success,
    expected_action,
    expected_branch,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_pr_data_for_comment,
    setup_pr_mocks,
    setup_pipeline_mocks,
):
    """Should handle pipeline start for internal/fork PRs and success/failure."""
    mock_comment_event.data["comment"]["body"] = "@hubcast-bot run pipeline"

    if is_internal:
        mock_pr_data_for_comment["head"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["base"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["head"]["ref"] = "feature-branch"

    setup_pr_mocks(mock_pr_data_for_comment)
    setup_pipeline_mocks(run_success=run_success)

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == expected_action
    assert result["branch"] == expected_branch


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
):
    """Should restart failed jobs."""

    mock_comment_event.data["comment"]["body"] = command
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)
    mock_gl.get_latest_pipeline = AsyncMock(return_value=789)
    mock_gl.retry_pipeline_jobs = AsyncMock(
        return_value="https://gitlab.com/pipeline/789"
    )

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "jobs_restarted"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "is_internal,pipeline_exists,retry_success,expected_action,expected_branch",
    [
        (True, True, True, "jobs_restarted", "feature-branch"),  # internal success
        (False, True, True, "jobs_restarted", "pr-123"),  # fork success
        (True, True, False, "jobs_restart_failed", "feature-branch"),  # retry failed
        (True, False, False, "no_pipeline", "feature-branch"),  # no pipeline
    ],
)
async def test_respond_comment_restart_jobs_variations(
    is_internal,
    pipeline_exists,
    retry_success,
    expected_action,
    expected_branch,
    mock_comment_event,
    mock_gh,
    mock_gl,
    mock_pr_data_for_comment,
    setup_pr_mocks,
    setup_pipeline_mocks,
):
    """Should handle restart jobs for various scenarios."""
    mock_comment_event.data["comment"]["body"] = "@hubcast-bot restart failed"

    if is_internal:
        mock_pr_data_for_comment["head"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["base"]["repo"]["full_name"] = "owner/repo"
        mock_pr_data_for_comment["head"]["ref"] = "feature-branch"

    setup_pr_mocks(mock_pr_data_for_comment)
    setup_pipeline_mocks(pipeline_exists=pipeline_exists, retry_success=retry_success)

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == expected_action
    assert result["branch"] == expected_branch


# Tests for rerun_check


@pytest.mark.asyncio
async def test_check_rerun_skip_old_commit(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Check rerun should be skipped if the latest commit on the branch does not equal the check run commit."""

    # the branch's latest commit is different from the check run's head_sha
    mock_gh.get_branch.return_value = {"commit": {"sha": "latest-sha-456"}}

    result = await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"


@pytest.mark.asyncio
async def test_check_rerun_requested(
    mock_check_run_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Check rerun should be requested if all conditions are met."""

    # latest commit on the branch matches the check run head_sha
    mock_gh.get_branch.return_value = {"commit": {"sha": "check-run-sha-123"}}

    result = await rerun_check(
        event=mock_check_run_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "rerun_requested"
