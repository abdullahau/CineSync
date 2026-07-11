"""
Phase 1: parse a raw TMDB API response (movie or TV) into rows ready
for the CineSync schema.

Call TMDB like this for BOTH movie and TV:

    Movie:  /movie/{id}?append_to_response=keywords,credits,external_ids
    TV:     /tv/{id}?append_to_response=keywords,credits,external_ids

Usage:
    from parse_tmdb import parse_tmdb_response
    parsed = parse_tmdb_response(raw_json, content_type="movie", source="tmdb_discover")
    parsed["title"]      -> dict, one row for the `titles` table
    parsed["genres"]     -> list[str], rows for `title_genres`
    parsed["keywords"]   -> list[str], rows for `title_keywords`
    parsed["companies"]  -> list[dict], rows for `title_companies`
    parsed["credits"]    -> list[dict], rows for `title_credits` (director/writer/creator/cast)
    parsed["crew_extra"] -> list[dict], rows for `title_crew_extra` (producer-tier + DP)
"""

WRITER_JOBS = {"Writer", "Screenplay", "Story", "Teleplay"}

# Producer-tier job titles, ordered roughly senior-to-junior. Stored
# verbatim in title_crew_extra rather than collapsed to one role --
# "main producer" can be defined later as job == "Producer" exactly.
PRODUCER_JOBS = {
    "Producer",
    "Executive Producer",
    "Co-Producer",
    "Co-Executive Producer",
    "Supervising Producer",
    "Consulting Producer",
    "Line Producer",
    "Associate Producer",
}
DP_JOBS = {"Director of Photography", "Cinematographer"}


def _parse_title_row(data: dict, content_type: str, source: str) -> dict:
    if content_type == "movie":
        name = data["title"]
        release_date = data.get("release_date")
        runtime_minutes = data.get("runtime")
        number_of_seasons = None
    elif content_type == "tv":
        name = data["name"]
        release_date = data.get("first_air_date")
        episode_run_time = data.get("episode_run_time") or []
        if episode_run_time:
            runtime_minutes = round(sum(episode_run_time) / len(episode_run_time))
        else:
            last_ep = data.get("last_episode_to_air") or {}
            runtime_minutes = last_ep.get("runtime")
        number_of_seasons = data.get("number_of_seasons")
    else:
        raise ValueError(f"content_type must be 'movie' or 'tv', got {content_type!r}")

    release_year = int(release_date[:4]) if release_date else None

    external_ids = data.get("external_ids") or {}

    return {
        "title_id": f"{content_type}_{data['id']}",
        "tmdb_id": data["id"],
        "content_type": content_type,
        "name": name,
        "original_language": data.get("original_language"),
        "release_year": release_year,
        "runtime_minutes": runtime_minutes,
        "number_of_seasons": number_of_seasons,
        "status": data.get("status"),
        "imdb_id": external_ids.get("imdb_id") or None,
        "wikidata_id": external_ids.get("wikidata_id") or None,
        "overview": data.get("overview") or None,
        "detailed_plot": None,  # filled in later by the Wikipedia enrichment step
        "source": source,
    }


def _parse_genres(data: dict) -> list[str]:
    return [g["name"] for g in data.get("genres", [])]


def _parse_keywords(data: dict, content_type: str) -> list[str]:
    kw_block = data.get("keywords", {})
    if content_type == "movie":
        kw_list = kw_block.get("keywords", [])
    else:
        kw_list = kw_block.get("results", [])
    return [k["name"] for k in kw_list]


def _parse_companies(data: dict) -> list[dict]:
    return [
        {"company_id": c.get("id"), "company_name": c["name"]}
        for c in data.get("production_companies", [])
    ]


def _parse_credits(data: dict, content_type: str) -> list[dict]:
    rows = []

    credits_block = data.get("credits", {})

    # Cast "order" is billing order
    for c in credits_block.get("cast", []):
        rows.append({"role": "cast", "name": c["name"], "order": c.get("order")})

    for c in credits_block.get("crew", []):
        job = c.get("job")
        if job == "Director":
            rows.append({"role": "director", "name": c["name"], "order": None})
        elif job in WRITER_JOBS:
            rows.append({"role": "writer", "name": c["name"], "order": None})

    if content_type == "tv":
        for c in data.get("created_by", []):
            rows.append({"role": "creator", "name": c["name"], "order": None})

    seen = set()
    deduped = []
    for row in rows:
        key = (row["role"], row["name"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def _parse_crew_extra(data: dict) -> list[dict]:
    """
    Producer-tier credits (Producer, Executive Producer, Co-Producer,
    Supervising Producer, Consulting Producer, etc.) plus Director of
    Photography.
    """
    rows = []
    for c in data.get("credits", {}).get("crew", []):
        job = c.get("job")
        if job in PRODUCER_JOBS or job in DP_JOBS:
            rows.append(
                {"job": job, "name": c["name"], "department": c.get("department")}
            )

    seen = set()
    deduped = []
    for row in rows:
        key = (row["job"], row["name"])
        if key not in seen:
            seen.add(key)
            deduped.append(row)
    return deduped


def _parse_tmdb_score(data: dict) -> dict | None:
    vote_count = data.get("vote_count") or 0
    if vote_count == 0:
        return None
    return {
        "source": "tmdb_rating",
        "score": round(
            data["vote_average"] * 10, 2
        ),  # TMDB's 0-10 -> this table's 0-100 convention
        "sample_size": vote_count,
    }


def parse_tmdb_response(
    data: dict, content_type: str, source: str = "tmdb_discover"
) -> dict:
    return {
        "title": _parse_title_row(data, content_type, source),
        "genres": _parse_genres(data),
        "keywords": _parse_keywords(data, content_type),
        "companies": _parse_companies(data),
        "credits": _parse_credits(data, content_type),
        "crew_extra": _parse_crew_extra(data),
        "score": _parse_tmdb_score(data),
    }
