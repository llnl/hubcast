from dataclasses import MISSING, dataclass, fields
from typing import Any


@dataclass(slots=True, frozen=True)
class RepoConfig:
    """Configuration for a GitHub repository's GitLab sync settings."""

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

    # TODO: allow users to control the granularity of checks reported to GitHub
    # via setting either "pipeline" or "job"
    check_type: str = "pipeline"

    # TODO: create GitLab MRs that mirror GitHub PRs to allow users to test
    # synthetic merge commits between the branch and the default branch
    create_mr: bool = False

    @classmethod
    def from_yaml_data(cls, repo_data: dict[str, Any]) -> "RepoConfig":
        """Create a RepoConfig from YAML data, using field defaults for missing values.

        Args:
            repo_data: Dictionary containing configuration values from YAML

        Returns:
            RepoConfig instance

        Raises:
            ValueError: If required fields are missing
        """
        # Get required fields (those without defaults)
        required_fields = {
            f.name
            for f in fields(cls)
            if f.default is MISSING and f.default_factory is MISSING
        }
        missing = required_fields - repo_data.keys()
        if missing:
            raise ValueError(f"Missing required fields: {', '.join(sorted(missing))}")

        # Build kwargs from YAML data, using only fields that exist in the dataclass
        field_names = {f.name for f in fields(cls)}
        kwargs = {key: value for key, value in repo_data.items() if key in field_names}

        return cls(**kwargs)
