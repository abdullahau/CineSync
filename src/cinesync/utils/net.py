import asyncio
import random
import requests
import socket
import time
from cinesync.config_loader import load_config

# Statuses worth retrying: 429 rate-limit + transient 5xx. A non-retryable
# status is returned as-is so the caller's raise_for_status()/status check owns it.
_RETRY_STATUS = (429, 500, 502, 503, 504)


def force_ipv4():
    """(Forces the requests/urllib3 connection pool to prefer IPv4.)"""
    orig = socket.getaddrinfo

    def getaddrinfo_ipv4(*args, **kwargs):
        return [x for x in orig(*args, **kwargs) if x[0] == socket.AF_INET]

    socket.getaddrinfo = getaddrinfo_ipv4


def paced_request(
    session,
    url: str,
    *,
    service: str,
    method: str = "GET",
    params: dict | None = None,
    data: dict | None = None,
    headers: dict | None = None,
):
    """
    Shared, config-driven network pacing for every plain-`requests` fetcher
    (TMDB, Wikidata, Wikipedia, and future Rotten Tomatoes). Pacing/retry knobs
    come from config.yaml's `rate_limiting.<service>` block; the endpoint URL,
    User-Agent, and body/params stay with the caller.

    Returns the requests.Response. Retries 429 + 5xx (honouring Retry-After) and
    connection/timeout errors with exponential backoff + jitter, then sleeps
    min_interval after a delivered response. On exhausted retries it returns the
    last response if one arrived, else re-raises the last connection error.

    `timeout` may be a scalar or a [connect, read] pair. `method` allows POST for
    SPARQL. NOTE: IMDb (curl_cffi TLS impersonation) and the async Letterboxd
    scraper can't use this -- they keep their own loops.
    """
    cfg = load_config()["rate_limiting"][service]
    min_interval, max_retries, timeout = (
        cfg["min_interval"],
        cfg["max_retries"],
        cfg["timeout"],
    )
    timeout = tuple(timeout) if isinstance(timeout, (list, tuple)) else timeout

    last_exc = None
    response = None
    for attempt in range(max_retries):
        try:
            response = session.request(
                method, url, params=params, data=data, headers=headers, timeout=timeout
            )
        except (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
        ) as exc:
            last_exc, response = exc, None
            wait = 2**attempt
            print(
                f"    [paced_request:{service}] {type(exc).__name__} on {url} "
                f"(attempt {attempt + 1}/{max_retries}), retrying in {wait}s"
            )
            time.sleep(wait)
            continue

        if response.status_code in _RETRY_STATUS:
            wait = float(response.headers.get("Retry-After", 2**attempt)) + random.uniform(0, 1)
            print(
                f"    [paced_request:{service}] HTTP {response.status_code} on {url} "
                f"(attempt {attempt + 1}/{max_retries}), sleeping {wait:.1f}s"
            )
            time.sleep(wait)
            continue

        time.sleep(min_interval)
        return response

    if response is not None:
        return response  # last retryable response; caller surfaces the bad status
    raise last_exc      # every attempt was a connection error


# ===========================================================================
# Async scraping primitives (curl_cffi AsyncSession fetchers: IMDb, Letterboxd)
# ===========================================================================
#
# These serve the anti-bot scrapers that can't use paced_request (they need
# curl_cffi TLS impersonation and run under asyncio, not plain requests). Both
# share the same model: a global rate gate + a per-request retry wrapper, driven
# by rate_limiting.<service> (min_interval / max_retries / timeout / concurrency).


class AsyncRateGate:
    """Global minimum-interval gate across all coroutines. Reservation of the
    next evenly-spaced request slot is serialized under a lock; the wait itself
    happens OUTSIDE the lock, so the aggregate outbound rate is capped at
    1/min_interval req/s regardless of how many coroutines are in flight -- the
    async analogue of the IMDb driver's old token bucket."""

    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._next_slot = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            slot = max(time.monotonic(), self._next_slot)
            self._next_slot = slot + self.min_interval
        delay = slot - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)


async def paced_request_async(
    session,
    url: str,
    *,
    gate: AsyncRateGate,
    max_retries: int,
    timeout: float,
    method: str = "GET",
    headers: dict | None = None,
    **kwargs,
):
    """Gate-paced curl_cffi AsyncSession request with retry. Awaits the shared
    rate gate before every attempt, then retries 429 + 5xx and connection errors
    with exponential backoff + jitter. Returns the Response (caller checks status
    / parses); returns the last retryable response on exhaustion, or re-raises
    the last connection error if no response ever arrived. Pacing lives in the
    gate, so there's no post-success sleep here."""
    last_exc = None
    response = None
    for attempt in range(max_retries):
        await gate.wait()
        try:
            response = await session.request(
                method, url, headers=headers, timeout=timeout, **kwargs
            )
        except Exception as exc:  # curl_cffi raises its own error hierarchy
            last_exc, response = exc, None
            await asyncio.sleep((2**attempt) + random.uniform(0, 1))
            continue
        if response.status_code in _RETRY_STATUS:
            await asyncio.sleep((2**attempt) + random.uniform(0, 1))
            continue
        return response

    if response is not None:
        return response
    raise last_exc
