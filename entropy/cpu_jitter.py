"""CPU timing jitter entropy source."""

import time

from entropy.base import EntropySource


DEFAULT_ITERATIONS = 8
DEFAULT_LOOP_COUNT = 2000


class CpuJitterSource(EntropySource):
    """Entropy source based on CPU timing variations."""

    def __init__(
        self,
        iterations: int = DEFAULT_ITERATIONS,
        loop_count: int = DEFAULT_LOOP_COUNT,
    ) -> None:
        self._iterations = iterations
        self._loop_count = loop_count

    @property
    def name(self) -> str:
        return "cpu_timing_jitter"

    def collect(self) -> bytes:
        """Collect entropy from CPU timing jitter."""
        buf = bytearray()

        for _ in range(self._iterations):
            t1 = time.perf_counter_ns()
            for _ in range(self._loop_count):
                pass
            t2 = time.perf_counter_ns()
            buf.extend((t2 - t1).to_bytes(8, "big"))

        return bytes(buf)
