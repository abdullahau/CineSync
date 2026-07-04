"""
Phase 1b: build the candidate pool via TMDB's /discover/movie and
/discover/tv -- one sweep per language in config.yaml's languages_of_interest.
"""

import time


def build_discover_params(
    content_type: str,
    page: int,
    original_language: str | None = None,
    min_vote_count: int = 50,
    min_runtime_minutes: int = 40,
    date_gte: str | None = None,
    date_lte: str | None = None,
) -> dict:
    """
    Build query params for one page of a /discover sweep.

    Date filter: movies use `primary_release_date.gte/.lte`;
    TV uses `first_air_date.gte/.lte`.

    Runtime filter: the runtime floor exists to drop short films,
    for movies only.

    Sort is ALWAYS by release/first-air date ascending.

    original_language is optional: pass it for a per-language sweep, or
    omit it for a broad all-languages sweep.

    Date windowing: pass explicit `date_gte`/`date_lte` ('YYYY-MM-DD')
    to bound one window. Either bound is optional and simply omitted
    from the query when None. The caller (the sweep's windowing loop)
    supplies the floor/ceiling.
    """
    gte_param, lte_param = (
        ("primary_release_date.gte", "primary_release_date.lte")
        if content_type == "movie"
        else ("first_air_date.gte", "first_air_date.lte")
    )

    params = {
        "include_adult": "false",
        "vote_count.gte": min_vote_count,
        "page": page,
    }

    if original_language:
        params["with_original_language"] = original_language

    if content_type == "movie":
        params |= {
            "include_video": "false",
            "with_runtime.gte": min_runtime_minutes,
            "sort_by": "primary_release_date.asc",
        }
    elif content_type == "tv":
        params["sort_by"] = "first_air_date.asc"
    else:
        raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")

    if date_gte is not None:
        params[gte_param] = date_gte
    if date_lte is not None:
        params[lte_param] = date_lte

    return params


def paced_get(
    session,
    url: str,
    params: dict,
    headers: dict,
    min_interval: float = 0.05,
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
