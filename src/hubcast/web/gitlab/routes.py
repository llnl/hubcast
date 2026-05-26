import logging
from typing import Any
from urllib.parse import urlparse

from gidgetlab import routing, sansio

from hubcast.clients.github.client import GitHubClient
from hubcast.clients.gitlab.client import GitLabClient
from hubcast.exceptions import HubcastError

log = logging.getLogger(__name__)

# https://docs.github.com/en/rest/guides/using-the-rest-api-to-interact-with-checks#about-check-suites
# https://docs.gitlab.com/api/pipelines/#list-project-pipelines -> status description
# not mapping all statuses to avoid churn in posting updates
GITLAB_TO_GITHUB_STATUS = {
    "pending": "queued",
    "running": "in_progress",
    "failed": "failure",
    "canceled": "cancelled",
    "skipped": "skipped",
    "success": "success",
}


class GitLabRouter(routing.Router):
    """
    Custom router to better handle logging of errors
    """

    async def dispatch(self, event: sansio.Event, *args: Any, **kwargs: Any) -> None:
        try:
            await super().dispatch(event, *args, **kwargs)
        except HubcastError as e:
            e.log(log)
        except Exception:
            log.exception("Failed to process GitLab webhook event")


router = GitLabRouter()

# STATUS RELAYS

# To post status back to GitHub, we need to find the sha of the source commit from GitLab.
# This is trivial for regular pipelines but requires extra checks for MR pipelines.
# GitLab creates two types of MR pipelines:
# - regular: pipeline_sha is the source branch HEAD
# - merged results: pipeline_sha is a synthetic merge commit whose parents are [target HEAD, source HEAD]


@router.register("Pipeline Hook")
async def pipeline_status_relay(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gh_check_name: str,
    create_mr: bool,
    *args,
    **kwargs,
) -> None:
    """Relay status of a GitLab pipeline back to GitHub."""
    pipeline_status = event.data["object_attributes"]["status"]
    status = GITLAB_TO_GITHUB_STATUS.get(pipeline_status)
    if not status:
        return

    sha = event.data["object_attributes"]["sha"]
    project = event.data["project"]["path_with_namespace"]

    if not event.data.get("merge_request"):
        commit, pipeline_type = sha, "non-mr-branch"
    else:
        # to distinguish between the MR pipelines, we need to fetch the pipeline details
        # and check the ref's suffix
        pipeline_info = await gl.get_pipeline(
            project, event.data["object_attributes"]["id"]
        )

        if pipeline_info["ref"].endswith("/head"):
            commit, pipeline_type = sha, "branch"
        elif pipeline_info["ref"].endswith("/merge"):
            # API call to extract source HEAD
            commit_info = await gl.get_commit(project, sha)
            commit, pipeline_type = commit_info["parent_ids"][1], "merge request"

    name = f"{gh_check_name} [{pipeline_type}]" if create_mr else gh_check_name
    pipeline_url = event.data["object_attributes"]["url"]

    await gh.set_check_status(
        commit,
        name,
        status,
        title="External pipeline run",
        summary=f"[View this pipeline on {urlparse(pipeline_url).netloc}]({pipeline_url})",
        details_url=pipeline_url,
    )


@router.register("Job Hook")
async def job_status_relay(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gh_check_name: str,
    create_mr: bool,
    *args,
    **kwargs,
) -> None:
    """Relay status of a GitLab job back to GitHub."""
    job_status = event.data["build_status"]
    status = GITLAB_TO_GITHUB_STATUS.get(job_status)
    if not status:
        return

    sha = event.data["sha"]
    project = event.data["project"]["path_with_namespace"]
    ref = event.data.get("ref", "")
    is_mr_event = ref.startswith("refs/merge-requests/")

    if not is_mr_event:
        commit, pipeline_type = sha, "non-mr-branch"
    elif ref.endswith("/head"):
        commit, pipeline_type = sha, "branch"
    elif ref.endswith("/merge"):
        # API call to extract source HEAD
        commit_info = await gl.get_commit(project, sha)
        commit, pipeline_type = commit_info["parent_ids"][1], "merge request"

    job_id = event.data["build_id"]
    job_name = event.data["build_name"]

    repository_url = event.data["project"]["web_url"]
    job_url = f"{repository_url}/-/jobs/{job_id}"

    name = f"{gh_check_name} / {job_name}" if gh_check_name else job_name
    name = f"{name} [{pipeline_type}]" if create_mr else name

    await gh.set_check_status(
        commit,
        name,
        status,
        title="External job run",
        summary=f"[View this job on {urlparse(job_url).netloc}]({job_url})",
        details_url=job_url,
    )
