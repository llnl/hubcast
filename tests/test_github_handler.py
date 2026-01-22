# tests for github webhook handler

from unittest.mock import AsyncMock, Mock, patch

import pytest
from gidgethub import sansio

from hubcast.web.github.handler import GitHubHandler
from hubcast.web.github.routes import GitHubRouter

### FIXTURES


@pytest.fixture
def handler():
    """Handler with mocked dependencies."""

    webhook_secret = "secret"
    account_map = Mock(return_value="gitlab_user")
    gh_factory = Mock()
    gh_factory.create_client = Mock(return_value=AsyncMock())
    gl_factory = Mock()
    gl_factory.create_client = Mock(return_value=AsyncMock())

    return GitHubHandler(webhook_secret, account_map, gh_factory, gl_factory)


@pytest.fixture
def mock_request():
    """Mock aiohttp request."""

    request = AsyncMock()
    request.read = AsyncMock(
        return_value=b'{"sender": {"login": "user"}, "repository": {"owner": {"login": "owner"}, "name": "repo"}}'
    )

    request.headers = {
        "X-GitHub-Event": "push",
        "X-GitHub-Delivery": "123",
    }
    return request


@pytest.fixture
def mock_router():
    return GitHubRouter()


### TESTS

# test the handle method


@pytest.mark.asyncio
async def test_handle_valid_webhook(handler, mock_request):
    """Should return 200 for a normal webhook."""

    async def fake_spawn(request, coro):
        """Consume a coroutine so Python doesn't complain."""
        await coro

    with (
        patch("hubcast.web.github.handler.sansio.Event.from_http") as mock_event,
        patch("hubcast.web.github.handler.spawn", side_effect=fake_spawn),
        patch("hubcast.web.github.handler.router.dispatch"),
    ):
        # mock event sent by a user (the account map will always return "gitlab_user")
        mock_event.return_value = Mock(
            event="push",
            delivery_id="123",
            data={
                "sender": {"login": "user"},
                "repository": {"owner": {"login": "owner"}, "name": "repo"},
            },
        )

        response = await handler.handle(mock_request)

        assert response.status == 200


@pytest.mark.asyncio
async def test_handle_unauthorized(handler, mock_request):
    """Should return 200 for an unauthorized user not in the account map."""
    handler.account_map.return_value = None  # simulate unauthorized user

    with patch("hubcast.web.github.handler.sansio.Event.from_http") as mock_event:
        mock_event.return_value = Mock(
            event="push",
            delivery_id="123",
            data={
                "sender": {"login": "user"},
                "repository": {"owner": {"login": "owner"}, "name": "repo"},
            },
        )

        response = await handler.handle(mock_request)

        assert response.status == 200


@pytest.mark.asyncio
async def test_handle_exception(handler, mock_request):
    """Should return 500 if an exception occurs during handling."""

    with patch("hubcast.web.github.handler.sansio.Event.from_http") as mock_event:
        mock_event.side_effect = Exception("something awful happened")

        response = await handler.handle(mock_request)

        assert response.status == 500


# test the router


@pytest.mark.asyncio
async def test_router_callback_dispatch(mock_router):
    """Should call the registered callback for an event."""

    callback1 = AsyncMock()
    callback2 = AsyncMock()

    # register two callbacks for "push" event
    mock_router.register("push")(callback1)
    mock_router.register("push")(callback2)

    event = Mock(spec=sansio.Event)
    event.event = "push"

    # dispatch the mock push event
    await mock_router.dispatch(event, "arg1", "arg2", kwarg1="value1")

    # both callbacks should have been called with the event and additional args
    callback1.assert_called_once_with(event, "arg1", "arg2", kwarg1="value1")
    callback2.assert_called_once_with(event, "arg1", "arg2", kwarg1="value1")


@pytest.mark.asyncio
async def test_router_graceful_exception(mock_router):
    """Should continue dispatching even if one callback fails."""

    callback1 = AsyncMock(side_effect=Exception("error"))
    callback2 = AsyncMock()

    mock_router.register("push")(callback1)
    mock_router.register("push")(callback2)

    event = Mock(spec=sansio.Event)
    event.event = "push"
    # delivery_id is used in logging
    event.delivery_id = "test-123"

    await mock_router.dispatch(event, "arg1", "arg2", kwarg1="value1")

    callback1.assert_called_once_with(event, "arg1", "arg2", kwarg1="value1")
    callback2.assert_called_once_with(event, "arg1", "arg2", kwarg1="value1")


@pytest.mark.asyncio
async def test_router_no_callbacks(mock_router):
    """Should handle events with no registered callbacks without error."""

    event = Mock(spec=sansio.Event)
    event.event = "invalid"

    # no exceptions hopefully
    await mock_router.dispatch(event, "arg1", "arg2", kwarg1="value1")
