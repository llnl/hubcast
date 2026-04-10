from dataclasses import MISSING, dataclass, fields
from typing import Any


@dataclass(slots=True, frozen=True)
class RepoConfig:
    """Configuration for a GitHub repository's GitLab sync settings."""

    dest_org: str  # GitLab destination organization
    dest_name: str  # GitLab destination repository name
    check_name: str = "gitlab-ci"  # Name of the GitHub check to create
    check_type: str = "pipeline"  # TODO: Type of check (not yet used)
    create_mr: bool = (
        False  # TODO: Whether to create merge requests (not yet implemented)
    )
    delete_closed: bool = True  # Whether to delete branches for closed PRs
    sync_drafts: bool = True  # Whether to sync draft pull requests
    sync_drafts_msg: bool = True  # Whether to show message when skipping drafts

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
