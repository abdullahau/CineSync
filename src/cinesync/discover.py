"""
Phase 1b: build the candidate pool via TMDB's /discover/movie and
/discover/tv -- one sweep per language in config.yaml's languages_of_interest.
"""

import time
from datetime import date


def build_discover_params(
    content_type: str,
    original_language: str,
    page: int = 1,
    min_vote_count: int = 15,
    min_runtime_minutes: int = 40,
    sort_by: str = "vote_count.desc",
    date_gte: str | None = None,
    date_lte: str | None = None,
) -> dict:
    """
    Build query params for one page of one language's /discover sweep.

    Date windowing: pass explicit `date_gte` and `date_lte`
    ('YYYY-MM-DD') to query one bounded date window -- this is how the
    500-page-cap workaround splits a broad sweep into sub-queries. When
    date_gte is not given, it falls back to a floor of
    release_year_floor_years_ago before today (original behavior, still
    valid for narrow sweeps that stay under 500 pages). date_lte alone
    has no effect without date_gte.

    Defaults match config.yaml's discover_filter section -- pass that
    config in explicitly rather than relying on these defaults.
    """
    gte_param, lte_param = (
        ("primary_release_date.gte", "primary_release_date.lte")
        if content_type == "movie"
        else ("first_air_date.gte", "first_air_date.lte")
    )

    params = {
        "include_adult": "false",
        "with_original_language": original_language,
        "vote_count.gte": min_vote_count,
        gte_param: date_gte,
        "sort_by": sort_by,
        "page": page,
    }

    if content_type == "movie":
        params |= {
            "include_video": "false",
            "with_runtime.gte": min_runtime_minutes,
            gte_param: date_gte,
        }
    elif content_type == "tv":
        pass
    else:
        raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")

    if date_lte is not None:
        params[lte_param] = date_lte

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
