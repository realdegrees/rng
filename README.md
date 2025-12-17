# LiveCam RNG

A random number generator that uses live webcam images as an entropy source, inspired by [Cloudflare's LavaRand](https://blog.cloudflare.com/randomness-101-lavarand-in-production/).

## How It Works

Each request generates a random number by combining entropy from multiple sources:

1. **Image Collection** — Fetches live webcam images from [WorldCam](https://worldcam.eu) across 6 continents (Europe, North America, South America, Asia, Africa, Oceania)
2. **Region Extraction** — Slices images into 32×32 pixel regions and stores raw pixel data in per-continent buffers
3. **Entropy Combination** — On each request, takes one region from each continent's buffer and concatenates them
4. **Additional Entropy** — Mixes in CPU timing jitter, network timing jitter, `os.urandom()`, and a request counter
5. **Output** — Computes HMAC-SHA256 using a rotating session secret, converts the first 8 bytes to a float

```
Request → Collect image region from multiple continents
        → Add CPU jitter + network jitter + os.urandom(32) + request counter + timestamp
        → HMAC-SHA256 with session secret
        → Convert to float [0, 1)
```

The session secret rotates every 100 requests or 30 seconds using entropy from the same sources.

## Disclaimer

**This is an educational/experimental project.**

- Not cryptographically secure
- Not auditable or verifiable
- Do not use for security-sensitive applications

For cryptographic randomness, use `os.urandom()`, the `secrets` module, or hardware RNGs.

## Usage

```bash
docker compose up --build
```

Or locally:

```bash
pip install -r requirements.txt
uvicorn rng:app --host 0.0.0.0 --port 8000
```

## API

### `GET /rng`

Returns a random float between 0 and 1.

```json
{"random": 0.7291847362918474}
```

### `GET /health`

Returns buffer status per continent.

```json
{
    "status": "ok",
    "entropy_sources": [
        "cpu_timing_jitter",
        "network_timing_jitter",
        "live_camera_images"
    ],
    "livecam_total_regions": 455,
    "livecam_by_continent": {
        "europe": 91,
        "north-america": 91,
        "south-america": 91,
        "asia": 91,
        "australia-oceania": 91
    },
    "livecam_prefetching": false
}
```

## Project Structure

```
rng/
├── entropy/
│   ├── base.py           # Abstract entropy source interface
│   ├── cpu_jitter.py     # CPU timing jitter
│   ├── network_jitter.py # Network latency jitter
│   └── livecam.py        # Webcam image entropy (per-continent buffers)
├── rng.py                # FastAPI application
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```