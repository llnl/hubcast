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
    "created": "queued",
    "pending": "queued",
    "manual": "queued",
    "running": "in_progress",
    "failed": "failure",
    "canceled": "cancelled",
    "skipped": "skipped",
    "success": "success",
}


class GitLabRouter(routing.Router):
    """
    Custom router to handle common interactions for hubcast
    """

    async def dispatch(self, event: sansio.Event, *args: Any, **kwargs: Any) -> None:
        """Dispatch an event to all registered function(s)."""

        found_callbacks = []
        try:
            found_callbacks.extend(self._shallow_routes[event.event])
        except KeyError:
            pass
        try:
            details = self._deep_routes[event.event]
        except KeyError:
            pass
        else:
            for data_key, data_values in details.items():
                if data_key in event.object_attributes:
                    event_value = event.object_attributes[data_key]
                    if event_value in data_values:
                        found_callbacks.extend(data_values[event_value])
        for callback in found_callbacks:
            try:
                await callback(event, *args, **kwargs)
            except HubcastError as e:
                e.log(log, event_type=event.event)
            except Exception:
                log.exception(
                    "Failed to process GitLab webhook event",
                    extra={
                        "event_type": event.event,
                    },
                )


router = GitLabRouter()


async def _resolve_source_commit(
    gl: GitLabClient,
    project_path: str,
    pipeline_sha: str,
) -> tuple[str, str]:
    """
    To post status back to GitHub, we need to find the sha of the source commit from GitLab.
    This is trivial for regular pipelines but requires extra checks for MR pipelines.

    Args:
        gl: GitLab client for API calls
        project_path: the project namespace and name
        pipeline_sha: the commit SHA associated with the pipeline

    Returns:
        Tuple of (source_commit_sha, pipeline_type)
        - source_commit_sha: The SHA to use for GitHub status updates
        - pipeline_type: "branch", "merge request", or "merged results"
    """

    # GitLab creates two types of MR pipelines:
    # - regular: pipeline_sha is the source branch HEAD
    # - merged results: pipeline_sha is a synthetic merge commit whose parents are [target HEAD, source HEAD]
    # The regular MR pipeline is testing the same commit as a branch pipeline.
    # However, we can't distinguish between the two MR pipeline types from the pipeline webhook payload.

    commit_info = await gl.get_commit(project_path, pipeline_sha)
    parents = commit_info["parent_ids"]

    # Merged results pipelines: parent_ids == [target HEAD, source HEAD]
    # Regular MR pipelines: parent_ids == [previous source commit];
    #   the pipeline SHA itself is already source HEAD.
    if len(parents) == 2:
        return parents[1], "merged results"
    return pipeline_sha, "merge request"


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
    sha = event.data["object_attributes"]["sha"]
    project = event.data["project"]["path_with_namespace"]

    if not event.data.get("merge_request"):
        commit, pipeline_type = sha, "branch"
    else:
        # could be either regular MR pipeline or merged results, need to make API call to check
        commit, pipeline_type = await _resolve_source_commit(gl, project, sha)

    name = f"{gh_check_name} [{pipeline_type}]" if create_mr else gh_check_name

    # get status from event
    pipeline_status = event.data["object_attributes"]["status"]
    pipeline_url = event.data["object_attributes"]["url"]

    status = GITLAB_TO_GITHUB_STATUS.get(pipeline_status)

    if status:
        await gh.set_check_status(commit, name,
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
    sha = event.data["sha"]
    project = event.data["project"]["path_with_namespace"]
    ref = event.data.get("ref", "")
    is_mr_event = ref.startswith("refs/merge-requests/")

    if not is_mr_event:
        commit, pipeline_type = sha, "branch"
    elif ref.endswith("/head"):
        # regular MR pipeline; job hook exposes the type, no API call needed
        commit, pipeline_type = sha, "merge request"
    elif ref.endswith("/merge"):
        # merged results pipeline; need API call to extract source HEAD
        commit, pipeline_type = await _resolve_source_commit(gl, project, sha)

    job_id = event.data["build_id"]
    job_name = event.data["build_name"]
    job_status = event.data["build_status"]

    repository_url = event.data["project"]["web_url"]
    job_url = f"{repository_url}/-/jobs/{job_id}"

    name = f"{gh_check_name} / {job_name}" if gh_check_name else job_name
    name = f"{name} [{pipeline_type}]" if create_mr else name

    status = GITLAB_TO_GITHUB_STATUS.get(job_status)

    if status:
        await gh.set_check_status(commit,
            name,
            status,
            title="External job run",
            summary=f"[View this job on {urlparse(job_url).netloc}]({job_url})",
            details_url=job_url,
        )
