"""Network timing jitter entropy source."""

import time
from typing import Optional

import requests

from entropy.base import EntropySource


DEFAULT_ITERATIONS = 3
DEFAULT_TIMEOUT = 10

DEFAULT_PROBE_URLS = [
    "https://www.google.com",
    "https://www.cloudflare.com",
    "https://www.amazon.com",
    "https://www.microsoft.com",
    "https://www.github.com",
]


class NetworkJitterSource(EntropySource):
    """Entropy source based on network timing variations."""

    def __init__(
        self,
        probe_urls: Optional[list[str]] = None,
        iterations: int = DEFAULT_ITERATIONS,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self._probe_urls = probe_urls or DEFAULT_PROBE_URLS
        self._iterations = iterations
        self._timeout = timeout
        self._url_index = 0

    @property
    def name(self) -> str:
        return "network_timing_jitter"

    def _get_next_url(self) -> str:
        """Get the next URL to probe in round-robin fashion."""
        url = self._probe_urls[self._url_index % len(self._probe_urls)]
        self._url_index += 1
        return url

    def collect(self) -> bytes:
        """Collect entropy from network timing jitter."""
        buf = bytearray()
        url = self._get_next_url()

        for _ in range(self._iterations):
            t1 = time.perf_counter_ns()
            try:
                requests.head(url, timeout=self._timeout)
            except Exception:
                pass
            t2 = time.perf_counter_ns()
            buf.extend((t2 - t1).to_bytes(8, "big"))

        return bytes(buf)

    def collect_from_url(self, url: str) -> bytes:
        """Collect entropy from a specific URL."""
        buf = bytearray()

        for _ in range(self._iterations):
            t1 = time.perf_counter_ns()
            try:
                requests.head(url, timeout=self._timeout)
            except Exception:
                pass
            t2 = time.perf_counter_ns()
            buf.extend((t2 - t1).to_bytes(8, "big"))

        return bytes(buf)
