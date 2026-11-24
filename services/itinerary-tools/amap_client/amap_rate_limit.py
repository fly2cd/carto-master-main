"""One thread-safe pacing gate for all Amap requests in this service process."""
import asyncio
import math
import threading
import time


class AmapRateLimiter:
    def __init__(self, qps=2.0, *, clock=None, sleep=None):
        self._clock = clock or time.monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_start = 0.0
        self.configure(qps)

    def configure(self, qps):
        if not math.isfinite(qps) or not 0 < qps <= 30:
            raise ValueError('Amap QPS must be finite and in (0, 30]. Verify the account quota before increasing it.')
        with self._lock:
            self.qps = float(qps)
            self._interval = 1.0 / self.qps
            # Reconfiguration must not release already waiting requests as a burst.
            self._next_start = max(self._next_start, self._clock())

    async def acquire(self):
        while True:
            with self._lock:
                now = self._clock()
                delay = self._next_start - now
                if delay <= 0:
                    self._next_start = now + self._interval
                    return now
            # Recheck after waking: concurrent clients cannot consume stale reservations.
            await (self._sleep or asyncio.sleep)(delay)


_limiter = AmapRateLimiter()


def configure_amap_qps(qps):
    _limiter.configure(qps)


async def wait_for_amap_slot():
    return await _limiter.acquire()
