import jwt
import pytest

from hubcast.webhook import RoutingToken, RoutingTokenError


@pytest.fixture
def token_data():
    """Default routing token data."""
    return {
        "gh_owner": "owner",
        "gh_repo": "repo",
        "gh_check": "gitlab-ci",
    }


@pytest.fixture
def secret():
    """Webhook secret for signing."""
    return "test-secret-key"


class TestRoutingToken:
    def test_encode_decode_roundtrip(self, token_data, secret):
        """Should encode and decode token successfully."""
        token = RoutingToken(**token_data)
        encoded = token.encode(secret)
        decoded = RoutingToken.decode(secret, encoded)

        assert decoded.gh_owner == token_data["gh_owner"]
        assert decoded.gh_repo == token_data["gh_repo"]
        assert decoded.gh_check == token_data["gh_check"]

    def test_decode_invalid_signature(self, token_data, secret):
        """Should raise RoutingTokenError for invalid signature."""
        token = RoutingToken(**token_data)
        encoded = token.encode(secret)

        with pytest.raises(RoutingTokenError, match="Invalid routing token"):
            RoutingToken.decode("wrong-secret", encoded)

    def test_decode_malformed_token(self, secret):
        """Should raise RoutingTokenError for malformed JWT."""
        with pytest.raises(RoutingTokenError, match="Invalid routing token"):
            RoutingToken.decode(secret, "not-a-jwt-token")

    def test_decode_missing_fields(self, secret):
        """Should raise RoutingTokenError when required fields are missing."""
        incomplete_data = {"gh_owner": "owner"}
        token_str = jwt.encode(incomplete_data, secret, algorithm="HS256")

        with pytest.raises(RoutingTokenError, match="validation failed"):
            RoutingToken.decode(secret, token_str)

    def test_decode_extra_fields_rejected(self, token_data, secret):
        """Should raise RoutingTokenError when extra fields are present."""
        data_with_extra = {**token_data, "extra_field": "value"}
        token_str = jwt.encode(data_with_extra, secret, algorithm="HS256")

        with pytest.raises(RoutingTokenError, match="validation failed"):
            RoutingToken.decode(secret, token_str)

    def test_token_immutable(self, token_data):
        """Should not allow modification of token fields."""
        token = RoutingToken(**token_data)
        with pytest.raises(Exception):
            token.gh_owner = "new-owner"

    def test_encode_basic_fields(self, secret):
        """Should encode and decode all basic fields correctly."""
        token = RoutingToken(
            gh_owner="owner",
            gh_repo="repo",
            gh_check="gitlab-ci",
        )
        encoded = token.encode(secret)
        decoded = RoutingToken.decode(secret, encoded)

        assert decoded.gh_owner == "owner"
        assert decoded.gh_repo == "repo"
        assert decoded.gh_check == "gitlab-ci"
