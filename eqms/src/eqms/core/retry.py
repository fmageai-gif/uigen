"""Retry helpers with exponential back-off and jitter.

SharePoint-hosted Excel files are frequently locked by other concurrent users
or transiently throttled by Microsoft Graph. Rather than surfacing those
transient failures to the QA user, storage operations are wrapped so they
retry a bounded number of times with increasing delays before giving up.
"""

from __future__ import annotations

import functools
import random
import time
from typing import Callable, Iterable, TypeVar

from .. import config
from .exceptions import ConnectivityError, WorkbookLockedError
from .logging_config import get_logger

_log = get_logger(__name__)

T = TypeVar("T")

#: Exception types considered transient and therefore worth retrying.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    WorkbookLockedError,
    ConnectivityError,
    TimeoutError,
    ConnectionError,
)


def _compute_delay(attempt: int) -> float:
    """Exponential back-off with full jitter, capped at ``RETRY_MAX_DELAY``."""
    raw = config.RETRY_BASE_DELAY * (2 ** (attempt - 1))
    capped = min(raw, config.RETRY_MAX_DELAY)
    # Full jitter avoids the "thundering herd" of many clients retrying in sync.
    return random.uniform(0, capped)


def retry_call(
    func: Callable[[], T],
    *,
    attempts: int | None = None,
    transient: Iterable[type[BaseException]] | None = None,
    description: str = "operation",
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Invoke ``func`` retrying on transient errors with back-off.

    Parameters
    ----------
    func:
        Zero-argument callable to execute. Wrap with ``functools.partial`` or a
        lambda to bind arguments.
    attempts:
        Maximum attempts. Defaults to :data:`config.RETRY_ATTEMPTS`.
    transient:
        Iterable of exception types to treat as retryable. Defaults to
        :data:`TRANSIENT_ERRORS`.
    description:
        Human-readable label used in log messages.
    sleep:
        Injectable sleep function (overridden in tests to avoid real waits).

    Returns
    -------
    T
        Whatever ``func`` returns on the first successful attempt.

    Raises
    ------
    BaseException
        Re-raises the last transient error if all attempts are exhausted, or
        immediately re-raises any non-transient error.
    """
    max_attempts = attempts or config.RETRY_ATTEMPTS
    transient_types = tuple(transient) if transient else TRANSIENT_ERRORS
    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except transient_types as exc:  # type: ignore[misc]
            last_error = exc
            if attempt >= max_attempts:
                break
            delay = _compute_delay(attempt)
            _log.warning(
                "Transient failure during %s (attempt %d/%d): %s — retrying in %.1fs",
                description,
                attempt,
                max_attempts,
                exc,
                delay,
            )
            sleep(delay)

    _log.error("Giving up on %s after %d attempts", description, max_attempts)
    assert last_error is not None
    raise last_error


def with_retry(description: str = "operation"):
    """Decorator form of :func:`retry_call` for storage methods.

    Example
    -------
    >>> @with_retry("save audit")
    ... def save(self, audit):
    ...     ...
    """

    def decorator(fn: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            return retry_call(
                lambda: fn(*args, **kwargs), description=description
            )

        return wrapper

    return decorator
