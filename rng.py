"""Random number generator with multiple entropy sources."""

import os
import time
import hmac
import hashlib
import threading
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from entropy import EntropySource, CpuJitterSource, NetworkJitterSource, LiveCamSource

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- CONFIG ----------------

ROTATE_EVERY_REQUESTS = 100
ROTATE_EVERY_SECONDS = 30

# ----------------------------------------

lock = threading.Lock()

request_counter = 0
last_rotation = time.time()

SESSION_SECRET = hashlib.sha256(
    os.urandom(64) + time.time_ns().to_bytes(8, "big")
).digest()


class EntropyPool:
    """Manages multiple entropy sources and collects randomness."""

    def __init__(self) -> None:
        self._sources: list[EntropySource] = []
        self._livecam_source: Optional[LiveCamSource] = None

    def add_source(self, source: EntropySource) -> None:
        """Add an entropy source to the pool."""
        self._sources.append(source)
        if isinstance(source, LiveCamSource):
            self._livecam_source = source

    def collect_all(self) -> bytes:
        """Collect entropy from all sources."""
        entropy_parts: list[bytes] = []
        for source in self._sources:
            try:
                entropy_parts.append(source.collect())
            except Exception:
                continue
        return b"".join(entropy_parts)

    def collect_from(self, *source_types: type) -> bytes:
        """Collect entropy from specific source types only."""
        entropy_parts: list[bytes] = []
        for source in self._sources:
            if isinstance(source, source_types):
                try:
                    entropy_parts.append(source.collect())
                except Exception:
                    continue
        return b"".join(entropy_parts)

    @property
    def livecam(self) -> Optional[LiveCamSource]:
        """Get the live camera source if available."""
        return self._livecam_source

    def ensure_livecam_regions(self) -> None:
        """Ensure the live camera source has regions available."""
        if self._livecam_source and not self._livecam_source.has_regions():
            self._livecam_source.refill_regions()


entropy_pool = EntropyPool()
entropy_pool.add_source(CpuJitterSource())
entropy_pool.add_source(NetworkJitterSource())
entropy_pool.add_source(LiveCamSource(
    region_size=32,
    target_buffer=50,
    low_watermark=25,
))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    logger.info("Starting entropy sources...")
    if entropy_pool.livecam:
        logger.info("Initializing LiveCam source (this may take a moment)...")
        entropy_pool.livecam.start()
        logger.info(f"LiveCam ready with {entropy_pool.livecam.regions_count()} regions")
    logger.info("Entropy sources ready - server accepting requests")
    yield
    logger.info("Shutting down...")


app = FastAPI(lifespan=lifespan)


def rotate_secret() -> None:
    """Rotate the session secret using collected entropy."""
    global SESSION_SECRET, last_rotation

    rotation_entropy = b"".join([
        os.urandom(32),
        entropy_pool.collect_from(CpuJitterSource, NetworkJitterSource),
        request_counter.to_bytes(8, "big"),
        int(time.time_ns()).to_bytes(8, "big"),
    ])

    SESSION_SECRET = hmac.new(
        SESSION_SECRET,
        rotation_entropy,
        hashlib.sha256,
    ).digest()

    last_rotation = time.time()


@app.get("/rng")
def rng() -> JSONResponse:
    """Generate a random number using multiple entropy sources."""
    global request_counter

    with lock:
        request_counter += 1

        should_rotate = (
            request_counter % ROTATE_EVERY_REQUESTS == 0
            or time.time() - last_rotation > ROTATE_EVERY_SECONDS
        )
        if should_rotate:
            rotate_secret()

        livecam_entropy = b""
        if entropy_pool.livecam:
            try:
                livecam_entropy = entropy_pool.livecam.collect()
            except Exception:
                pass

        entropy = b"".join([
            livecam_entropy,
            entropy_pool.collect_from(CpuJitterSource),
            os.urandom(32),
            request_counter.to_bytes(8, "big"),
            time.time_ns().to_bytes(8, "big"),
        ])

        mac = hmac.new(
            SESSION_SECRET,
            entropy,
            hashlib.sha256,
        ).digest()

        value = int.from_bytes(mac[:8], "big") / 2**64

        return JSONResponse(
            {"random": value},
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )


@app.get("/health")
def health() -> JSONResponse:
    """Health check endpoint."""
    livecam = entropy_pool.livecam
    return JSONResponse({
        "status": "ok",
        "entropy_sources": [source.name for source in entropy_pool._sources],
        "livecam_total_regions": livecam.regions_count() if livecam else 0,
        "livecam_by_continent": livecam.regions_by_continent() if livecam else {},
        "livecam_prefetching": livecam.is_prefetching() if livecam else False,
    })
