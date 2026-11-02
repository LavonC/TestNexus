"""
Adaptive rate limiting for Gemini API and LLM calls.
Prevents 429 quota exhaustion bursts by maintaining requests within free-tier RPM limits,
and dynamically applies cooldown backoff upon receiving 429 rate limit errors.
"""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """
    Token bucket / interval-based asynchronous rate limiter with adaptive backoff.
    Ensures calls do not exceed the configured requests-per-minute (RPM).
    """

    def __init__(self, requests_per_minute: float = 12.0):
        """
        Initialize rate limiter with a maximum RPM.
        Default is 12.0 RPM (well within the 15.0 RPM free tier ceiling).
        """
        self.rpm = float(requests_per_minute)
        self.interval = 60.0 / self.rpm if self.rpm > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last_call_time = 0.0
        self._backoff_until = 0.0

    async def acquire(self) -> float:
        """
        Acquire permission to execute a request.
        Awaits if necessary to respect the interval between calls or active backoff.
        Returns the duration waited in seconds.
        """
        if self.rpm <= 0:
            return 0.0

        async with self._lock:
            now = time.monotonic()
            waited = 0.0

            # 1. Respect active 429 cooldown backoff
            if now < self._backoff_until:
                backoff_wait = self._backoff_until - now
                logger.info(
                    "Rate limiter holding for 429 cooldown: %.2f seconds", backoff_wait
                )
                await asyncio.sleep(backoff_wait)
                now = time.monotonic()
                waited += backoff_wait

            # 2. Respect regular RPM interval
            elapsed = now - self._last_call_time
            if elapsed < self.interval:
                interval_wait = self.interval - elapsed
                logger.debug(
                    "Rate limiter delaying request by %.2f seconds (limit: %.1f RPM)",
                    interval_wait,
                    self.rpm,
                )
                await asyncio.sleep(interval_wait)
                waited += interval_wait

            self._last_call_time = time.monotonic()
            return waited

    async def backoff(self, delay: float = 2.0, reduce_rpm: bool = False) -> None:
        """
        Trigger adaptive backoff upon receiving a 429 rate limit or quota notice.
        Sets a cooldown period and optionally reduces requests per minute.
        """
        async with self._lock:
            self._backoff_until = max(self._backoff_until, time.monotonic() + delay)
            if reduce_rpm and self.rpm > 2.0:
                self.update_rpm(max(2.0, self.rpm * 0.8))
            logger.info("Adaptive rate limiter backoff active for %.2f seconds", delay)

    def update_rpm(self, new_rpm: float) -> None:
        """Dynamically adjust requests per minute (e.g. after receiving a 429)."""
        self.rpm = max(1.0, float(new_rpm))
        self.interval = 60.0 / self.rpm
        logger.info(
            "Updated rate limiter RPM to %.1f (interval: %.2fs)",
            self.rpm,
            self.interval,
        )
