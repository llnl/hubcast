from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator


class RepoConfig(BaseModel):
    """Repository configuration for mirroring and status checks"""

    model_config = ConfigDict(frozen=True, extra="ignore")

    # destination org and repository to sync into
    dest_org: str
    dest_name: str

    # name of the CI check that is reported back the the source
    check_name: str = "gitlab-ci"

    # Whether or not to delete PR branches when the corresponding PR
    # is closed or merged (default is True)
    delete_closed: bool = True

    # Whether or not to sync draft PRs (default is True)
    sync_drafts: bool = True
    sync_drafts_msg: bool = True

    # Allow users to control the granularity of checks reported to GitHub
    # via setting either "pipeline" or "job"
    status_type: Literal["pipeline", "job"] = "pipeline"

    # TODO: create GitLab MRs that mirror GitHub PRs to allow users to test
    # synthetic merge commits between the branch and the default branch
    create_mr: bool = False

    @model_validator(mode="before")
    @classmethod
    def extract_repo_section(cls, data: Any) -> Any:
        """Extract the 'Repo' key from the YAML structure.

        Raises:
            ValueError: If data is a dict but missing the 'Repo' key
        """
        if isinstance(data, dict):
            if "Repo" not in data:
                raise ValueError("Configuration must have a top-level 'Repo' section")
            return data["Repo"]

        # fallback to Pydantic's other validators if the input data isn't a dict
        return data
