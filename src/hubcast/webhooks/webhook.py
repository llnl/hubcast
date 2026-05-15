import jwt
from pydantic import BaseModel, ConfigDict, ValidationError

from hubcast.exceptions import HubcastError

# If this is changed we should add the previous value to the decode
# method's list to allow for backwards compatibility while webhooks
# are migrated over time
JWT_ALGORITHM = "HS256"


class WebhookValidationError(HubcastError):
    """Raised when webhook data validation fails."""


class WebhookData(BaseModel):
    """JWT webhook data for encoding GitHub routing information.

    This data serves as the GitLab webhook secret payload and encodes routing
    information (GitHub owner, repo, check name) in a tamper-proof JWT format.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    gh_owner: str
    gh_repo: str
    gh_check: str
    create_mr: bool = False

    def encode(self, secret: str) -> str:
        """Generate a cryptographically signed JWT token.

        Args:
            secret: HMAC signing key

        Returns:
            JWT token signed with HMAC-SHA256
        """
        return jwt.encode(self.model_dump(), secret, algorithm=JWT_ALGORITHM)

    @classmethod
    def decode(cls, secret: str, token: str) -> "WebhookData":
        """Validate and decode a JWT webhook token.

        Args:
            secret: HMAC signing key (must match the key used for encoding)
            token: The JWT token string to validate

        Returns:
            WebhookData instance with validated fields

        Raises:
            WebhookValidationError: If the token is malformed, signature is invalid,
                                    or payload is missing required fields
        """
        try:
            payload_dict = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
        except jwt.InvalidTokenError as e:
            raise WebhookValidationError(
                f"Invalid webhook token: {e}",
                log_level="WARNING",
            ) from e

        try:
            return cls.model_validate(payload_dict)
        except ValidationError as e:
            raise WebhookValidationError(
                f"Webhook data validation failed: {e}",
                log_level="WARNING",
            ) from e
