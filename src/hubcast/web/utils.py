import logging
from collections.abc import Awaitable, Callable, Collection
from typing import Any

import yaml
import yaml.reader
from aiohttp.client_exceptions import ClientResponseError
from gidgetlab.exceptions import BadRequest
from pydantic import ValidationError
from repligit.asyncio import fetch_pack, ls_remote, send_pack
from repligit.exceptions import RefUpdateRejected

from hubcast.clients.github import GitHubClient
from hubcast.clients.gitlab import GitLabDestClient, GitLabSrcClient
from hubcast.exceptions import HubcastError, RepoConfigError
from hubcast.logging import update_log_context
from hubcast.repos.config import RepoConfig
from hubcast.web.messages import (
    CONFIG_INVALID_SUMMARY,
    CONFIG_INVALID_TITLE,
    CONFIG_VALID_SUMMARY,
    CONFIG_VALID_TITLE,
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
)

log = logging.getLogger(__name__)

# statuses returned by GitLab when a token/user lacks sufficient permissions
# on the destination repository
PERMISSION_DENIED_STATUSES = (401, 403)

# check name used to report errors about repo config or webhooks
# this avoids overwriting errors if a normal pipeline succeeds, and provides
# a default for situations where there is no default check name set
# this check won't linger because resolving issues requires a new commit to be pushed
ERROR_CHECK_NAME = "hubcast-config"

NULL_SHA = "0" * 40


def is_deactivated_account(exc: BadRequest) -> bool:
    """Whether a GitLab permission-denied error was caused by a deactivated account."""
    return DEACTIVATED_ACCOUNT_MARKER in str(exc)


def permission_denied_response(exc: BadRequest) -> str:
    """User-facing message for a GitLab permission-denied error from a comment command."""
    if is_deactivated_account(exc):
        return DEACTIVATED_ACCOUNT_MSG
    return PERMISSION_DENIED_SUMMARY


def changed_files_from_push(payload: dict[str, Any]) -> set[str]:
    """Collect all file paths touched by the commits in a push payload."""
    return {
        f
        for c in payload["commits"]
        for key in ("added", "modified", "removed")
        for f in c.get(key, ())
    }


def _format_yaml_error(exc: yaml.YAMLError) -> str:
    """Render YAML parse errors with bullet points rather than pyyaml's default mess."""
    if isinstance(exc, yaml.reader.ReaderError):
        # encoding/control-character issues
        return f"- {exc.reason} (position {exc.position})"

    if not isinstance(exc, yaml.MarkedYAMLError):
        # the only other error safe_load raises (needed to resolve type issues)
        raise TypeError(f"Unexpected YAML error type: {type(exc)!r}")

    problem = f"{exc.context}; {exc.problem}" if exc.context else exc.problem
    mark = exc.problem_mark
    line = (
        f"- {problem} (line {mark.line + 1}, column {mark.column + 1})"
        if mark
        else f"- {problem}"
    )

    snippet = mark.get_snippet() if mark else None
    return f"{line}\n\n```\n{snippet}\n```" if snippet else line


def _format_validation_error(exc: ValidationError) -> str:
    """Render pydantic validation errors as a per-field bullet list."""
    lines = []
    for err in exc.errors(include_url=False, include_input=False):
        loc = ".".join(str(p) for p in err["loc"])
        # pydantic prefixes messages from raised errors
        msg = err["msg"].removeprefix("Value error, ")
        lines.append(f"- `{loc}`: {msg}" if loc else f"- {msg}")
    return "\n".join(lines)


def parse_repo_config(raw_config: str) -> RepoConfig:
    """Parse YAML as a RepoConfig.

    Raises RepoConfigError for invalid YAML or schema validation issues.
    """
    try:
        config_yaml = yaml.safe_load(raw_config)
    except yaml.YAMLError as e:
        raise RepoConfigError(
            "Invalid YAML in repo config",
            title=CONFIG_INVALID_TITLE,
            summary=f"{CONFIG_INVALID_SUMMARY}\n\n---\n\n{_format_yaml_error(e)}",
            error=str(e),
        )

    try:
        return RepoConfig.model_validate(config_yaml)
    except ValidationError as e:
        raise RepoConfigError(
            "Invalid repo config",
            title=CONFIG_INVALID_TITLE,
            summary=f"{CONFIG_INVALID_SUMMARY}\n\n---\n\n{_format_validation_error(e)}",
            error=str(e),
        )


async def get_repo_config(src_client: GitHubClient | GitLabSrcClient) -> RepoConfig:
    """Fetch and validate the repository configuration from the source forge.

    Args:
        src_client: GitHub or GitLab source client instance

    Returns:
        RepoConfig instance

    Raises:
        HubcastError: If config file contains invalid YAML, is missing required keys,
            or has validation errors
    """
    fetched_config = await src_client.get_repo_config()

    if fetched_config is None:  # 404
        # raise so route handlers can't continue
        # we don't want to raise this as a RepoConfigError because telling users
        # about the absence of the config will create noise and confusion as
        # they may have installed the app but have not submitted a config file yet
        raise HubcastError("Repo config file not found", log_level="INFO")

    # parse and validate YAML
    config = parse_repo_config(fetched_config)

    log.info("Repo config fetched from source forge")
    return config


async def report_config_error(
    src_client: GitHubClient | GitLabSrcClient,
    sha: str,
    exc: RepoConfigError,
) -> None:
    """Report a missing/invalid repo config to the user as a failed check/status."""
    exc.log(log)
    await src_client.set_check_status(
        sha,
        ERROR_CHECK_NAME,
        src_client.FAILURE_STATUS,
        title=exc.title,
        summary=exc.summary,
    )


