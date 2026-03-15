"""Retry logic with exponential backoff for Gemini API."""
import asyncio
import logging
from typing import Callable, TypeVar, ParamSpec


logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


async def retry_with_backoff(
    func: Callable[P, T],
    backoff_seconds: list[int],
    *args: P.args,
    **kwargs: P.kwargs
) -> T:
    """Retry function with exponential backoff.
    
    Args:
        func: Async function to retry
        backoff_seconds: List of backoff delays (e.g., [1, 2, 4])
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
        
    Returns:
        Result from successful function call
        
    Raises:
        Exception: Last exception if all retries fail
    """
    last_exception = None
    
    for attempt, delay in enumerate(backoff_seconds, start=1):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            logger.warning(
                f"Attempt {attempt}/{len(backoff_seconds)} failed: {e}. "
                f"Retrying in {delay}s..."
            )
            if attempt < len(backoff_seconds):
                await asyncio.sleep(delay)
    
    logger.error(f"All {len(backoff_seconds)} retry attempts failed")
    raise last_exception
