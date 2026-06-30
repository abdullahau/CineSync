"""
Phase 1b: build the candidate pool via TMDB's /discover/movie and
/discover/tv -- one sweep per language in config.yaml's
languages_of_interest.
"""

import time
from datetime import date


def build_discover_params(
    content_type: str,
    original_language: str,
    page: int = 1,
    min_vote_count: int = 15,
    min_runtime_minutes: int = 40,
    release_year_floor_years_ago: int = 35,
    sort_by: str = "vote_count.desc",
) -> dict:
    """
    Build query params for one page of one language's /discover sweep.
    Defaults match config.yaml's candidate_pool section -- pass that
    config in explicitly rather than relying on these hardcoded
    defaults once Phase 1b is actually wired up.
    """
    floor_year = date.today().year - release_year_floor_years_ago
    params = {
        "include_adult": "false",
        "with_original_language": original_language,
        "vote_count.gte": min_vote_count,
        "sort_by": sort_by,
        "page": page,
    }
    if content_type == "movie":
        params["include_video"] = "false"
        params["with_runtime.gte"] = min_runtime_minutes
        params["primary_release_date.gte"] = f"{floor_year}-01-01"
    elif content_type == "tv":
        params["first_air_date.gte"] = f"{floor_year}-01-01"
    else:
        raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")

    return params


def paced_get(
    session,
    url: str,
    params: dict,
    headers: dict,
    min_interval: float = 0.15,
    max_retries: int = 5,
):
    """
    Self-imposed pacing well under TMDB's real ~40-50 req/s ceiling.
    min_interval=0.15s is roughly 6-7 req/s -- comfortably safe, and
    still fast enough that a few thousand titles finish in minutes,
    not hours. Backs off using the Retry-After header on a 429 rather
    than guessing a wait time.
    """
    for attempt in range(max_retries):
        response = session.get(url, params=params, headers=headers)
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2**attempt))
            time.sleep(wait)
            continue
        time.sleep(min_interval)
        return response
    raise RuntimeError(f"Exceeded {max_retries} retries for {url}")
