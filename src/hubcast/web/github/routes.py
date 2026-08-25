import logging
import re
from collections.abc import Awaitable, Callable, Collection
from typing import Any

from aiohttp.client_exceptions import ClientResponseError
from gidgethub import routing, sansio
from gidgetlab.exceptions import BadRequest
from repligit.asyncio import fetch_pack, ls_remote, send_pack
from repligit.exceptions import RefUpdateRejected

from hubcast.clients.github.client import GitHubClient
from hubcast.clients.gitlab.client import GitLabClient
from hubcast.exceptions import HubcastError, RepoConfigError, WebhookPermissionError
from hubcast.logging import update_log_context
from hubcast.web.github.messages import (
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
    PERMISSION_DENIED_STATUSES,
    PERMISSION_DENIED_SUMMARY,
    PERMISSION_DENIED_SYNC_LOG_MSG,
    PERMISSION_DENIED_TITLE,
    PIPELINE_FAILED_MSG,
    WEBHOOK_PERMISSION_DENIED_SUMMARY,
    WEBHOOK_PERMISSION_DENIED_TITLE,
    help_message,
)
from hubcast.web.github.utils import (
    changed_files_from_push,
    get_repo_config,
    parse_repo_config,
)

log = logging.getLogger(__name__)


class GitHubRouter(routing.Router):
    """
    Custom router to handle GitHub interactions for hubcast
    """

    async def dispatch(self, event: sansio.Event, *args: Any, **kwargs: Any) -> None:
        """Dispatch an event to all registered function(s)."""
        found_callbacks = self.fetch(event)
        for callback in found_callbacks:
            try:
                await callback(event, *args, **kwargs)
            except HubcastError as e:
                e.log(log)
            except Exception:
                log.exception("Failed to process GitHub webhook event")


router = GitHubRouter()


# check name used to report errors about repo config or webhooks
# this avoids overwriting errors if a normal pipeline succeeds, and provides
# a default for situations where there is no default check name set
# this check won't linger because resolving issues requires a new commit to be pushed
ERROR_CHECK_NAME = "hubcast-config"

NULL_SHA = "0" * 40


async def report_config_error(gh: GitHubClient, sha: str, exc: RepoConfigError) -> None:
    """Report a missing/invalid repo config to the user as a failed check."""
    exc.log(log)
    await gh.set_check_status(
        sha,
        ERROR_CHECK_NAME,
        "failure",
        title=exc.title,
        summary=exc.summary,
    )


def _pr_branch_name(pull_request: dict[str, Any]) -> str:
    """Return the branch name used on the destination for this PR.

    Pull requests coming from forks are pushed as branches in the form of
    pr-<pr-number> instead of as their branch name, as conflicts can occur
    between multiple source repositories.
    """
    src_fullname = pull_request["head"]["repo"]["full_name"]
    base_fullname = pull_request["base"]["repo"]["full_name"]
    if src_fullname != base_fullname:
        return f"pr-{pull_request['number']}"
    return pull_request["head"]["ref"]


def _is_deactivated_account(exc: BadRequest) -> bool:
    """Whether a GitLab permission-denied error was caused by a deactivated account."""
    return DEACTIVATED_ACCOUNT_MARKER in str(exc)


def _permission_denied_response(exc: BadRequest) -> str:
    """User-facing message for a GitLab permission-denied error from a comment command."""
    if _is_deactivated_account(exc):
        return DEACTIVATED_ACCOUNT_MSG
    return PERMISSION_DENIED_SUMMARY


