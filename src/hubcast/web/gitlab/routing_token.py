import jwt

from hubcast.exceptions import HubcastError

# Old algorithms should be kept in the list for a couple releases to
# give instances time to migrate webhooks over time
JWT_ALGORITHMS = ["HS256"]


class RoutingTokenError(HubcastError):
    """Raised when routing token validation fails."""


def validate_routing_token(secret: str, token: str) -> dict[str, str]:
    """Validate a JWT routing token and extract its payload.

    Args:
        secret: HMAC signing key (must match the key used for generation)
        token: The JWT token string to validate

    Returns:
        Dictionary with keys: gh_owner, gh_repo, gh_check

    Raises:
        RoutingTokenError: If the token is malformed, signature is invalid,
                          or payload is missing required fields
    """
    try:
        payload = jwt.decode(token, secret, algorithms=JWT_ALGORITHMS)
    except jwt.InvalidTokenError as e:
        raise RoutingTokenError(
            f"Invalid routing token: {e}",
            log_level="WARNING",
        ) from e

    # Validate required fields are present
    required_fields = {"gh_owner", "gh_repo", "gh_check"}
    missing_fields = required_fields - payload.keys()
    if missing_fields:
        raise RoutingTokenError(
            f"Routing token payload missing required fields: {', '.join(sorted(missing_fields))}",
            log_level="WARNING",
            missing_fields=sorted(missing_fields),
        )

    return payload