async def validate_config_change(
    src_client: GitHubClient | GitLabSrcClient,
    changed_files: Collection[str],
    head_sha: str,
) -> None:
    """
    Validate the Hubcast repo config at head_sha if changed_files touches it,
    reporting feedback via a check/status on the source forge.

    This is meant to supersede previously reported config errors on the default branch.
    """
    if src_client.repo_config_path not in changed_files:
        return

    # config was deleted in this change
    config = await src_client.get_repo_config(ref=head_sha)
    if config is None:
        return

    try:
        parse_repo_config(config)
    except RepoConfigError as exc:
        exc.log(log)
        await src_client.set_check_status(
            head_sha,
            ERROR_CHECK_NAME,
            src_client.FAILURE_STATUS,
            title=exc.title,
            summary=exc.summary,
        )
        return

    # report success if validation passes for the change's config
    await src_client.set_check_status(
        head_sha,
        ERROR_CHECK_NAME,
        src_client.SUCCESS_STATUS,
        title=CONFIG_VALID_TITLE,
        summary=CONFIG_VALID_SUMMARY,
    )


async def _sync_ref(
    src_client: GitHubClient | GitLabSrcClient,
    gl: GitLabDestClient,
    gl_user: str,
    dest_remote_url: str,
    sync_ref: str,
    want_sha: str,
    src_repo_url: str,
    # auth rules differ by caller, which needs to provide its own closure
    get_src_creds: Callable[[], Awaitable[dict[str, str]]],
    check_name: str,
    entity: str,
) -> bool:
    """Sync `sync_ref` on the destination to `want_sha`, fetching from `src_repo_url`.
    Permission issues and Repligit errors are logged and reported to the source
    forge as a failed check/status on `src_client`.

    Returns True in a success state (up-to-date or sync performed), otherwise False.
    """

    async def report_failure(title: str, summary: str) -> None:
        await src_client.set_check_status(
            want_sha,
            check_name,
            src_client.FAILURE_STATUS,
            title=title,
            summary=summary,
        )

    gl_token = await gl.auth.authenticate_user(gl_user)

    try:
        gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    except ClientResponseError as exc:
        if exc.status not in PERMISSION_DENIED_STATUSES:
            raise
        log.info(PERMISSION_DENIED_SYNC_LOG_MSG)
        await report_failure(PERMISSION_DENIED_TITLE, PERMISSION_DENIED_SUMMARY)
        return False

    have_shas = set(gl_refs.values())
    from_sha = gl_refs.get(sync_ref) or NULL_SHA
    update_log_context(from_sha=from_sha, want_sha=want_sha)

    # directly check from_sha equals want_sha for cases where the sha has
    # already been mirrored but the ref is out-of-date. This is commonly the
    # case for tags that are created against an existing commit on a branch.
    if from_sha == want_sha:
        log.info(f"Skipped {entity} sync - already up-to-date")
        return True

    # each caller has different rules for fetching the packfile from src_repo_url
    src_creds = await get_src_creds()
    packfile = await fetch_pack(src_repo_url, want_sha, have_shas, **src_creds)
    if packfile is None:
        raise HubcastError(
            f"Failed to fetch packfile for {want_sha} from {src_repo_url}"
        )

    log.info(f"Syncing {entity}")
    try:
        await send_pack(
            dest_remote_url,
            sync_ref,
            from_sha,
            want_sha,
            packfile,
            username=gl_user,
            password=gl_token,
        )
    except ClientResponseError as exc:
        if exc.status not in PERMISSION_DENIED_STATUSES:
            raise
        log.info(PERMISSION_DENIED_SYNC_LOG_MSG)
        await report_failure(PERMISSION_DENIED_TITLE, PERMISSION_DENIED_SUMMARY)
        return False
    # repligit
    except RefUpdateRejected as exc:
        hook_declined = str(exc) == HOOK_DECLINED_MSG
        await report_failure(
            HOOK_DECLINED_TITLE if hook_declined else INTERNAL_ERROR_TITLE,
            HOOK_DECLINED_SUMMARY if hook_declined else INTERNAL_ERROR_SUMMARY,
        )
        if not hook_declined:
            raise
        return False

    log.info(f"Synced {entity}")
    return True


async def _delete_ref(
    gl: GitLabDestClient,
    gl_user: str,
    dest_remote_url: str,
    sync_ref: str,
    entity: str,
) -> None:
    """Delete `sync_ref` from the destination, if it exists."""
    gl_token = await gl.auth.authenticate_user(gl_user)

    try:
        gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    except ClientResponseError as exc:
        if exc.status not in PERMISSION_DENIED_STATUSES:
            raise
        # we cannot set source forge status for deleted refs, and we have no way to notify the user of this failure
        log.info(PERMISSION_DENIED_DELETE_LOG_MSG)
        return

    head_sha = gl_refs.get(sync_ref)
    update_log_context(head_sha=head_sha)

    if head_sha is None:
        log.info(f"Skipped {entity} removal - ref not found")
        return

    log.info(f"Deleting {entity}")

    try:
        await send_pack(
            dest_remote_url,
            sync_ref,
            head_sha,
            NULL_SHA,
            b"",
            username=gl_user,
            password=gl_token,
        )
    except ClientResponseError as exc:
        if exc.status not in PERMISSION_DENIED_STATUSES:
            raise
        log.info(PERMISSION_DENIED_DELETE_LOG_MSG)
        return
    # repligit
    except RefUpdateRejected as exc:
        if str(exc) != HOOK_DECLINED_MSG:
            # raise unknown ref update rejected errors for later debugging
            raise
        log.info(str(exc))
        return

    log.info(f"Deleted {entity}")
