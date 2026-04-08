# tests for Hubcast's GitHub route handlers

from unittest.mock import AsyncMock, Mock, patch

import pytest

from hubcast.web.github.routes import (
    remove_branch,
    remove_pr,
    rerun_check,
    respond_comment,
    respond_pr_comment,
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
            draft_sync=True,
            draft_sync_msg=True,
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


### UNIT TESTS

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
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Branch removal should be skipped if the ref cannot be found on the destination."""

    # ls_remote returns some other refs, not the one being deleted
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "some-sha"}

    result = await remove_branch(
        event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "ref_not_found"


@pytest.mark.asyncio
async def test_remove_branch_deleted(
    mock_delete_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Branch removal should proceed if the ref exists."""

    # ls_remote has the ref we want to delete
    mock_repligit_ops["ls_remote"].return_value = {
        "refs/heads/feature-branch": "branch-sha-123",
    }

    result = await remove_branch(
        event=mock_delete_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "deleted"


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
    """PR sync should be skipped for draft PRs (when draft_sync is False)."""

    mock_pr_event.data["pull_request"]["draft"] = True
    mock_repligit_ops["get_repo_config"].return_value = (
        Mock(draft_sync=False, dest_org="owner", dest_name="repo"),
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


# Tests for remove_pr


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
async def test_respond_comment_skip_non_pr_comments(
    mock_comment_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Skip commenting on issues (not PRs)."""
    del mock_comment_event.data["issue"]["pull_request"]

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "skipped"
    assert result["reason"] == "not_pr_comment"


@pytest.mark.asyncio
async def test_respond_comment_help(
    mock_comment_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Should respond with help message when @bot help is mentioned."""
    mock_comment_event.data["comment"]["body"] = "@hubcast-bot help"

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "help_sent"


@pytest.mark.asyncio
async def test_respond_comment_approve(
    mock_review_event,
    mock_gh,
    mock_gl,
    mock_repligit_ops,
    mock_pr_data_for_comment,
):
    """Should sync PR when @bot approve is mentioned."""
    mock_gh.get_pr = AsyncMock(return_value=mock_pr_data_for_comment)

    # old sha to simulate out-of-date destination
    mock_repligit_ops["ls_remote"].return_value = {"refs/heads/main": "old-sha"}

    result = await respond_pr_comment(
        event=mock_review_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result["action"] == "approve_sent"


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
async def test_respond_comment_ignores_unmatched_commands(
    mock_comment_event, mock_gh, mock_gl, mock_repligit_ops
):
    """Should return None when comment doesn't match any command."""

    mock_comment_event.data["comment"]["body"] = "hi"

    result = await respond_comment(
        event=mock_comment_event, gh=mock_gh, gl=mock_gl, gl_user="gl-user"
    )

    assert result is None


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
