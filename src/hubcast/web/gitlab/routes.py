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
    # get ref from event
    ref = event.data["object_attributes"]["sha"]

    # GitLab creates two types of MR pipelines:
    # - regular: event.commit.id is the actual source commit
    # - merged results: event.commit.id is a synthetic merge commit
    # we cannot reliably distinguish between these two types from the webhook payload
    # without making an API call, so we fetch the source branch HEAD to update the GitHub check
    # associated with the source commit.

    is_mr_event = (
        event.data["object_attributes"]["source"] == "merge_request_event"
        and "merge_request" in event.data
    )
    if is_mr_event:
        source_branch = event.data["merge_request"]["source_branch"]
        gl_fullname = event.data["project"]["path_with_namespace"]
        ref = await gl.get_branch_head(gl_fullname, source_branch)

    # modify check name based on the pipeline source
    if create_mr:
        suffix = "merge request" if is_mr_event else "branch"
    name = f"{gh_check_name} [{suffix}]" if suffix else gh_check_name

    # get status from event
    pipeline_status = event.data["object_attributes"]["status"]
    pipeline_url = event.data["object_attributes"]["url"]

    status = GITLAB_TO_GITHUB_STATUS.get(pipeline_status)

    if status:
        await gh.set_check_status(
            ref, name,
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
    *arg,
    **kwargs,
) -> None:
    """Relay status of a GitLab job back to GitHub."""
    # get ref from event
    ref = event.data["sha"]

    job_id = event.data["build_id"]
    job_name = event.data["build_name"]
    job_status = event.data["build_status"]

    repository_url = event.data["project"]["web_url"]
    job_url = f"{repository_url}/-/jobs/{job_id}"

    name = f"{gh_check_name} / {job_name}" if gh_check_name else job_name
    status = GITLAB_TO_GITHUB_STATUS.get(job_status)

    if status:
        await gh.set_check_status(
            ref,
            name,
            status,
            title="External job run",
            summary=f"[View this job on {urlparse(job_url).netloc}]({job_url})",
            details_url=job_url,
        )
