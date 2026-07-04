import socket
import time
from cinesync.config_loader import load_config


def force_ipv4():
    """(Forces the requests/urllib3 connection pool to prefer IPv4.)"""
    orig = socket.getaddrinfo

    def getaddrinfo_ipv4(*args, **kwargs):
        return [x for x in orig(*args, **kwargs) if x[0] == socket.AF_INET]

    socket.getaddrinfo = getaddrinfo_ipv4


def paced_get(
    session,
    url: str,
    params: dict,
    headers: dict,
):
    """
    Self-imposed pacing well under TMDB's real ~40-50 req/s ceiling.
    min_interval=0.15s is roughly 6-7 req/s. Backs off using the
    Retry-After header on a 429 rather than guessing a wait time.
    """
    config = load_config()["rate_limiting"]
    min_interval, max_retries = config["min_interval"], config["max_retries"]
    for attempt in range(max_retries):
        response = session.get(url, params=params, headers=headers)
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2**attempt))
            time.sleep(wait)
            continue
        time.sleep(min_interval)
        return response
    raise RuntimeError(f"Exceeded {max_retries} retries for {url}")
