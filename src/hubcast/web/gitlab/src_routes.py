import logging
import re
from typing import Any

from gidgetlab import sansio
from gidgetlab.exceptions import BadRequest

from hubcast.clients.gitlab.client import GitLabDestClient, GitLabSrcClient
from hubcast.exceptions import HubcastError, RepoConfigError, WebhookPermissionError
from hubcast.logging import update_log_context
from hubcast.web.gitlab.messages import help_message
from hubcast.web.gitlab.routes import GitLabRouter
from hubcast.web.messages import (
    INTERNAL_ERROR_SUMMARY,
    INTERNAL_ERROR_TITLE,
    PIPELINE_FAILED_MSG,
    WEBHOOK_PERMISSION_DENIED_SUMMARY,
    WEBHOOK_PERMISSION_DENIED_TITLE,
)
from hubcast.web.utils import (
    ERROR_CHECK_NAME,
    NULL_SHA,
    PERMISSION_DENIED_STATUSES,
    _delete_ref,
    _sync_ref,
    changed_files_from_push,
    get_repo_config,
    permission_denied_response,
    report_config_error,
    validate_config_change,
)
from hubcast.webhook import GitLabRoutingToken

log = logging.getLogger(__name__)

router = GitLabRouter()


async def remove_ref(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    entity: str,
) -> None:
    """Delete a git branch or tag from the destination."""
    sync_ref = event.data["ref"]

    update_log_context(ref=sync_ref)

    repo_config = await get_repo_config(gl_src)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl_dest.instance_url}/{dest_fullname}.git"

    await _delete_ref(gl_dest, dest_user, dest_remote_url, sync_ref, entity=entity)


# -----------------------------------
# Push Events
# -----------------------------------
@router.register("Push Hook")
async def sync_branch(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *args,
    **kwargs,
) -> None:
    """Sync a git branch to the destination."""

    # a push to the null SHA signals deletion
    if event.data["after"] == NULL_SHA:
        await remove_ref(event, gl_src, gl_dest, dest_user, entity="branch")
        return

    src_repo_url = event.data["repository"]["git_http_url"]
    src_repo_id = event.data["project"]["id"]
    # "after" represents the new HEAD of the ref
    want_sha = event.data["after"]
    sync_ref = event.data["ref"]

    update_log_context(ref=sync_ref)

    src_user = gl_src.requester
    src_password = await gl_src.auth.authenticate_user(gl_src.requester)

    # skip branch pushes that are actually the underlying ref of an open merge
    # request -- sync_mr_event handles those, to avoid syncing/racing on the
    # same ref twice
    branch_name = sync_ref.removeprefix("refs/heads/")
    if await gl_src.get_mrs(branch_name):
        log.info("Skipped branch sync - branch has open MR")
        return

    default_branch = event.data["project"]["default_branch"]
    is_default_branch = sync_ref == f"refs/heads/{default_branch}"
    changed_files = changed_files_from_push(event.data)
    config_changed = gl_src.repo_config_path in changed_files

    try:
        repo_config = await get_repo_config(gl_src)
    except RepoConfigError as exc:
        # only report the default branch config's error when this push isn't trying to fix it
        if is_default_branch or not config_changed:
            await report_config_error(gl_src, want_sha, exc)
        # if the config has changes and not on default branch, validate the new config
        if not is_default_branch:
            await validate_config_change(gl_src, changed_files, want_sha)
        return

    # validate the changes when the default branch config doesn't have issues
    if not is_default_branch:
        await validate_config_change(gl_src, changed_files, want_sha)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl_dest.instance_url}/{dest_fullname}.git"

    # commits are listed oldest-to-newest; the last one is the push's HEAD
    commits = event.data.get("commits") or []
    commit_msg = commits[-1]["message"] if commits else ""

    # only set/update the webhook on default branch pushes that touch the config
    # file (avoids spurious permission errors on unrelated pushes); maintainers
    # can also force it by including [hubcast config] in the commit message
    if is_default_branch and (config_changed or "[hubcast config]" in commit_msg):
        routing_token = GitLabRoutingToken(
            gl_repo_id=src_repo_id,
            gl_check=repo_config.check_name,
            check_types=repo_config.check_types,
        )
        try:
            await gl_dest.set_webhook(
                dest_org=repo_config.dest_org,
                dest_repo=repo_config.dest_name,
                routing_token=routing_token,
            )
        except WebhookPermissionError as exc:
            # the user is not a maintainer and we need to tell them to push config changes with higher permissions
            exc.log(log)
            await gl_src.set_check_status(
                want_sha,
                ERROR_CHECK_NAME,
                gl_src.FAILURE_STATUS,
                title=WEBHOOK_PERMISSION_DENIED_TITLE,
                summary=WEBHOOK_PERMISSION_DENIED_SUMMARY,
            )
            return
        except HubcastError as exc:
            # log for the hubcast admin and tell the user it's not their fault
            exc.log(log)
            await gl_src.set_check_status(
                want_sha,
                ERROR_CHECK_NAME,
                gl_src.FAILURE_STATUS,
                title=INTERNAL_ERROR_TITLE,
                summary=INTERNAL_ERROR_SUMMARY,
            )
            return
        else:
            log.info("Updated GitLab webhook", extra={"dest_fullname": dest_fullname})

    async def get_src_creds() -> dict[str, str]:
        # push events can only come via the source repo, so the bot account can
        # always authenticate
        return {"username": src_user, "password": src_password}

    await _sync_ref(
        gl_src,
        gl_dest,
        dest_user,
        dest_remote_url,
        sync_ref,
        want_sha,
        src_repo_url,
        get_src_creds,
        check_name=repo_config.check_name,
        entity="branch",
    )


