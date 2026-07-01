"""
TMDB fetch primitives for Phase 1b candidate discovery.

known_ids = known_tmdb_ids(conn, "movie")
for page in range(1, 6):
    payload = fetch_discover_page("movie", "ja", page, api_key, session, **filters)
    for entry in payload["results"]:
        result = process_one_candidate(conn, "movie", entry["id"], api_key, session,
                                        known_ids, source_tag="discover_lang_ja")
        print(entry["id"], result)
    if page >= payload.get("total_pages", 1):
        break
"""

from cinesync.discover import paced_get, build_discover_params
from cinesync.tmdb_parser import parse_tmdb_response
from cinesync.db_writer import upsert_parsed_title

TMDB_BASE = "https://api.themoviedb.org/3"


def known_tmdb_ids(conn, content_type: str) -> set:
    """Loaded once per notebook session, reused across the whole sweep -- not re-queried per page."""
    rows = conn.execute(
        "SELECT tmdb_id FROM titles WHERE content_type = ?", (content_type,)
    ).fetchall()
    return {r[0] for r in rows}


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
    content_type: str, language: str, page: int, api_key: str, session, **filter_kwargs
) -> dict:
    """
    One page of one language's /discover sweep. filter_kwargs are
    passed straight to build_discover_params (min_vote_count,
    min_runtime_minutes, sort_by, date_gte, date_lte) -- pass
    config.yaml's discover_filter values plus the current window's
    date bounds here explicitly.
    """
    url = f"{TMDB_BASE}/discover/{content_type}"
    params = build_discover_params(content_type, language, page=page, **filter_kwargs)
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


# TODO: `process_one_candidate` is a first entry function, i.e. not for updating titles. Create a similar function for updating.
def process_one_candidate(
    conn,
    content_type: str,
    tmdb_id: int,
    api_key: str,
    session,
    known_ids: set,
    source_tag: str,
) -> str:
    """
    The one shared step every discovery source needs: skip the detail
    fetch entirely if already known (the expensive call), otherwise
    fetch + parse + upsert. Returns 'new' or 'already_known' for the
    notebook to print/count as it likes. No candidate_pool side-effect
    -- eligibility is now just `unwatched_titles`, computed live, not
    written here.
    """
    if tmdb_id in known_ids:
        return "already_known"

    details = fetch_title_details(content_type, tmdb_id, api_key, session)
    parsed = parse_tmdb_response(details, content_type=content_type, source=source_tag)
    upsert_parsed_title(conn, parsed)
    known_ids.add(tmdb_id)
    return "new"


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
