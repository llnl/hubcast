# tests for gitlab webhook handler

from unittest.mock import AsyncMock, Mock, patch

import pytest
from gidgetlab import sansio

from hubcast.web.gitlab.handler import GitLabHandler
from hubcast.web.gitlab.routes import GitLabRouter

### FIXTURES


async def fake_spawn(request, coro):
    """Consume coroutine to avoid warnings."""
    await coro


@pytest.fixture
def handler():
    """Handler with mocked dependencies."""

    webhook_secret = "secret"
    github_client_factory = Mock()
    github_client_factory.create_client = Mock(return_value=AsyncMock())
    return GitLabHandler(webhook_secret, github_client_factory)


@pytest.fixture
def mock_request():
    """Mock aiohttp request."""

    request = AsyncMock()
    request.read = AsyncMock(
        return_value=b'{"object_attributes": {"status": "success"}}'
    )

    request.headers = {
        "x-gitlab-event": "Pipeline Hook",
        "x-gitlab-token": "valid-token",
    }

    request.rel_url.query = {}
    return request


@pytest.fixture
def mock_router():
    return GitLabRouter()


### TESTS

# test the handle method in GitLabHandler


@pytest.mark.asyncio
async def test_handle_valid_webhook(handler, mock_request):
    """Should return 200 for a normal webhook."""

    with (
        patch("hubcast.web.gitlab.handler.RoutingToken.decode") as mock_decode,
        patch("hubcast.web.gitlab.handler.sansio.Event.from_http") as mock_event,
        patch("hubcast.web.gitlab.handler.spawn", side_effect=fake_spawn),
        patch("hubcast.web.gitlab.handler.router.dispatch", new_callable=AsyncMock),
    ):
        # Mock routing token validation
        mock_routing_token = Mock()
        mock_routing_token.gh_owner = "owner"
        mock_routing_token.gh_repo = "repo"
        mock_routing_token.gh_check = "gitlab-ci"
        mock_decode.return_value = mock_routing_token

        mock_event.return_value = Mock(
            event="Pipeline Hook",
            data={
                "object_attributes": {
                    "status": "success",
                    "sha": "abc123",
                    "url": "https://gitlab.com/pipeline/123",
                }
            },
        )

        response = await handler.handle(mock_request)
        assert response.status == 200


@pytest.mark.asyncio
async def test_handle_exception(handler, mock_request):
    """Should return 500 if an exception occurs."""

    with (
        patch("hubcast.web.gitlab.handler.RoutingToken.decode") as mock_decode,
        patch("hubcast.web.gitlab.handler.sansio.Event.from_http") as mock_event,
    ):
        # Mock routing token validation
        mock_routing_token = Mock()
        mock_routing_token.gh_owner = "owner"
        mock_routing_token.gh_repo = "repo"
        mock_routing_token.gh_check = "gitlab-ci"
        mock_decode.return_value = mock_routing_token

        mock_event.side_effect = Exception("bug")
        response = await handler.handle(mock_request)
        assert response.status == 500


@pytest.mark.asyncio
async def test_handle_validation_failure(handler, mock_request):
    """Should return 401 for an invalid routing token."""

    from hubcast.webhook import RoutingTokenError

    mock_request.headers = {
        "x-gitlab-event": "Pipeline Hook",
        "x-gitlab-token": "invalid-token",
    }

    with patch("hubcast.web.gitlab.handler.RoutingToken.decode") as mock_decode:
        # Simulate token validation failure
        mock_decode.side_effect = RoutingTokenError("Invalid token signature")
        response = await handler.handle(mock_request)

    assert response.status == 401


@pytest.mark.asyncio
async def test_handle_query_params(handler, mock_request):
    """Should extract GitHub repo info from routing token."""

    with (
        patch("hubcast.web.gitlab.handler.RoutingToken.decode") as mock_decode,
        patch("hubcast.web.gitlab.handler.sansio.Event.from_http") as mock_event,
        patch("hubcast.web.gitlab.handler.spawn", side_effect=fake_spawn),
        patch("hubcast.web.gitlab.handler.router.dispatch", new_callable=AsyncMock),
    ):
        # Mock routing token validation with specific owner/repo
        mock_routing_token = Mock()
        mock_routing_token.gh_owner = "owner"
        mock_routing_token.gh_repo = "repo"
        mock_routing_token.gh_check = "gitlab-ci"
        mock_decode.return_value = mock_routing_token

        # just a basic event
        mock_event.return_value = Mock(
            event="Pipeline Hook", data={"object_attributes": {"status": "success"}}
        )

        response = await handler.handle(mock_request)

        assert response.status == 200
        # the gh factory should be called with the correct owner and repo (from routing token)
        handler.github_client_factory.create_client.assert_called_once_with(
            "owner", "repo"
        )


# test the router


@pytest.mark.asyncio
async def test_router_callback_dispatch(mock_router):
    """Should call the registered callback for an event."""

    callback1 = AsyncMock()
    callback2 = AsyncMock()

    # one shallow callback and one with a status condition (deep match)
    mock_router.register("Pipeline Hook")(callback1)
    mock_router.register("Pipeline Hook", status="success")(callback2)

    event = Mock(spec=sansio.Event)
    event.event = "Pipeline Hook"
    event.object_attributes = {"status": "success"}

    await mock_router.dispatch(event, "arg1", kwarg="value")

    # both callbacks should be called
    callback1.assert_called_once_with(event, "arg1", kwarg="value")
    callback2.assert_called_once_with(event, "arg1", kwarg="value")


@pytest.mark.asyncio
async def test_router_graceful_exception(mock_router):
    """Should continue dispatching even if one callback fails."""

    callback1 = AsyncMock(side_effect=Exception("atrocious error"))
    callback2 = AsyncMock()

    mock_router.register("Pipeline Hook")(callback1)
    mock_router.register("Pipeline Hook")(callback2)

    event = Mock(spec=sansio.Event)
    event.event = "Pipeline Hook"
    event.object_attributes = {}

    await mock_router.dispatch(event)

    callback1.assert_called_once()
    callback2.assert_called_once()


@pytest.mark.asyncio
async def test_router_no_callbacks(mock_router):
    """Should handle event with no registered callbacks without error."""

    event = Mock(spec=sansio.Event)
    event.event = "butterfly"
    event.object_attributes = {}

    # no exceptions expected
    await mock_router.dispatch(event)
