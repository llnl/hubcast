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
    "canceled": "cancelled",  # Not a typo, GitHub with two Ls
    "skipped": "skipped",
    "success": "success",
}


class GitLabRouter(routing.Router):
    """
    Custom router to better handle logging of errors
    """

    def register(self, event_type: str, **data_detail: Any):  # type: ignore[override]
        """Register a callback. Relaxes return type to allow dict returns for testing."""
        return super().register(event_type, **data_detail)

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
    check_types: list,
    *args,
    **kwargs,
) -> str | None:
    """Relay status of a GitLab pipeline back to GitHub."""

    pipeline_status = event.data["object_attributes"]["status"]
    status = GITLAB_TO_GITHUB_STATUS.get(pipeline_status)
    if not status:
        return

    pipeline_id = event.data["object_attributes"]["id"]
    pipeline_source = event.data["object_attributes"]["source"]
    project = event.data["project"]["path_with_namespace"]
    sha = event.data["object_attributes"]["sha"]

    is_child_pipeline = pipeline_source == "parent_pipeline"

    event_type = "child-pipelines" if is_child_pipeline else "pipeline"
    if event_type not in check_types:
        return

    if event.data.get("merge_request"):
        # Fetch the pipeline from the API to get the correct ref (which may include /merge suffix)
        pipeline = await gl.get_pipeline(project, pipeline_id)
        ref = pipeline.get("ref", "")

        if ref.endswith("/merge"):
            # MR merge pipelines use a synthetic merge commit, so report the source
            # commit status back to GitHub instead.
            commit_info = await gl.get_commit(project, sha)
            sha = commit_info["parent_ids"][1]

    pipeline_url = event.data["object_attributes"]["url"]

    if is_child_pipeline:
        pipeline_name = event.data["object_attributes"].get("name") or pipeline_id
        name = f"{gh_check_name} / {pipeline_name}"
    else:
        name = gh_check_name

    await gh.set_check_status(
        sha,
        name,
        status,
        title="External pipeline run",
        summary=f"[View this pipeline on {urlparse(pipeline_url).netloc}]({pipeline_url})",
        details_url=pipeline_url,
    )

    return status


@router.register("Job Hook")
async def job_status_relay(
    event: sansio.Event,
    gh: GitHubClient,
    gl: GitLabClient,
    gh_check_name: str,
    check_types: list,
    *args,
    **kwargs,
) -> str | None:
    """Relay status of a GitLab job back to GitHub."""
    job_status = event.data["build_status"]
    status = GITLAB_TO_GITHUB_STATUS.get(job_status)
    if not status:
        return

    project = event.data["project"]["path_with_namespace"]
    ref = event.data.get("ref", "")
    sha = event.data["sha"]

    if ref.startswith("refs/merge-requests/") and ref.endswith("/merge"):
        # MR merge jobs use a synthetic merge commit, so report the source
        # commit status back to GitHub instead.
        commit_info = await gl.get_commit(project, sha)
        sha = commit_info["parent_ids"][1]

    job_id = event.data["build_id"]
    job_name = event.data["build_name"]

    if "child-pipelines" in check_types:
        pipeline_id = event.data["pipeline_id"]
        pipeline = await gl.get_pipeline(project, pipeline_id)

        pipeline_source = pipeline.get("source", "")
        if pipeline_source == "parent_pipeline":
            pipeline_name = pipeline.get("name") or pipeline_id
            job_name = f"{pipeline_name} / {job_name}"

    repository_url = event.data["project"]["web_url"]
    job_url = f"{repository_url}/-/jobs/{job_id}"

    name = f"{gh_check_name} / {job_name}" if gh_check_name else job_name

    await gh.set_check_status(
        sha,
        name,
        status,
        title="External job run",
        summary=f"[View this job on {urlparse(job_url).netloc}]({job_url})",
        details_url=job_url,
    )

    return status
