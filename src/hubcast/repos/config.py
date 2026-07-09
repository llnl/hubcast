from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

# path to the hubcast config file within a repository, relative to its root
HUBCAST_CONFIG_PATH = ".github/hubcast.yml"


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
    # via setting one or more of "pipeline", "child-pipelines" and/or "jobs"
    check_types: list[Literal["pipeline", "child-pipelines", "jobs"]] = ["pipeline"]

    # Create GitLab MRs that mirror GitHub PRs to allow users to test
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

    @model_validator(mode="after")
    def require_pipeline_check(self) -> "RepoConfig":
        """Ensure the "pipeline" check is always enabled, regardless of user config. This is used to pass error messages back to the user."""
        if "pipeline" not in self.check_types:
            object.__setattr__(self, "check_types", [*self.check_types, "pipeline"])
        return self
