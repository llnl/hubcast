import logging
import re
from typing import Any

from gidgethub import routing, sansio
from repligit.asyncio import fetch_pack, ls_remote, send_pack

from hubcast.clients.github.client import GitHubClient
from hubcast.clients.gitlab.client import GitLabClient
from hubcast.exceptions import HubcastError
from hubcast.web import comments
from hubcast.web.github.utils import get_repo_config

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

    # skip branches from push events that are also pull requests
    if await gh.get_prs(branch=sync_ref):
        return

    # only refresh config on default branch pushes (where .github/hubcast.yml lives)
    default_branch = event.data["repository"]["default_branch"]
    is_default_branch = sync_ref == f"refs/heads/{default_branch}"
    repo_config, fetched = await get_repo_config(
        gh, src_fullname, refresh=is_default_branch
    )

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    # only set/update webhook on default branch pushes when config cache was bypassed (refresh or initial fetch)
    if fetched and is_default_branch:
        # setup callback webhook on GitLab
        await gl.set_webhook(
            dest_org=repo_config.dest_org,
            dest_repo=repo_config.dest_name,
            gh_owner=src_owner,
            gh_repo=src_repo_name,
            gh_check=repo_config.check_name,
            check_types=repo_config.check_types,
        )

    # sync commits from GitHub -> GitLab
    gl_token = await gl.auth.authenticate_user(gl_user)

    gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    have_shas = set(gl_refs.values())
    from_sha = gl_refs.get(sync_ref) or ("0" * 40)

    if want_sha in have_shas:
        log.info(
            "Destination ref already up-to-date",
            extra={"ref": sync_ref},
        )
        return

    log.info(
        "Mirroring refs",
        extra={
            "ref": sync_ref,
            "from_sha": from_sha,
            "want_sha": want_sha,
        },
    )

    gh_token = await gh.auth.authenticate_installation(gh.repo_owner, gh.repo_name)

    packfile = await fetch_pack(
        src_repo_url,
        want_sha,
        have_shas,
        username=gh.requester,  # the username doesn't matter, but can't be empty
        password=gh_token,
    )

    await send_pack(
        dest_remote_url,
        sync_ref,
        from_sha,
        want_sha,
        packfile,
        username=gl_user,
        password=gl_token,
    )

    log.info(
        "Successfully mirrored refs",
        extra={
            "ref": sync_ref,
            "from_sha": from_sha,
            "want_sha": want_sha,
        },
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

    repo_config, _ = await get_repo_config(gh, src_fullname)

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    gl_token = await gl.auth.authenticate_user(gl_user)

    gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    head_sha = gl_refs.get(sync_ref)
    null_sha = "0" * 40

    log.info("Deleting ref", extra={"ref": sync_ref})

    await send_pack(
        dest_remote_url,
        sync_ref,
        head_sha,
        null_sha,
        b"",
        username=gl_user,
        password=gl_token,
    )

    log.info(
        "Successfully deleted ref",
        extra={"ref": sync_ref},
    )


# -----------------------------------
# Pull Request Events
# -----------------------------------


async def sync_pr(
    pull_request: dict[str, Any],
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    src_repo_private: bool,
    want_sha: str,
    default_branch: str,
) -> None:
    """Sync the git fork/branch referenced in a PR to GitLab.

    This isn't technically an event handler, but is used a couple different ways in this file.
    """
    pull_request_id = pull_request["number"]

    src_repo_url = pull_request["head"]["repo"]["clone_url"]
    src_fullname = pull_request["head"]["repo"]["full_name"]
    base_fullname = pull_request["base"]["repo"]["full_name"]

    # pull requests coming from forks are pushed as branches in the form of
    # pr-<pr-number> instead of as their branch name as conflicts could occur
    # between multiple repositories
    is_pull_request_fork = src_fullname != base_fullname
    if is_pull_request_fork:
        sync_branch = f"pr-{pull_request_id}"
    else:
        sync_branch = pull_request["head"]["ref"]

    sync_ref = f"refs/heads/{sync_branch}"

    if is_pull_request_fork and src_repo_private:
        # GitHub apps will not have access to private forks
        log.warning(
            "Cannot sync pull request from private fork",
            extra={
                "pull_request_id": pull_request_id,
                "fork_fullname": pull_request["head"]["repo"]["full_name"],
            },
        )
        return

    # get the repository configuration from .github/hubcast.yml
    repo_config, _ = await get_repo_config(gh, base_fullname)
    if not repo_config.sync_drafts and pull_request["draft"]:
        if repo_config.sync_drafts_msg:
            await gh.set_check_status(
                want_sha,
                repo_config.check_name or "hubcast",
                status="skipped",
                title="Hubcast disables sync for draft PRs.",
            )
        return

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"
    gl_token = await gl.auth.authenticate_user(gl_user)

    gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    have_shas = set(gl_refs.values())
    from_sha = gl_refs.get(sync_ref) or ("0" * 40)

    if want_sha in have_shas:
        log.info(
            "Destination ref already up-to-date",
            extra={"ref": sync_ref},
        )
    else:  # needs sync
        if is_pull_request_fork and not src_repo_private:
            # no auth needed for public forks
            src_creds = {}
        else:
            # authenticate if the PR comes from the src repository
            src_creds = {
                "username": gh.requester,  # the username doesn't matter, but can't be empty
                "password": await gh.auth.authenticate_installation(
                    gh.repo_owner, gh.repo_name
                ),
            }

        # fetch differential packfile with all new commits
        packfile = await fetch_pack(
            src_repo_url,
            want_sha,
            have_shas,
            **src_creds,
        )

        # upload packfile to gitlab repository
        log.info(
            "Mirroring refs",
            extra={
                "from_sha": from_sha,
                "want_sha": want_sha,
            },
        )
        await send_pack(
            dest_remote_url,
            sync_ref,
            from_sha,
            want_sha,
            packfile,
            username=gl_user,
            password=gl_token,
        )

    # skip already created MRs
    if repo_config.create_mr and not await gl.get_mr(
        dest_fullname, sync_branch, default_branch
    ):
        await gl.create_mr(
            gl_fullname=dest_fullname,
            src_branch=sync_branch,
            target_branch=default_branch,
            ref_title=pull_request["title"],
            ref_url=pull_request["html_url"],
        )


@router.register("pull_request", action="opened")
@router.register("pull_request", action="reopened")
@router.register("pull_request", action="synchronize")
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
    repo_config, _ = await get_repo_config(gh, base_fullname)

    if not repo_config.delete_closed:
        return

    # if the pull request comes from a fork we should clean up
    # the branch upon closing or merging the PR. However, if the
    # pull request comes from an internal branch we should wait
    # to clean up the branch when the branch is deleted from the
    # internal repository
    is_pull_request_fork = src_fullname != base_fullname
    if not is_pull_request_fork:
        return

    pull_request_id = pull_request["number"]
    sync_ref = f"refs/heads/pr-{pull_request_id}"

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"
    gl_token = await gl.auth.authenticate_user(gl_user)

    gl_refs = await ls_remote(dest_remote_url, username=gl_user, password=gl_token)
    head_sha = gl_refs.get(sync_ref)
    null_sha = "0" * 40

    log.info("Deleting ref", extra={"ref": sync_ref})
    await send_pack(
        dest_remote_url,
        sync_ref,
        head_sha,
        null_sha,
        b"",
        username=gl_user,
        password=gl_token,
    )


@router.register("pull_request_review", action="submitted")
async def respond_pr_comment(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    comment = event.data["review"]["body"]

    # reviews without comments (plain approvals or RFC)
    if not comment:
        return

    if re.search(f"{gh.bot_caller} approve", comment, re.IGNORECASE):
        # sync PR changes to the destination on behalf of the commenter
        # does not handle PR deletions, those will need to be manually cleaned by project maintainers

        # approvals must be tied to specific commit hashes to avoid unintended syncing of malicious commits
        commit_sha = event.data["review"]["commit_id"]
        pull_request = event.data["pull_request"]
        src_repo_private = pull_request["head"]["repo"]["private"]
        # sync the approved commit explicitly
        await sync_pr(
            pull_request,
            gh,
            gl,
            gl_user,
            src_repo_private,
            want_sha=commit_sha,
            default_branch=event.data["repository"]["default_branch"],
        )
        await gh.react_to_comment(event.data["review"]["node_id"], "+1")


@router.register("issue_comment", action="created")
async def respond_comment(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gl_user: str,
    *arg,
    **kwargs,
) -> None:
    # differentiate issue vs PR comment
    if "pull_request" not in event.data["issue"]:
        return

    comment = event.data["comment"]["body"]
    response = None
    plus_one = False

    if re.search(f"{gh.bot_caller} help", comment, re.IGNORECASE):
        response = comments.help_message(gh.bot_caller)

    elif re.search(f"{gh.bot_caller} approve", comment, re.IGNORECASE):
        response = (
            "To approve the sync of this PR, please use the "
            "[GitHub review comment feature](https://github.com/llnl/hubcast/blob/main/docs/guide-user.md#approval) "
            "to submit an approval. This ensures the approval is tied to a specific "
            "commit to avoid unintended syncing of malicious commits."
        )

    elif re.search(
        f"{gh.bot_caller} (re[-]?)?(run|start) pipeline", comment, re.IGNORECASE
    ):
        # allows a project maintainer to restart the pipeline for a PR; should be
        # used for issues unrelated for code changes
        # this process will not sync changes, as an external collaborator could
        # submit malicious changes and trigger a sync without explicit approval
        # on the commit hash (see `respond_pr_comment`)
        pull_request_id = event.data["issue"]["number"]
        pull_request = await gh.get_pr(pull_request_id)

        # get the branch this PR belongs to
        src_fullname = pull_request["head"]["repo"]["full_name"]
        base_fullname = pull_request["base"]["repo"]["full_name"]

        # pull requests coming from forks are pushed as branches in the form of
        # pr-<pr-number> instead of as their branch name as conflicts could occur
        # between multiple repositories
        is_pull_request_fork = src_fullname != base_fullname
        if is_pull_request_fork:
            branch = f"pr-{pull_request_id}"
        else:
            branch = pull_request["head"]["ref"]

        # get the gitlab repo information and run the pipeline
        repo_config, _ = await get_repo_config(gh, base_fullname)
        dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
        pipeline_url = await gl.run_pipeline(dest_fullname, branch)

        if pipeline_url:
            response = f"I've started a new [pipeline]({pipeline_url}) for you!"
            plus_one = True
        else:
            response = "I had a problem starting the pipeline."

    elif re.search(
        f"{gh.bot_caller} restart failed(?:[- ]?jobs)?", comment, re.IGNORECASE
    ):
        # if a pipeline failed, we give the user the option to restart any failed jobs
        # we don't want to re-sync the branch, as a new pipeline would be created
        # and would defeat the purpose of individually restarting failed jobs
        pull_request_id = event.data["issue"]["number"]
        pull_request = await gh.get_pr(pull_request_id)

        # get the branch this PR belongs to
        src_fullname = pull_request["head"]["repo"]["full_name"]
        base_fullname = pull_request["base"]["repo"]["full_name"]
        # pull requests coming from forks are pushed as branches in the form of
        # pr-<pr-number> instead of as their branch name as conflicts could occur
        # between multiple repositories
        is_pull_request_fork = src_fullname != base_fullname
        if is_pull_request_fork:
            branch = f"pr-{pull_request_id}"
        else:
            branch = pull_request["head"]["ref"]

        # get the gitlab repo information and run the pipeline
        repo_config, _ = await get_repo_config(gh, base_fullname)
        dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
        pipeline_id = await gl.get_latest_pipeline(dest_fullname, branch)

        if pipeline_id:
            pipeline_url = await gl.retry_pipeline_jobs(dest_fullname, pipeline_id)

            if pipeline_url:
                response = (
                    f"I've retried any failed jobs in the [pipeline]({pipeline_url})!"
                )
                plus_one = True
            else:
                response = "I had a problem retrying jobs in the pipeline."
        else:
            response = "No pipeline exists."

    if response:
        await gh.post_comment(event.data["issue"]["number"], response)

    if plus_one:
        await gh.react_to_comment(event.data["comment"]["node_id"], "+1")


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
    Handles a user re-running a check run for the latest commit in the branch.
    See https://docs.github.com/en/webhooks/webhook-events-and-payloads?actionType=rerequested#check_run.
    """
    src_fullname = event.data["repository"]["full_name"]
    branch = event.data["check_run"]["check_suite"]["head_branch"]
    check_run_commit = event.data["check_run"]["head_sha"]

    # get the latest commit on the branch from GH
    branch_data = await gh.get_branch(branch)
    latest_commit = branch_data["commit"]["sha"]

    # only rerun if this commit is the head of the branch
    if check_run_commit != latest_commit:
        log.info("user tried to re-run check for old commit")
        return

    # get the GL repo info and run the pipeline
    repo_config, _ = await get_repo_config(gh, src_fullname)
    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    await gl.run_pipeline(dest_fullname, branch)
