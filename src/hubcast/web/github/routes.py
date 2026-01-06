import logging
import re
from typing import Any

from gidgethub import routing, sansio
from repligit.asyncio import fetch_pack, ls_remote, send_pack

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
            except Exception:
                # this catches errors related to processing of webhook events
                log.exception(
                    "Failed to process GitHub webhook event",
                    extra={
                        "event_type": event.event,
                        "delivery_id": event.delivery_id,
                    },
                )


router = GitHubRouter()


# -----------------------------------
# Push Events
# -----------------------------------
@router.register("push", deleted=False)
async def sync_branch(event, gh, gl, gl_user, *arg, **kwargs):
    """Sync the git branch referenced to GitLab."""
    src_repo_url = event.data["repository"]["clone_url"]
    src_fullname = event.data["repository"]["full_name"]
    src_owner, src_repo_name = src_fullname.split("/")
    want_sha = event.data["head_commit"]["id"]
    target_ref = event.data["ref"]

    # skip branches from push events that are also pull requests
    if await gh.get_prs(branch=target_ref):
        return

    repo_config = await get_repo_config(gh, src_fullname, refresh=True)

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    # setup callback webhook on GitLab
    webhook_data = {
        "gh_owner": src_owner,
        "gh_repo": src_repo_name,
        "gh_check": repo_config.check_name,
    }
    await gl.set_webhook(dest_fullname, webhook_data)

    # sync commits from GitHub -> GitLab
    gl_refs = await ls_remote(dest_remote_url)
    have_shas = set(gl_refs.values())
    from_sha = gl_refs.get(target_ref) or ("0" * 40)

    if want_sha in have_shas:
        log.info(
            "Target ref already up-to-date",
            extra={"repo": src_fullname, "target_ref": target_ref},
        )
        return

    packfile = await fetch_pack(
        src_repo_url,
        want_sha,
        have_shas,
    )

    gl_token = await gl.auth.authenticate_user(gl_user)

    log.info(
        "Mirroring refs",
        extra={
            "repo": src_fullname,
            "from_sha": from_sha,
            "want_sha": want_sha,
        },
    )
    await send_pack(
        dest_remote_url,
        target_ref,
        from_sha,
        want_sha,
        packfile,
        username=gl_user,
        password=gl_token,
    )


@router.register("push", deleted=True)
async def remove_branch(event, gh, gl, gl_user, *arg, **kwargs):
    src_fullname = event.data["repository"]["full_name"]
    target_ref = event.data["ref"]

    repo_config = await get_repo_config(gh, src_fullname, refresh=True)

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    gl_refs = await ls_remote(dest_remote_url)
    head_sha = gl_refs.get(target_ref)
    null_sha = "0" * 40

    gl_token = await gl.auth.authenticate_user(gl_user)

    log.info("Deleting ref", extra={"repo": src_fullname, "target_ref": target_ref})
    await send_pack(
        dest_remote_url,
        target_ref,
        head_sha,
        null_sha,
        b"",
        username=gl_user,
        password=gl_token,
    )


# -----------------------------------
# Pull Request Events
# -----------------------------------


async def sync_pr(pull_request, gh, gl, gl_user):
    """Sync the git fork/branch referenced in a PR to GitLab.

    This isn't technically an event handler, but is used a couple different ways in this file.
    """
    pull_request_id = pull_request["number"]

    src_repo_url = pull_request["head"]["repo"]["clone_url"]
    src_fullname = pull_request["head"]["repo"]["full_name"]
    want_sha = pull_request["head"]["sha"]

    # pull requests coming from forks are pushed as branches in the form of
    # pr-<pr-number> instead of as their branch name as conflicts could occur
    # between multiple repositories
    is_pull_request_fork = src_fullname != pull_request["base"]["repo"]["full_name"]
    if is_pull_request_fork:
        target_ref = f"refs/heads/pr-{pull_request_id}"
    else:
        target_ref = f"refs/heads/{pull_request['head']['ref']}"

    # get the repository configuration from .github/hubcast.yml
    repo_config = await get_repo_config(gh, src_fullname)
    if not repo_config.draft_sync and pull_request["draft"]:
        if repo_config.draft_sync_msg:
            await gh.set_check_status(
                want_sha,
                repo_config.check_name,
                "skipped",
                message="Hubcast disables sync for draft PRs.",
            )
        return

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    gl_refs = await ls_remote(dest_remote_url)
    have_shas = set(gl_refs.values())
    from_sha = gl_refs.get(target_ref) or ("0" * 40)

    if want_sha in have_shas:
        log.info(
            "Target ref already up-to-date",
            extra={"repo": src_fullname, "target_ref": target_ref},
        )
        return

    # fetch differential packfile with all new commits
    packfile = await fetch_pack(
        src_repo_url,
        want_sha,
        have_shas,
    )

    gl_token = await gl.auth.authenticate_user(gl_user)

    # upload packfile to gitlab repository
    log.info(
        "Mirroring refs",
        extra={
            "repo": src_fullname,
            "from_sha": from_sha,
            "want_sha": want_sha,
        },
    )
    await send_pack(
        dest_remote_url,
        target_ref,
        from_sha,
        want_sha,
        packfile,
        username=gl_user,
        password=gl_token,
    )


