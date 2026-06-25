"""
Phase 1: parse a raw TMDB API response (movie or TV) into rows ready
for the CineSync schema.

Call TMDB like this for BOTH movie and TV

    Movie:  /movie/{id}?append_to_response=keywords,credits,external_ids
    TV:     /tv/{id}?append_to_response=keywords,credits,external_ids

external_ids gives you imdb_id (for OMDb critic scores) and
wikidata_id (for the Wikipedia plot lookup -- query Wikidata's
wbgetentities by this id directly)

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
        # TV has no single "runtime" field. episode_run_time is often
        # an empty list (as in the Severance payload) even for shows
        # with real episodes -- fall back to the most recent aired
        # episode's runtime when that happens.
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

    # external_ids is identical in shape for movie and TV -- no
    # branching needed here, unlike runtime/name above.
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
        "imdb_id": external_ids.get("imdb_id"),
        "wikidata_id": external_ids.get("wikidata_id"),
        "overview": data.get("overview"),
        "detailed_plot": None,  # filled in later by the Wikipedia enrichment step
        "source": source,
    }


def _parse_genres(data: dict) -> list[str]:
    # Identical shape for movie and TV -- no branching needed.
    return [g["name"] for g in data.get("genres", [])]


def _parse_keywords(data: dict, content_type: str) -> list[str]:
    # The one TMDB gotcha that bites everyone: movies nest keywords
    # under "keywords", TV nests the identical data under "results".
    kw_block = data.get("keywords", {})
    if content_type == "movie":
        kw_list = kw_block.get("keywords", [])
    else:
        kw_list = kw_block.get("results", [])
    return [k["name"] for k in kw_list]


def _parse_companies(data: dict) -> list[dict]:
    return [
        {
            "company_id": c.get("id"),
            "company_name": c["name"],
            "origin_country": c.get("origin_country"),
        }
        for c in data.get("production_companies", [])
    ]


def _parse_credits(data: dict, content_type: str) -> list[dict]:
    rows = []

    credits_block = data.get("credits", {})

    # Cast -- "order" is billing order, used for top-N bucketing in Phase 2.
    for c in credits_block.get("cast", []):
        rows.append({"role": "cast", "name": c["name"], "order": c.get("order")})

    # Crew -- IMPORTANT: match on "job" (this specific credit), never
    # on "known_for_department" (this person's general career area).
    # Real example from your data: Roberto Patino's known_for_department
    # is "Writing", but his job on this title is "Producer" -- using
    # known_for_department would have wrongly tagged him as a writer.
    for c in credits_block.get("crew", []):
        job = c.get("job")
        if job == "Director":
            rows.append({"role": "director", "name": c["name"], "order": None})
        elif job in WRITER_JOBS:
            rows.append({"role": "writer", "name": c["name"], "order": None})

    # TV-only: created_by is the showrunner/creator credit, and is
    # far more reliable for TV than crew job-title parsing -- TMDB's
    # top-level TV credits are sparse on director/writer since those
    # vary per episode rather than per series. It's expected and
    # normal for a TV title to end up with zero director/writer rows
    # here while still having a creator row -- that's not a bug, it's
    # a consequence of storing TV at series level rather than per-episode.
    if content_type == "tv":
        for c in data.get("created_by", []):
            rows.append({"role": "creator", "name": c["name"], "order": None})

    # A person can show up twice with overlapping job titles (e.g.
    # "Story" and "Screenplay" both map to role='writer') -- dedupe
    # on (role, name) since that's the table's primary key.
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
    Photography. job is kept verbatim -- see title_crew_extra in
    schema.sql for why this isn't collapsed into title_credits.
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
    }