async def _sync_ref(
    gh: GitHubClient,
    gl: GitLabClient,
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
    Permission issues and Repligit errors are reported as GitHub checks to `want_sha`.

    Returns True in a success state (up-to-date or sync performed), otherwise False.
    """
    gl_token = await gl.auth.authenticate_user(gl_user)

    try:
        gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    except ClientResponseError as exc:
        if exc.status not in PERMISSION_DENIED_STATUSES:
            raise
        log.info(PERMISSION_DENIED_SYNC_LOG_MSG)
        await gh.set_check_status(
            want_sha,
            check_name,
            "failure",
            title=PERMISSION_DENIED_TITLE,
            summary=PERMISSION_DENIED_SUMMARY,
        )
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
        await gh.set_check_status(
            want_sha,
            check_name,
            "failure",
            title=PERMISSION_DENIED_TITLE,
            summary=PERMISSION_DENIED_SUMMARY,
        )
        return False
    # repligit
    except RefUpdateRejected as exc:
        hook_declined = str(exc) == HOOK_DECLINED_MSG
        await gh.set_check_status(
            want_sha,
            check_name,
            "failure",
            title=HOOK_DECLINED_TITLE if hook_declined else INTERNAL_ERROR_TITLE,
            summary=HOOK_DECLINED_SUMMARY if hook_declined else INTERNAL_ERROR_SUMMARY,
        )
        if not hook_declined:
            raise
        return False

    log.info(f"Synced {entity}")
    return True


async def _delete_ref(
    gl: GitLabClient,
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
        # we cannot set GitHub status checks for deleted refs, and we have no way to notify the user of this failure
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


# -----------------------------------
# Push Events
# -----------------------------------
@router.register("push", deleted=False)
async def sync_branch(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    """Sync the git branch referenced to GitLab."""
    src_repo_url = event.data["repository"]["clone_url"]
    src_fullname = event.data["repository"]["full_name"]
    src_owner, src_repo_name = src_fullname.split("/")
    # the commit the push event is referencing
    want_sha = event.data["after"]
    sync_ref = event.data["ref"]

    update_log_context(ref=sync_ref)

    # skip branches from push events that are also pull requests
    if await gh.get_prs(branch=sync_ref):
        log.info("Skipped branch sync - branch has open PR")
        return

    # only refresh config when a default branch push touches .github/hubcast.yml
    default_branch = event.data["repository"]["default_branch"]
    is_default_branch = sync_ref == f"refs/heads/{default_branch}"
    changed_files = changed_files_from_push(event.data)
    config_changed = gh.repo_config_path in changed_files
    try:
        repo_config = await get_repo_config(
            gh, src_fullname, refresh=is_default_branch and config_changed
        )
    except RepoConfigError as exc:
        # only report the default branch config's error when this push isn't trying to fix it
        if is_default_branch or not config_changed:
            await report_config_error(gh, want_sha, exc)
        # if the config has changes and not on default branch, validate the new config
        if not is_default_branch:
            await validate_config_change(gh, changed_files, want_sha)
        return

    # validate the changes when the default branch config doesn't have issues
    if not is_default_branch:
        await validate_config_change(gh, changed_files, want_sha)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"
    head_commit = event.data.get("head_commit")
    commit_msg = head_commit["message"] if head_commit else ""

    # only set/update webhook on default branch pushes when the push actually
    # touched the config file (config_changed above); this avoids spurious
    # permission errors when the config merely aged out of the cache
    # we also give maintainers the option to force-set the webhook: if the
    # commit message contains [hubcast config], we'll set the webhook
    if is_default_branch and (config_changed or "[hubcast config]" in commit_msg):
        # setup callback webhook on GitLab
        try:
            await gl.set_webhook(
                dest_org=repo_config.dest_org,
                dest_repo=repo_config.dest_name,
                gh_owner=src_owner,
                gh_repo=src_repo_name,
                gh_check=repo_config.check_name,
                check_types=repo_config.check_types,
            )
        except WebhookPermissionError as exc:
            # the user is not a maintainer and we need to tell them to push config changes with higher permissions
            exc.log(log)
            await gh.set_check_status(
                want_sha,
                ERROR_CHECK_NAME,
                "failure",
                title=WEBHOOK_PERMISSION_DENIED_TITLE,
                summary=WEBHOOK_PERMISSION_DENIED_SUMMARY,
            )
            return
        except HubcastError as exc:
            # log for the hubcast admin and tell the user it's not their fault
            exc.log(log)
            await gh.set_check_status(
                want_sha,
                ERROR_CHECK_NAME,
                "failure",
                title=INTERNAL_ERROR_TITLE,
                summary=INTERNAL_ERROR_SUMMARY,
            )
            return
        else:
            log.info("Updated GitLab webhook", extra={"dest_fullname": dest_fullname})

    async def get_src_creds() -> dict[str, str]:
        # push events can only come via the source repo, so we assume that the GitHub app can authenticate with its credentials
        return {
            "username": gh.requester,  # the username doesn't matter, but can't be empty
            "password": await gh.auth.authenticate_installation(
                gh.repo_owner, gh.repo_name
            ),
        }

    await _sync_ref(
        gh,
        gl,
        gl_user,
        dest_remote_url,
        sync_ref,
        want_sha,
        src_repo_url,
        get_src_creds,
        check_name=repo_config.check_name,
        entity="branch",
    )


@router.register("push", deleted=True)
async def remove_branch(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    src_fullname = event.data["repository"]["full_name"]
    sync_ref = event.data["ref"]

    update_log_context(ref=sync_ref)

    repo_config = await get_repo_config(gh, src_fullname)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    await _delete_ref(gl, gl_user, dest_remote_url, sync_ref, entity="branch")


# -----------------------------------
# Pull Request Events
# -----------------------------------


async def validate_config_change(
    gh: GitHubClient, changed_files: Collection[str], head_sha: str
) -> None:
    """
    Validate the Hubcast repo config at head_sha if changed_files touches it,
    reporting feedback via a GH check.

    This is meant to supersede previously reported config errors on the default branch.
    """
    if gh.repo_config_path not in changed_files:
        return

    # config was deleted in this change
    config = await gh.get_repo_config(ref=head_sha)
    if config is None:
        return

    try:
        parse_repo_config(config)
    except RepoConfigError as exc:
        exc.log(log)
        await gh.set_check_status(
            head_sha,
            ERROR_CHECK_NAME,
            "failure",
            title=exc.title,
            summary=exc.summary,
        )
        return

    # report success if validation passes for the PR's config
    await gh.set_check_status(
        head_sha,
        ERROR_CHECK_NAME,
        "success",
        title=CONFIG_VALID_TITLE,
        summary=CONFIG_VALID_SUMMARY,
    )


async def sync_pr(
    pull_request: dict[str, Any],
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    src_repo_private: bool,
    want_sha: str,
    default_branch: str,
    force_sync_draft: bool = False,  # allows draft PRs to be manually synced
) -> None:
    """Sync the git fork/branch referenced in a PR to GitLab.

    This isn't technically an event handler, but is used a couple different ways in this file.
    """
    src_repo_url = pull_request["head"]["repo"]["clone_url"]
    src_fullname = pull_request["head"]["repo"]["full_name"]
    base_fullname = pull_request["base"]["repo"]["full_name"]
    is_pull_request_fork = src_fullname != base_fullname

    sync_branch = _pr_branch_name(pull_request)
    sync_ref = f"refs/heads/{sync_branch}"

    update_log_context(ref=sync_ref)

    if is_pull_request_fork and src_repo_private:
        # GitHub apps will not have access to private forks
        log.warning(
            "Skipped PR sync - private fork",
            extra={"fork_fullname": pull_request["head"]["repo"]["full_name"]},
        )
        return

    changed_files = await gh.get_pr_files(pull_request["number"])
    config_changed = gh.repo_config_path in changed_files

    # get the repository configuration from .github/hubcast.yml
    try:
        repo_config = await get_repo_config(gh, base_fullname)
    except RepoConfigError as exc:
        # only report the default branch config's error when this push isn't trying to fix it
        if not config_changed:
            await report_config_error(gh, want_sha, exc)
        await validate_config_change(gh, changed_files, want_sha)
        return

    # validate the changes when the default branch config doesn't have issues
    await validate_config_change(gh, changed_files, want_sha)

    if not force_sync_draft and not repo_config.sync_drafts and pull_request["draft"]:
        if repo_config.sync_drafts_msg:
            await gh.set_check_status(
                want_sha,
                repo_config.check_name,
                status="skipped",
                title="Hubcast disables sync for draft PRs.",
            )
        log.info("Skipped PR sync - draft PR")
        return

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    async def get_src_creds() -> dict[str, str]:
        # we should not try to authenticate if the source is a public fork, as our GitHub app credentials will not work
        # in addition to the fact that they are public
        if is_pull_request_fork and not src_repo_private:
            return {}
        # use GH app credentials if the PR comes from the src repo
        return {
            "username": gh.requester,  # the username doesn't matter, but can't be empty
            "password": await gh.auth.authenticate_installation(
                gh.repo_owner, gh.repo_name
            ),
        }

    synced = await _sync_ref(
        gh,
        gl,
        gl_user,
        dest_remote_url,
        sync_ref,
        want_sha,
        src_repo_url,
        get_src_creds,
        check_name=repo_config.check_name,
        entity="PR",
    )

    # sync failed (logged in _sync_ref)
    if not synced:
        return

    # create MRs if configured
    # skip already created MRs
    if repo_config.create_mr and not await gl.get_mr(
        dest_fullname, sync_branch, default_branch
    ):
        # user must have at least developer role to reach this point so we don't need to do a permissions check
        await gl.create_mr(
            gl_fullname=dest_fullname,
            src_branch=sync_branch,
            target_branch=default_branch,
            ref_title=pull_request["title"],
            ref_url=pull_request["html_url"],
        )
        log.info("Created MR", extra={"branch": sync_branch})


@router.register("pull_request", action="opened")
@router.register("pull_request", action="reopened")
@router.register("pull_request", action="synchronize")
@router.register("pull_request", action="ready_for_review")
async def sync_pr_event(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    """Sync the git fork/branch referenced in a PR to GitLab."""
    pull_request = event.data["pull_request"]
    src_repo_private = pull_request["head"]["repo"]["private"]
    if event.data["action"] == "synchronize":
        # to prevent races between pushes to the PR, we want to explicitly sync the commit referenced in the push event
        want_sha = event.data["after"]
    else:
        # these events are not triggered by new commits, so we sync the head
        want_sha = pull_request["head"]["sha"]
    await sync_pr(
        pull_request,
        gh,
        gl,
        gl_user,
        src_repo_private,
        want_sha=want_sha,
        default_branch=event.data["repository"]["default_branch"],
    )


@router.register("pull_request", action="closed")
async def remove_pr(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    pull_request = event.data["pull_request"]
    src_fullname = pull_request["head"]["repo"]["full_name"]
    base_fullname = pull_request["base"]["repo"]["full_name"]

    # get the repository configuration from .github/hubcast.yml
    repo_config = await get_repo_config(gh, base_fullname)

    if not repo_config.delete_closed:
        log.info("Skipped PR branch removal - delete_closed disabled")
        return

    # if the pull request comes from a fork we should clean up
    # the branch upon closing or merging the PR. However, if the
    # pull request comes from an internal branch we should wait
    # to clean up the branch when the branch is deleted from the
    # internal repository
    is_pull_request_fork = src_fullname != base_fullname
    if not is_pull_request_fork:
        log.info("Skipped PR branch removal - internal branch")
        return

    sync_ref = f"refs/heads/{_pr_branch_name(pull_request)}"
    update_log_context(ref=sync_ref)

    dest_fullname = repo_config.dest_fullname
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    await _delete_ref(gl, gl_user, dest_remote_url, sync_ref, entity="PR branch")


@router.register("issue_comment", action="created")
@router.register("pull_request_review", action="submitted")
async def respond_comment(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    is_review = event.event == "pull_request_review"

    if is_review:
        comment = event.data["review"]["body"]
        # reviews without comments (plain approvals or RFC)
        if not comment:
            log.info("Skipped comment - no command matched")
            return
        pr_number = event.data["pull_request"]["number"]
        comment_node_id = event.data["review"]["node_id"]
    else:
        # differentiate issue vs PR comment
        if "pull_request" not in event.data["issue"]:
            log.info("Skipped comment - not PR comment")
            return
        comment = event.data["comment"]["body"]
        pr_number = event.data["issue"]["number"]
        comment_node_id = event.data["comment"]["node_id"]

    response = None
    plus_one = False
    action_logged = False

    if re.search(f"{gh.bot_caller} help", comment, re.IGNORECASE):
        response = help_message(gh.bot_caller)
        log.info("Help message sent")
        action_logged = True

    elif re.search(f"{gh.bot_caller} approve", comment, re.IGNORECASE):
        action_logged = True
        if is_review:
            # sync PR changes to the destination on behalf of the commenter
            # does not handle PR deletions, those will need to be manually cleaned by project maintainers

            # approvals must be tied to specific commit hashes to avoid unintended syncing of malicious commits
            commit_sha = event.data["review"]["commit_id"]
            pull_request = event.data["pull_request"]
            src_repo_private = pull_request["head"]["repo"]["private"]
            # sync the approved commit explicitly even if sync_drafts is disabled
            await sync_pr(
                pull_request,
                gh,
                gl,
                gl_user,
                src_repo_private,
                want_sha=commit_sha,
                default_branch=event.data["repository"]["default_branch"],
                force_sync_draft=True,
            )
            plus_one = True
            log.info(
                "Mirrored ref with approval from review comment",
                extra={"ref": commit_sha},
            )
        else:
            response = (
                "To mirror this PR, please use the "
                "[GitHub review comment feature](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#approval). "
                "This ensures the approval is tied to a specific "
                "commit to avoid mirroring malicious data."
            )
            log.info("Approval reminder sent")

    elif re.search(
        f"{gh.bot_caller} re[-]?(run|start) pipeline", comment, re.IGNORECASE
    ):
        # allows a project maintainer to restart the pipeline for a PR; should be
        # used for issues unrelated for code changes
        # this process will not sync changes, as an external collaborator could
        # submit malicious changes and trigger a sync without explicit approval
        # on the commit hash (see the `approve` review handling above)
        action_logged = True
        pull_request = await gh.get_pr(pr_number)

        # get the branch this PR belongs to
        base_fullname = pull_request["base"]["repo"]["full_name"]
        branch = _pr_branch_name(pull_request)

        update_log_context(branch=branch)

        # get the gitlab repo information and run the pipeline
        repo_config = await get_repo_config(gh, base_fullname)
        dest_fullname = repo_config.dest_fullname

        try:
            pipeline_url = await gl.run_pipeline(dest_fullname, branch)
        except BadRequest as exc:
            if exc.status_code in PERMISSION_DENIED_STATUSES:
                response = _permission_denied_response(exc)
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
        f"{gh.bot_caller} restart failed(?:[- ]?jobs)?", comment, re.IGNORECASE
    ):
        # if a pipeline failed, we give the user the option to restart any failed jobs
        # we don't want to re-sync the branch, as a new pipeline would be created
        # and would defeat the purpose of individually restarting failed jobs
        action_logged = True
        pull_request = await gh.get_pr(pr_number)

        # get the branch this PR belongs to
        base_fullname = pull_request["base"]["repo"]["full_name"]
        branch = _pr_branch_name(pull_request)

        update_log_context(branch=branch)

        # get the gitlab repo information and run the pipeline
        repo_config = await get_repo_config(gh, base_fullname)
        dest_fullname = repo_config.dest_fullname

        try:
            pipeline_id = await gl.get_latest_pipeline(dest_fullname, branch)
        except BadRequest as exc:
            if exc.status_code not in PERMISSION_DENIED_STATUSES:
                raise
            response = _permission_denied_response(exc)
            log.info("Pipeline ID fetch failed - insufficient permissions")
        else:
            if pipeline_id:
                try:
                    pipeline_url = await gl.retry_pipeline_jobs(
                        dest_fullname, pipeline_id
                    )
                except BadRequest as exc:
                    if exc.status_code not in PERMISSION_DENIED_STATUSES:
                        raise
                    response = _permission_denied_response(exc)
                    log.info("Jobs restart failed - insufficient permissions")
                else:
                    response = f"I've retried any failed jobs in the [pipeline]({pipeline_url})!"
                    plus_one = True
                    log.info("Jobs restarted for branch")
            else:
                response = "No pipeline exists."
                log.info("No pipeline found for branch")

    if response:
        await gh.post_comment(pr_number, response)

    if plus_one:
        await gh.react_to_comment(comment_node_id, "+1")

    if not action_logged:
        log.info("Skipped comment - no command matched")


# job and pipeline checks are created with a details_url pointing
# at the corresponding GitLab job/pipeline (see job_status_relay and pipeline_status_relay in web/gitlab/routes.py)
JOB_DETAILS_URL_RE = re.compile(r"/-/jobs/(\d+)/?$")
PIPELINE_DETAILS_URL_RE = re.compile(r"/-/pipelines/(\d+)/?$")


async def _fail_check_from_pipeline_error(
    gh: GitHubClient,
    check_name: str,
    check_run_commit: str,
    exc: BadRequest,
) -> None:
    """Set a failing check status from a GitLab pipeline/job start error."""
    if exc.status_code in PERMISSION_DENIED_STATUSES:
        deactivated = _is_deactivated_account(exc)
        message = DEACTIVATED_ACCOUNT_MSG if deactivated else PERMISSION_DENIED_TITLE
        summary = "" if deactivated else PERMISSION_DENIED_SUMMARY
    elif exc.status_code == 400:
        message = PIPELINE_FAILED_MSG
        summary = str(exc)
    else:
        # unknown issues
        raise exc
    await gh.set_check_status(
        check_run_commit,
        check_name,
        "failure",
        title=message,
        summary=summary,
    )


@router.register("check_run", action="rerequested")
async def rerun_check(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    """
    Handles a user re-running a check run by retrying the specific GitLab job or pipeline it's attached to.
    See https://docs.github.com/en/webhooks/webhook-events-and-payloads?actionType=rerequested#check_run.
    """
    src_fullname = event.data["repository"]["full_name"]
    check_run_commit = event.data["check_run"]["head_sha"]
    details_url = event.data["check_run"]["details_url"]
    update_log_context(
        check_run_commit=check_run_commit, check_run_id=event.data["check_run"]["id"]
    )

    job_match = JOB_DETAILS_URL_RE.search(details_url)
    pipeline_match = PIPELINE_DETAILS_URL_RE.search(details_url)

    if not any((job_match, pipeline_match)):
        log.warning(
            "Skipped check rerun due to unrecognized check type",
        )
        return

    try:
        repo_config = await get_repo_config(gh, src_fullname)
    except RepoConfigError as exc:
        await report_config_error(gh, check_run_commit, exc)
        return

    dest_fullname = repo_config.dest_fullname

    if job_match:
        job_id = int(job_match.group(1))
        update_log_context(job_id=job_id)
        try:
            await gl.retry_job(dest_fullname, job_id)
        except BadRequest as exc:
            await _fail_check_from_pipeline_error(
                gh, repo_config.check_name, check_run_commit, exc
            )
            return
        log.info("Retried job for check run")
    elif pipeline_match:
        pipeline_id = int(pipeline_match.group(1))
        update_log_context(pipeline_id=pipeline_id)
        try:
            await gl.retry_pipeline_jobs(dest_fullname, pipeline_id)
        except BadRequest as exc:
            await _fail_check_from_pipeline_error(
                gh, repo_config.check_name, check_run_commit, exc
            )
            return
        log.info("Retried failed jobs for check run")
