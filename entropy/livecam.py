"""Live camera image entropy source with async prefetching."""

import io
import random
import threading
import logging
from queue import Queue, Empty
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from PIL import Image

from entropy.base import EntropySource


logger = logging.getLogger(__name__)

DEFAULT_REGION_SIZE = 20
DEFAULT_REQUEST_TIMEOUT = 15
DEFAULT_PREFETCH_WORKERS = 6

WORLDCAM_BASE_URL = "https://worldcam.eu/webcams/"

CONTINENTS = [
    "europe",
    "north-america",
    "south-america",
    "asia",
    "australia-oceania",
]


class LiveCamSource(EntropySource):
    """Entropy source based on live camera images with async prefetching."""

    def __init__(
        self,
        region_size: int,
        target_buffer: int,
        low_watermark: int,
        timeout: int = DEFAULT_REQUEST_TIMEOUT,
        prefetch_workers: int = DEFAULT_PREFETCH_WORKERS,
    ) -> None:
        self._region_size = region_size
        self._timeout = timeout
        self._target_buffer = target_buffer
        self._low_watermark = low_watermark

        self._regions_by_continent: dict[str, Queue[bytes]] = {
            continent: Queue() for continent in CONTINENTS
        }

        self._continent_prefetch_lock: dict[str, threading.Lock] = {
            continent: threading.Lock() for continent in CONTINENTS
        }
        self._continent_prefetching: dict[str, bool] = {
            continent: False for continent in CONTINENTS
        }

        self._executor = ThreadPoolExecutor(max_workers=prefetch_workers)
        self._started = False
        self._startup_complete = threading.Event()

    @property
    def name(self) -> str:
        return "live_camera_images"

    def _fetch_image(self, url: str) -> Optional[Image.Image]:
        """Fetch an image from a URL."""
        try:
            response = requests.get(url, timeout=self._timeout, allow_redirects=True)
            response.raise_for_status()
            img = Image.open(io.BytesIO(response.content)).convert("RGB")
            logger.debug(f"Successfully fetched image from {url} ({img.size[0]}x{img.size[1]})")
            return img
        except Exception as e:
            logger.warning(f"Failed to fetch image from {url}: {e}")
            return None

    def _slice_regions(self, img: Image.Image) -> list[bytes]:
        """Slice an image into regions for entropy extraction."""
        width, height = img.size
        pixels = img.load()
        regions: list[bytes] = []

        for y in range(0, height - self._region_size, self._region_size):
            for x in range(0, width - self._region_size, self._region_size):
                buf = bytearray()
                for dy in range(self._region_size):
                    for dx in range(self._region_size):
                        buf.extend(pixels[x + dx, y + dy])
                regions.append(bytes(buf))

        random.shuffle(regions)
        return regions

    def _discover_continent_images(self, continent: str) -> list[str]:
        """Discover webcam image URLs from a specific continent."""
        urls: list[str] = []
        if continent not in CONTINENTS:
            return urls

        logger.info(f"Discovering cameras from WorldCam: {continent}")

        try:
            response = requests.get(
                f"{WORLDCAM_BASE_URL}{continent}",
                timeout=self._timeout,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            for img in soup.find_all("img"):
                src = img.get("src", "")
                data_src = img.get("data-src", "")
                for candidate in [src, data_src]:
                    if candidate and ("webcam" in candidate.lower() or "cam" in candidate.lower()):
                        if candidate.startswith("http"):
                            urls.append(candidate)
                        elif candidate.startswith("/"):
                            urls.append(f"{WORLDCAM_BASE_URL}{candidate}")
            logger.info(f"WorldCam [{continent}]: discovered {len(urls)} camera URLs")
        except Exception as e:
            logger.warning(f"WorldCam discovery failed for {continent}: {e}")

        return urls

    def _fetch_and_enqueue_for_continent(self, url: str, continent: str) -> bool:
        """Fetch a single image and add its regions to the continent queue."""
        img = self._fetch_image(url)
        if img:
            regions = self._slice_regions(img)
            queue = self._regions_by_continent[continent]
            added_count = 0
            for region in regions:
                queue.put(region)
                added_count += 1
            logger.info(f"[{continent}] {url[:45]}... -> {added_count} regions (buffer: {queue.qsize()})")
            return True
        return False

    def _fill_continent_buffer(self, continent: str) -> None:
        """Fill a single continent's buffer up to target size."""
        with self._continent_prefetch_lock[continent]:
            if self._continent_prefetching[continent]:
                return
            self._continent_prefetching[continent] = True

        try:
            queue = self._regions_by_continent[continent]
            current_size = queue.qsize()

            if current_size >= self._target_buffer:
                logger.debug(f"[{continent}] Buffer already at {current_size}, skipping")
                return

            needed = self._target_buffer - current_size
            logger.info(f"[{continent}] Filling buffer: {current_size} -> {self._target_buffer} (need ~{needed} regions)")

            urls = self._discover_continent_images(continent)
            if not urls:
                logger.warning(f"[{continent}] No URLs found")
                return

            random.shuffle(urls)

            for url in urls:
                if queue.qsize() >= self._target_buffer:
                    break
                self._fetch_and_enqueue_for_continent(url, continent)

            logger.info(f"[{continent}] Buffer fill complete: {queue.qsize()} regions")
        finally:
            with self._continent_prefetch_lock[continent]:
                self._continent_prefetching[continent] = False

    def _check_and_refill_continent(self, continent: str) -> None:
        """Check if continent needs refill and trigger async if needed."""
        queue = self._regions_by_continent[continent]
        current_size = queue.qsize()

        if current_size < self._low_watermark:
            with self._continent_prefetch_lock[continent]:
                if self._continent_prefetching[continent]:
                    return
            logger.info(f"[{continent}] Buffer low ({current_size}/{self._low_watermark}), triggering async refill")
            self._executor.submit(self._fill_continent_buffer, continent)

    def _check_all_continents(self) -> None:
        """Check all continents and trigger refills as needed."""
        for continent in CONTINENTS:
            self._check_and_refill_continent(continent)

    def start(self) -> None:
        """Start the prefetching system and do initial load (blocking)."""
        if self._started:
            return
        self._started = True
        logger.info(f"Starting initial buffer fill for {len(CONTINENTS)} continents...")

        futures = []
        for continent in CONTINENTS:
            future = self._executor.submit(self._fill_continent_buffer, continent)
            futures.append((continent, future))

        for continent, future in futures:
            try:
                future.result(timeout=self._timeout * 5)
            except Exception as e:
                logger.warning(f"Initial fill failed for {continent}: {e}")

        total = self.regions_count()
        logger.info(f"Initial buffer fill complete: {total} total regions")
        logger.info(f"Per-continent: {self.regions_by_continent()}")
        self._startup_complete.set()

    def collect(self) -> bytes:
        """Collect entropy by combining one region from each continent."""
        if not self._started:
            self.start()

        self._startup_complete.wait(timeout=60)

        combined_entropy = bytearray()
        continents_used: list[str] = []

        for continent in CONTINENTS:
            queue = self._regions_by_continent[continent]
            try:
                region = queue.get_nowait()
                combined_entropy.extend(region)
                continents_used.append(continent)
            except Empty:
                pass

        self._check_all_continents()

        if not combined_entropy:
            logger.error("All buffers empty")
            raise RuntimeError("No image entropy available")

        logger.debug(f"Collected from {len(continents_used)} continents")
        return bytes(combined_entropy)

    def has_regions(self) -> bool:
        """Check if all continents have regions available."""
        return all(q.qsize() > 0 for q in self._regions_by_continent.values())

    def regions_count(self) -> int:
        """Get the total number of available regions across all continents."""
        return sum(q.qsize() for q in self._regions_by_continent.values())

    def regions_by_continent(self) -> dict[str, int]:
        """Get region counts per continent."""
        return {c: q.qsize() for c, q in self._regions_by_continent.items()}

    def is_prefetching(self) -> bool:
        """Check if any continent is currently prefetching."""
        return any(self._continent_prefetching.values())
