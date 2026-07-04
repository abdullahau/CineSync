from cinesync.utils.net import paced_get

TMDB_BASE = "https://api.themoviedb.org/3"


def build_discover_params(
    content_type: str,
    page: int,
    lang: str | None = None,
    min_rating: float | None = None,
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

    if lang:
        params["with_original_language"] = lang

    if min_rating:
        params["vote_average.gte"] = min_rating

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


def fetch_title_details(content_type: str, tmdb_id: int, api_key: str, session) -> dict:
    """
    One detail call -- movie or tv, always with the same
    append_to_response so every call uniformly returns keywords,
    credits, and external_ids regardless of content type.
    """
    url = f"{TMDB_BASE}/{content_type}/{tmdb_id}"
    params = {"append_to_response": "keywords,credits,external_ids"}
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = paced_get(session, url, params, headers)
    response.raise_for_status()
    return response.json()


def fetch_discover_page(
    content_type: str, page: int, api_key: str, session, **filter_kwargs
) -> dict:
    """
    One page of tmdb /discover sweep. filter_kwargs are filter params
    passed straight to build_discover_params (original_language,
    min_runtime_minutes, min_vote_count, date_gte, date_lte) -- build
    config.yaml's discover_sweep values into params and add the current
    window's date bounds here explicitly.
    """
    url = f"{TMDB_BASE}/discover/{content_type}"
    params = build_discover_params(
        content_type=content_type, page=page, **filter_kwargs
    )
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = paced_get(session, url, params, headers)
    response.raise_for_status()
    return response.json()


def fetch_recommendations_page(
    content_type: str, tmdb_id: int, api_key: str, session, page: int = 1
) -> dict:
    """One page of TMDB's /recommendations for a seed title -- same paginated shape as /discover."""
    url = f"{TMDB_BASE}/{content_type}/{tmdb_id}/recommendations"
    params = {"page": page}
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    response = paced_get(session, url, params, headers)
    response.raise_for_status()
    return response.json()


# TODO: Create a function for updating existing entries.


# TODO: /recommendations processing function get_highly_rated_seed_titles > check seed_already_processed > fetch_recommendations_page > parse this page in some way > record_recommendation_link


def get_highly_rated_seed_titles(
    conn, content_type: str, min_rating: float = 4.0
) -> list:
    """
    Seeds for a /recommendations sweep: any title ANY person in the
    group rated at or above min_rating, via current_ratings.
    """
    rows = conn.execute(
        """SELECT DISTINCT t.tmdb_id
           FROM current_ratings cr
           JOIN titles t ON t.title_id = cr.title_id
           WHERE cr.rating >= ? AND t.content_type = ?""",
        (min_rating, content_type),
    ).fetchall()
    return [r[0] for r in rows]
