import logging

from anthropic import APIConnectionError, APIStatusError, RateLimitError
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RETRYABLE_EXCEPTIONS = (RateLimitError, APIConnectionError, APIStatusError)


def _log_retry(retry_state: RetryCallState) -> None:
    exc = retry_state.outcome.exception()
    logger.warning(
        "Retrying %s (attempt %d): %s",
        retry_state.fn.__name__,
        retry_state.attempt_number,
        exc,
    )


def agent_retry(max_attempts: int = 3):
    """에이전트 호출에 사용할 재시도 데코레이터."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
