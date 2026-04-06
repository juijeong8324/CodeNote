import logging

#from anthropic import APIConnectionError, APIStatusError, RateLimitError
from google.api_core import exceptions as google_exceptions
from tenacity import (
    RetryCallState,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# RETRYABLE_EXCEPTIONS = (RateLimitError, APIConnectionError, APIStatusError)

# Gemini + 일반적인 transient 오류를 retry 대상으로 설정
RETRYABLE_EXCEPTIONS = (
    google_exceptions.ResourceExhausted,      # 429 Rate Limit
    google_exceptions.ServiceUnavailable,
    google_exceptions.DeadlineExceeded,       # Timeout
    google_exceptions.InternalServerError,
    google_exceptions.TooManyRequests,        # 또 다른 429 형태
    ConnectionError,
    TimeoutError,
)

# def agent_retry(max_attempts: int = 3):
#     """에이전트 호출에 사용할 재시도 데코레이터."""
#     return retry(
#         stop=stop_after_attempt(max_attempts),
#         wait=wait_exponential(multiplier=1, min=4, max=60),
#         retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
#         before_sleep=before_sleep_log(logger, logging.WARNING),
#         reraise=True,
#     )

def agent_retry(max_attempts: int = 3):
    """에이전트 호출에 사용할 재시도 데코레이터 (Gemini에 최적화)"""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1.5, min=5, max=90),   # Gemini rate limit에 더 여유롭게
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,          # 마지막 실패 시 원래 예외를 그대로 raise
    )
