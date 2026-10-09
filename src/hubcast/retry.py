import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")

# extra attempts after the first; set from HC_RETRIES at startup
retries: int = 3


def retry_delay(name: str, attempt: int, reason: str) -> float:
    """
    Calculate the delay for a retry attempt (exponential backoff) and log the attempt.
    """
    delay = 2**attempt
    log.warning(
        f"{name} failed, retrying",
        extra={
            "attempt": attempt + 1,
            "max_attempts": retries + 1,
            "reason": reason,
            "delay": delay,
        },
    )
    return delay


async def retry_async(
    func: Callable[[], Awaitable[T]],
    retryable: tuple[type[BaseException], ...],
    name: str,
) -> T:
    """
    Await func() and retry it when a "retryable" exception is raised.
    """
    for attempt in range(retries):
        try:
            return await func()
        except retryable as e:
            # try again
            await asyncio.sleep(retry_delay(name, attempt, repr(e)))
    return await func()
