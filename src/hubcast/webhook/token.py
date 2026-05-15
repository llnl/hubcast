import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from hubcast.exceptions import HubcastError

# If this is changed we should add the previous value to the decode
# method's list to allow for backwards compatibility while webhooks
# are migrated over time
JWT_ALGORITHM = "HS256"


class RoutingTokenError(HubcastError):
    """Raised when routing token validation fails."""


class RoutingToken(BaseModel):
    """JWT routing token for encoding GitHub routing information.

    This token serves as the GitLab webhook secret and encodes routing information
    (GitHub owner, repo, check name) in a tamper-proof JWT format.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gh_owner: str
    gh_repo: str
    gh_check: str

    def encode(self, secret: str) -> str:
        """Generate a cryptographically signed JWT token.

        Args:
            secret: HMAC signing key

        Returns:
            JWT token signed with HMAC-SHA256
        """
        return jwt.encode(self.model_dump(), secret, algorithm=JWT_ALGORITHM)

    @classmethod
    def decode(cls, secret: str, token: str) -> "RoutingToken":
        """Validate and decode a JWT routing token.

        Args:
            secret: HMAC signing key (must match the key used for encoding)
            token: The JWT token string to validate

        Returns:
            RoutingToken instance with validated fields

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

        try:
            return cls.model_validate(payload_dict)
        except ValidationError as e:
            raise RoutingTokenError(
                f"Routing token validation failed: {e}",
                log_level="WARNING",
            ) from e
