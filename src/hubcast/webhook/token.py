from typing import Annotated, Literal

import jwt
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from hubcast.exceptions import HubcastError

# If this is changed we should add the previous value to the decode
# method's list to allow for backwards compatibility while webhooks
# are migrated over time
JWT_ALGORITHM = "HS256"


class RoutingTokenError(HubcastError):
    """Raised when routing token validation fails."""


class GitHubRoutingToken(BaseModel):
    """Routing token for a GitHub source repository."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # tokens created before GL->GL do not have an src_forge field, this is handled in decode_routing_token
    src_forge: Literal["github"] = "github"

    gh_owner: str
    gh_repo: str
    gh_check: str

    check_types: list[Literal["pipeline", "child-pipelines", "jobs"]] = ["pipeline"]


class GitLabRoutingToken(BaseModel):
    """Routing token for a GitLab source repository."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    src_forge: Literal["gitlab"] = "gitlab"

    gl_repo_id: int  # identify GL project by numerical ID
    gl_check: str

    check_types: list[Literal["pipeline", "child-pipelines", "jobs"]] = ["pipeline"]


RoutingToken = Annotated[
    GitHubRoutingToken | GitLabRoutingToken, Field(discriminator="src_forge")
]
_routing_token_adapter: TypeAdapter[GitHubRoutingToken | GitLabRoutingToken] = (
    TypeAdapter(RoutingToken)
)


def encode_routing_token(
    token: GitHubRoutingToken | GitLabRoutingToken, secret: str
) -> str:
    """Generate a cryptographically signed JWT token.

    Args:
        token: The routing token to encode
        secret: HMAC signing key

    Returns:
        JWT token signed with HMAC-SHA256
    """
    return jwt.encode(token.model_dump(), secret, algorithm=JWT_ALGORITHM)


def decode_routing_token(
    secret: str, token: str
) -> GitHubRoutingToken | GitLabRoutingToken:
    """Validate and decode a JWT routing token.

    Args:
        secret: HMAC signing key (must match the key used for encoding)
        token: The JWT token string to validate

    Returns:
        GitHubRoutingToken or GitLabRoutingToken, depending on src_forge

    Raises:
        RoutingTokenError: If the token is malformed, signature is invalid,
                          or payload is missing required fields
    """
    try:
        payload_dict = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    except jwt.InvalidTokenError as e:
        raise RoutingTokenError(
            f"Invalid routing token: {e}",
            log_level="WARNING",
        ) from e

    # pydantic's validation for discriminated unions (GL/GH routing tokens)
    # require the discriminator key (src_forge) to be in the input (which is not true for tokens created before GL-GL)
    # it won't fall back to the model default, so we need to inject it here
    payload_dict.setdefault("src_forge", "github")

    try:
        return _routing_token_adapter.validate_python(payload_dict)
    except ValidationError as e:
        raise RoutingTokenError(
            f"Routing token validation failed: {e}",
            log_level="WARNING",
        ) from e