# -----------------------------------
# Merge Request Events
# -----------------------------------


def _mr_branch_info(mr: dict[str, Any]) -> tuple[bool, str]:
    """Parses info from an MR to shape a Hubcast-usable branch name and whether the MR is from a fork."""
    is_from_fork = mr["source"]["id"] != mr["target"]["id"]
    dest_branch_name = f"mr-{mr['iid']}" if is_from_fork else mr["source_branch"]
    return is_from_fork, dest_branch_name


async def sync_mr(
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *,
    merge_request_id: int,
    target_fullname: str,
    src_fullname: str,
    src_repo_url: str,
    dest_branch_name: str,
    is_from_fork: bool,
    private_src_repo: bool,
    is_draft: bool,
    want_sha: str,
    mr_title: str,
    mr_url: str,
    dest_default_branch: str,
) -> bool:
    """Sync the git fork/branch referenced in a merge request to the destination.

    This isn't technically an event handler, but is used a couple different ways in this file.

    Returns True if the MR was actually synced, False if the sync was skipped.
    """
    sync_ref = f"refs/heads/{dest_branch_name}"
    update_log_context(ref=sync_ref)

    if is_from_fork and private_src_repo:
        # hubcast's bot account has no access to private forks
        log.warning(
            "Skipped MR sync - private fork",
            extra={
                "target_fullname": target_fullname,
                "mr_id": merge_request_id,
                "fork_fullname": src_fullname,
            },
        )
        return False

    changed_files = await gl_src.get_mr_files(merge_request_id)
    config_changed = gl_src.repo_config_path in changed_files

    try:
        repo_config = await get_repo_config(gl_src)
    except RepoConfigError as exc:
        # only report the default branch config's error when this MR isn't trying to fix it
        if not config_changed:
            await report_config_error(gl_src, want_sha, exc)
        await validate_config_change(gl_src, changed_files, want_sha)
        return False

    # validate the changes when the default branch config doesn't have issues
    await validate_config_change(gl_src, changed_files, want_sha)

    if not repo_config.sync_drafts and is_draft:
        if repo_config.sync_drafts_msg:
            await gl_src.set_check_status(
                want_sha,
                repo_config.check_name,
                "skipped",
                title="Hubcast disables sync for draft MRs.",
            )
        log.info("Skipped MR sync - draft MR")
        return False

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl_dest.instance_url}/{dest_fullname}.git"

    async def get_src_creds() -> dict[str, str]:
        if is_from_fork and not private_src_repo:
            # no auth needed for public forks
            return {}
        return {
            "username": gl_src.requester,
            "password": await gl_src.auth.authenticate_user(gl_src.requester),
        }

    synced = await _sync_ref(
        gl_src,
        gl_dest,
        dest_user,
        dest_remote_url,
        sync_ref,
        want_sha,
        src_repo_url,
        get_src_creds,
        check_name=repo_config.check_name,
        entity="MR",
    )

    # sync failed (logged in _sync_ref)
    if not synced:
        return False

    # create MRs if configured
    # skip already created MRs
    if repo_config.create_mr and not await gl_dest.get_mr(
        dest_fullname, dest_branch_name, dest_default_branch
    ):
        # user must have at least developer role to reach this point so we don't need to do a permissions check
        await gl_dest.create_mr(
            gl_fullname=dest_fullname,
            src_branch=dest_branch_name,
            target_branch=dest_default_branch,
            ref_title=mr_title,
            ref_url=mr_url,
        )
        log.info("Created MR", extra={"branch": dest_branch_name})

    return True


