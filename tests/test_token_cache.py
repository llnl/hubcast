# tests for the token cache utility used in the gitlab and github clients

import time
from unittest.mock import AsyncMock

import pytest

from hubcast.clients.utils import TokenCache


@pytest.mark.asyncio
async def test_token_new_token_first_call():
    """Should call renew function and return token on first call."""

    cache = TokenCache()

    async def renew():
        return (time.time() + 3600, "new-token-123")

    token = await cache.get("test-token", renew)

    assert token == "new-token-123"


@pytest.mark.asyncio
async def test_token_cached_token_within_validity():
    """Should return cached token if still valid."""

    cache = TokenCache()
    renew_mock = AsyncMock(return_value=(time.time() + 3600, "token-123"))

    token1 = await cache.get("test-token", renew_mock)  # should call renew
    token2 = await cache.get("test-token", renew_mock)  # cache hit

    assert token1 == "token-123"
    assert token2 == "token-123"
    renew_mock.assert_called_once()


@pytest.mark.asyncio
async def test_token_renew_expired_token():
    """Should call renew if cached token is expired."""

    cache = TokenCache()

    # "current" token is already expired
    async def renew_old():
        return (time.time() - 100, "old-token")

    # first call should create old token
    token1 = await cache.get("test-token", renew_old)
    assert token1 == "old-token"

    # second call should create new token since old one is expired
    async def renew_new():
        return (time.time() + 3600, "new-token")

    token2 = await cache.get("test-token", renew_new)
    assert token2 == "new-token"


@pytest.mark.asyncio
async def test_token_renew_within_window():
    """Should call renew if cached token expires within time_needed window."""

    cache = TokenCache()

    # expiring token in 30 seconds
    async def renew_expiring_soon():
        return (time.time() + 30, "expiring-token")

    token1 = await cache.get("test-token", renew_expiring_soon, time_needed=60)
    assert token1 == "expiring-token"

    # we need 60 seconds, so should renew
    async def renew_fresh():
        return (time.time() + 3600, "fresh-token")

    token2 = await cache.get("test-token", renew_fresh, time_needed=60)
    assert token2 == "fresh-token"


@pytest.mark.asyncio
async def test_token_renew_zero_time_needed():
    """Should not renew if time_needed is zero and token is valid."""

    cache = TokenCache()

    # expires in 5 seconds
    async def renew():
        return (time.time() + 5, "token-123")

    token = await cache.get("test-token", renew, time_needed=0)

    # should not renew since time_needed is 0
    assert token == "token-123"