@router.register("pull_request", action="opened")
@router.register("pull_request", action="reopened")
@router.register("pull_request", action="synchronize")
async def sync_pr_event(event, gh, gl, gl_user, *arg, **kwargs):
    """Sync the git fork/branch referenced in a PR to GitLab."""
    pull_request = event.data["pull_request"]
    await sync_pr(pull_request, gh, gl, gl_user)


@router.register("pull_request", action="closed")
async def remove_pr(event, gh, gl, gl_user, *arg, **kwargs):
    pull_request = event.data["pull_request"]
    src_fullname = pull_request["head"]["repo"]["full_name"]

    # if the pull request comes from a fork we should clean up
    # the branch upon closing or merging the PR. However, if the
    # pull request comes from an internal branch we should wait
    # to clean up the branch when the branch is deleted from the
    # internal repository
    is_pull_request_fork = src_fullname != pull_request["base"]["repo"]["full_name"]
    if not is_pull_request_fork:
        return

    pull_request_id = pull_request["number"]
    target_ref = f"refs/heads/pr-{pull_request_id}"

    # get the repository configuration from .github/hubcast.yml
    repo_config = await get_repo_config(gh, src_fullname)

    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    dest_remote_url = f"{gl.instance_url}/{dest_fullname}.git"

    gl_refs = await ls_remote(dest_remote_url)
    head_sha = gl_refs.get(target_ref)
    null_sha = "0" * 40

    gl_token = await gl.auth.authenticate_user(gl_user)

    log.info("Deleting ref", extra={"repo": src_fullname, "target_ref": target_ref})
    await send_pack(
        dest_remote_url,
        target_ref,
        head_sha,
        null_sha,
        b"",
        username=gl_user,
        password=gl_token,
    )


@router.register("issue_comment", action="created")
async def respond_comment(event, gh, gl, gl_user, *arg, **kwargs):
    # differentiate issue vs PR comment
    if "pull_request" not in event.data["issue"]:
        return

    comment = event.data["comment"]["body"]
    response = None
    plus_one = False

    if re.search(f"@{gh.bot_user} help", comment, re.IGNORECASE):
        response = comments.help_message(gh.bot_user)

    elif re.search(f"@{gh.bot_user} approve", comment, re.IGNORECASE):
        # syncs PR changes to the destination on behalf of the commenter
        # this does not handle PR deletions, those will need to be manually cleaned by project maintainers
        pull_request_id = event.data["issue"]["number"]
        pull_request = await gh.get_pr(pull_request_id)
        await sync_pr(pull_request, gh, gl, gl_user)

        # note: the user will see a +1 regardless of whether a sync truly occurred
        plus_one = True

    elif re.search(
        f"@{gh.bot_user} (re[-]?)?(run|start) pipeline", comment, re.IGNORECASE
    ):
        pull_request_id = event.data["issue"]["number"]
        pull_request = await gh.get_pr(pull_request_id)
        # sync the PR in case it fell out of sync
        await sync_pr(pull_request, gh, gl, gl_user)

        # get the branch this PR belongs to
        src_fullname = pull_request["head"]["repo"]["full_name"]
        # pull requests coming from forks are pushed as branches in the form of
        # pr-<pr-number> instead of as their branch name as conflicts could occur
        # between multiple repositories
        is_pull_request_fork = src_fullname != pull_request["base"]["repo"]["full_name"]
        if is_pull_request_fork:
            branch = f"pr-{pull_request_id}"
        else:
            branch = pull_request["head"]["ref"]

        # get the gitlab repo information and run the pipeline
        repo_config = await get_repo_config(gh, src_fullname, refresh=True)
        dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
        pipeline_url = await gl.run_pipeline(dest_fullname, branch)

        if pipeline_url:
            response = f"I've started a new [pipeline]({pipeline_url}) for you!"
            plus_one = True
        else:
            response = "I had a problem starting the pipeline."

    elif re.search(
        f"@{gh.bot_user} restart failed(?:[- ]?jobs)?", comment, re.IGNORECASE
    ):
        pull_request_id = event.data["issue"]["number"]
        pull_request = await gh.get_pr(pull_request_id)
        # if a pipeline failed, we give the user the option to restart any failed jobs
        # we don't want to re-sync the branch, as a new pipeline would be created
        # and would defeat the purpose of individually restarting failed jobs

        # get the branch this PR belongs to
        src_fullname = pull_request["head"]["repo"]["full_name"]
        # pull requests coming from forks are pushed as branches in the form of
        # pr-<pr-number> instead of as their branch name as conflicts could occur
        # between multiple repositories
        is_pull_request_fork = src_fullname != pull_request["base"]["repo"]["full_name"]
        if is_pull_request_fork:
            branch = f"pr-{pull_request_id}"
        else:
            branch = pull_request["head"]["ref"]

        # get the gitlab repo information and run the pipeline
        repo_config = await get_repo_config(gh, src_fullname, refresh=True)
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
        await gh.react_to_comment(event.data["comment"]["id"], "+1")


@router.register("check_run", action="rerequested")
async def rerun_check(event, gh, gl, gl_user, *arg, **kwargs):
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
    repo_config = await get_repo_config(gh, src_fullname, refresh=True)
    dest_fullname = f"{repo_config.dest_org}/{repo_config.dest_name}"
    await gl.run_pipeline(dest_fullname, branch)