@router.register("Merge Request Hook", action="open")
@router.register("Merge Request Hook", action="reopen")
@router.register("Merge Request Hook", action="update")
async def sync_mr_event(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *args,
    **kwargs,
) -> None:
    """Sync the git fork/branch referenced in a merge request to the destination."""
    attrs = event.data["object_attributes"]
    merge_request_id = attrs["iid"]

    is_from_fork, dest_branch_name = _mr_branch_info(attrs)
    # https://docs.gitlab.com/development/permissions/predefined_roles/#general-permissions
    # visibility_level 20 is "public"
    private_src_repo = attrs["source"]["visibility_level"] != 20

    await sync_mr(
        gl_src,
        gl_dest,
        dest_user,
        merge_request_id=merge_request_id,
        target_fullname=attrs["target"]["path_with_namespace"],
        src_fullname=attrs["source"]["path_with_namespace"],
        src_repo_url=attrs["source"]["git_http_url"],
        dest_branch_name=dest_branch_name,
        is_from_fork=is_from_fork,
        private_src_repo=private_src_repo,
        is_draft=attrs["draft"],
        want_sha=attrs["last_commit"]["id"],
        mr_title=attrs["title"],
        mr_url=attrs["url"],
        dest_default_branch=event.data["project"]["default_branch"],
    )


@router.register("Merge Request Hook", action="close")
@router.register("Merge Request Hook", action="merge")
async def remove_mr(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *args,
    **kwargs,
) -> None:
    attrs = event.data["object_attributes"]

    repo_config = await get_repo_config(gl_src)

    if not repo_config.delete_closed:
        log.info("Skipped MR branch removal - delete_closed disabled")
        return

    # if the MR comes from a fork we should clean up the branch upon closing
    # or merging. However, if the MR comes from an internal branch we should
    # wait to clean up the branch when it's deleted from the source repository
    is_from_fork, _ = _mr_branch_info(attrs)
    if not is_from_fork:
        log.info("Skipped MR branch removal - internal branch")
        return

    merge_request_id = attrs["iid"]
    sync_ref = f"refs/heads/mr-{merge_request_id}"
    update_log_context(ref=sync_ref)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl_dest.instance_url}/{dest_fullname}.git"

    await _delete_ref(gl_dest, dest_user, dest_remote_url, sync_ref, entity="MR branch")


# -----------------------------------
# Tag Events
# -----------------------------------
@router.register("Tag Push Hook")
async def sync_tag(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *args,
    **kwargs,
) -> None:
    """Sync a git tag to the destination.

    GitLab has tag events (unlike GH), but tags don't need special handling like in sync_branch:
    - merge request checking
    - default branch checking via webhook registration
    """
    if event.data["after"] == NULL_SHA:
        await remove_ref(event, gl_src, gl_dest, dest_user, entity="tag")
        return

    src_repo_url = event.data["repository"]["git_http_url"]
    want_sha = event.data["after"]
    sync_ref = event.data["ref"]

    update_log_context(ref=sync_ref)

    try:
        repo_config = await get_repo_config(gl_src)
    except RepoConfigError as exc:
        await report_config_error(gl_src, want_sha, exc)
        return

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl_dest.instance_url}/{dest_fullname}.git"

    async def get_src_creds() -> dict[str, str]:
        return {
            "username": gl_src.requester,
            "password": await gl_src.auth.authenticate_user(gl_src.requester),
        }

    await _sync_ref(
        gl_src,
        gl_dest,
        dest_user,
        dest_remote_url,
        sync_ref,
        want_sha,
        src_repo_url,
        get_src_creds,
        check_name=repo_config.check_name,
        entity="tag",
    )


