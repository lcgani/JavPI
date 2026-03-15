"""Timeout monitoring for Gemini Live API operations."""
import asyncio
import logging
from typing import TypeVar, Callable, ParamSpec


logger = logging.getLogger(__name__)

P = ParamSpec('P')
T = TypeVar('T')


class TimeoutError(Exception):
    """Raised when operation exceeds timeout."""
    pass


async def with_timeout(
    func: Callable[P, T],
    timeout_seconds: float,
    operation_name: str,
    *args: P.args,
    **kwargs: P.kwargs
) -> T:
    """Execute async function with timeout.
    
    Args:
        func: Async function to execute
        timeout_seconds: Timeout in seconds
        operation_name: Name for logging
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func
        
    Returns:
        Result from function
        
    Raises:
        TimeoutError: If operation exceeds timeout
    """
    try:
        return await asyncio.wait_for(
            func(*args, **kwargs),
            timeout=timeout_seconds
        )
    except asyncio.TimeoutError as e:
        logger.error(f"{operation_name} exceeded {timeout_seconds}s timeout")
        raise TimeoutError(
            f"{operation_name} timed out after {timeout_seconds}s"
        ) from e


class TimeoutMonitor:
    """Monitor for various Gemini API operation timeouts."""
    
    KEEPALIVE_INTERVAL = 30.0
    VISION_PROCESSING_TIMEOUT = 10.0
    VOICE_TURN_TIMEOUT = 30.0
    
    def __init__(self):
        self._keepalive_task: asyncio.Task[None] | None = None
        self._running = False
    
    async def start_keepalive(self, check_func: Callable[[], None]) -> None:
        """Start keepalive monitoring.
        
        Args:
            check_func: Function to call every keepalive interval
        """
        self._running = True
        self._keepalive_task = asyncio.create_task(
            self._keepalive_loop(check_func)
        )
    
    async def stop_keepalive(self) -> None:
        """Stop keepalive monitoring."""
        self._running = False
        if self._keepalive_task:
            self._keepalive_task.cancel()
            try:
                await self._keepalive_task
            except asyncio.CancelledError:
                pass
    
    async def _keepalive_loop(self, check_func: Callable[[], None]) -> None:
        """Internal keepalive loop."""
        while self._running:
            await asyncio.sleep(self.KEEPALIVE_INTERVAL)
            try:
                check_func()
            except Exception as e:
                logger.warning(f"Keepalive check failed: {e}")
    
    async def monitor_vision_processing(
        self,
        func: Callable[P, T],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> T:
        """Monitor vision processing with timeout alert.
        
        Args:
            func: Vision processing function
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Result from function
        """
        try:
            return await with_timeout(
                func,
                self.VISION_PROCESSING_TIMEOUT,
                "Vision processing",
                *args,
                **kwargs
            )
        except TimeoutError:
            logger.warning(
                f"Vision processing exceeded {self.VISION_PROCESSING_TIMEOUT}s"
            )
            raise
    
    async def monitor_voice_turn(
        self,
        func: Callable[P, T],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> T:
        """Monitor voice turn completion with timeout.
        
        Args:
            func: Voice processing function
            *args: Positional arguments
            **kwargs: Keyword arguments
            
        Returns:
            Result from function
        """
        return await with_timeout(
            func,
            self.VOICE_TURN_TIMEOUT,
            "Voice turn",
            *args,
            **kwargs
        )
