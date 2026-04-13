import jwt


class RoutingTokenError(Exception):
    """Raised when routing token validation fails."""


def generate_routing_token(
    secret: str, gh_owner: str, gh_repo: str, gh_check: str
) -> str:
    """Generate a cryptographically signed routing token using JWT.

    This token serves as the GitLab webhook secret and encodes routing information
    (GitHub owner, repo, check name) in a tamper-proof JWT format.

    Args:
        secret: HMAC signing key
        gh_owner: GitHub repository owner
        gh_repo: GitHub repository name
        gh_check: GitHub check name to report status to

    Returns:
        JWT token signed with HMAC-SHA256
    """
    payload = {
        "gh_owner": gh_owner,
        "gh_repo": gh_repo,
        "gh_check": gh_check,
    }

    return jwt.encode(payload, secret, algorithm="HS256")


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
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as e:
        raise RoutingTokenError(f"Invalid token: {e}") from e

    # Validate required fields are present
    required_fields = {"gh_owner", "gh_repo", "gh_check"}
    missing_fields = required_fields - payload.keys()
    if missing_fields:
        raise RoutingTokenError(
            f"Payload missing required fields: {', '.join(sorted(missing_fields))}"
        )

    return {
        "gh_owner": payload["gh_owner"],
        "gh_repo": payload["gh_repo"],
        "gh_check": payload["gh_check"],
    }