# -----------------------------------
# Comment Events
# -----------------------------------
@router.register("Note Hook")
async def respond_comment(
    event: sansio.Event,
    gl_src: GitLabSrcClient,
    gl_dest: GitLabDestClient,
    dest_user: str,
    *args,
    **kwargs,
) -> None:
    attrs = event.data["object_attributes"]

    if attrs.get("noteable_type") != "MergeRequest":
        log.info("Skipped comment - not MR comment")
        return

    comment = attrs["note"]
    note_id = attrs["id"]
    mr_data = event.data["merge_request"]
    mr_iid = mr_data["iid"]
    target_fullname = event.data["project"]["path_with_namespace"]
    bot_caller = gl_src.bot_caller

    response = None
    plus_one = False
    action_logged = False

    if re.search(f"{bot_caller} help", comment, re.IGNORECASE):
        response = help_message(bot_caller)
        log.info("Help message sent")
        action_logged = True

    elif re.search(f"{bot_caller} approve", comment, re.IGNORECASE):
        action_logged = True
        # approvals must be pinned to a specific commit to avoid unintended
        # syncing of malicious commits. the only mechanism to link comments to
        # commit ids is via "diff notes", comments on lines of codes on a specific commit
        # TODO: downside is cannot sync empty commits, allow "approve <sha>" command?
        is_diff_note = bool(attrs.get("line_code")) and bool(attrs.get("commit_id"))
        if is_diff_note:
            commit_sha = attrs["commit_id"]
            is_from_fork, dest_branch_name = _mr_branch_info(mr_data)
            synced = await sync_mr(
                gl_src,
                gl_dest,
                dest_user,
                merge_request_id=mr_iid,
                target_fullname=target_fullname,
                src_fullname=mr_data["source"]["path_with_namespace"],
                src_repo_url=mr_data["source"]["git_http_url"],
                dest_branch_name=dest_branch_name,
                is_from_fork=is_from_fork,
                # https://docs.gitlab.com/development/permissions/predefined_roles/#general-permissions
                # visibility_level 20 is "public"
                private_src_repo=mr_data["source"]["visibility_level"] != 20,
                is_draft=mr_data["draft"],
                want_sha=commit_sha,
                mr_title=mr_data["title"],
                mr_url=mr_data["url"],
                dest_default_branch=event.data["project"]["default_branch"],
            )
            if synced:
                plus_one = True
                log.info(
                    "Mirrored ref with approval from diff note",
                    extra={"ref": commit_sha},
                )
            else:
                log.info(
                    "Skipped thumbs-up - MR sync was skipped",
                    extra={"ref": commit_sha},
                )
        else:
            response = (
                "To mirror this MR, please comment on a specific line in the "
                "MR's **Changes** (diff) tab. This ensures the "
                "approval is tied to a specific commit to avoid mirroring "
                "malicious data."
            )
            log.info("Approval reminder sent")

    elif re.search(f"{bot_caller} re[-]?(run|start) pipeline", comment, re.IGNORECASE):
        # allows a project maintainer to restart the pipeline for an MR; should
        # be used for issues unrelated to code changes -- this does not sync
        # changes, as an external collaborator could submit malicious changes
        # and trigger a sync without explicit approval (see the `approve`
        # handling above)
        action_logged = True
        _, branch = _mr_branch_info(mr_data)
        update_log_context(branch=branch)

        repo_config = await get_repo_config(gl_src)
        dest_fullname = repo_config.dest_fullname

        try:
            pipeline_url = await gl_dest.run_pipeline(dest_fullname, branch)
        except BadRequest as exc:
            if exc.status_code in PERMISSION_DENIED_STATUSES:
                response = permission_denied_response(exc)
                log.info("Pipeline failed to start - insufficient permissions")
            elif exc.status_code == 400:
                # \n to avoid indent markdown issues
                response = f"""{PIPELINE_FAILED_MSG}\n```\n{exc}\n```"""
                log.info("Pipeline failed to start", extra={"error": exc})
            else:
                raise
        else:
            response = f"I've started a new [pipeline]({pipeline_url}) for you!"
            plus_one = True
            log.info("Pipeline started for branch")

    elif re.search(
        f"{bot_caller} restart failed(?:[- ]?jobs)?", comment, re.IGNORECASE
    ):
        # if a pipeline failed, we give the user the option to restart any
        # failed jobs; we don't want to re-sync the branch, as a new pipeline
        # would be created and would defeat the purpose of individually
        # restarting failed jobs
        action_logged = True
        _, branch = _mr_branch_info(mr_data)
        update_log_context(branch=branch)

        repo_config = await get_repo_config(gl_src)
        dest_fullname = repo_config.dest_fullname

        try:
            pipeline_id = await gl_dest.get_latest_pipeline(dest_fullname, branch)
        except BadRequest as exc:
            if exc.status_code not in PERMISSION_DENIED_STATUSES:
                raise
            response = permission_denied_response(exc)
            log.info("Pipeline ID fetch failed - insufficient permissions")
        else:
            if pipeline_id:
                try:
                    pipeline_url = await gl_dest.retry_pipeline_jobs(
                        dest_fullname, pipeline_id
                    )
                except BadRequest as exc:
                    if exc.status_code not in PERMISSION_DENIED_STATUSES:
                        raise
                    response = permission_denied_response(exc)
                    log.info("Jobs restart failed - insufficient permissions")
                else:
                    response = f"I've retried any failed jobs in the [pipeline]({pipeline_url})!"
                    plus_one = True
                    log.info("Jobs restarted for branch")
            else:
                response = "No pipeline exists."
                log.info("No pipeline found for branch")

    if response:
        await gl_src.post_comment(mr_iid, response)

    if plus_one:
        await gl_src.react_to_comment(mr_iid, note_id, "+1")

    if not action_logged:
        log.info("Skipped comment - no command matched")
