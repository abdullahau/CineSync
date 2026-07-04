"""
Writes a parse_tmdb_response() result into the actual database, in
one transaction across every table it touches.

discover -> details -> DB pipeline

Upsert semantics, per table:
  - titles: INSERT on first sight; on a refresh of an existing title,
    UPDATE the mutable fields and bump last_refreshed. tmdb_id,
    content_type, original_language never change once set.
  - title_genres / title_companies / title_credits / title_crew_extra:
    INSERT OR IGNORE. These are attribute lists, not single values --
    there's no "update" to perform per row, and if TMDB's data shifts
    slightly between refreshes (rare), we accept the simplification of
    not pruning stale rows for v1 rather than diffing the full set.
  - title_keywords: full replace (DELETE then re-INSERT) Keywords change
    over time and directly drive theme/mood matching
  - external_scores: upsert (overwrite the score/sample_size in place)
    -- this table is explicitly designed to hold only the current
    value per (title_id, source), per its own schema comment.
"""

import sqlite3


# TODO: modify any other table/column that can be updated in the upsert function below, i.e. genres and credits (maybe?)
def upsert_parsed_title(conn: sqlite3.Connection, parsed: dict) -> bool:
    """
    Returns True if this was a brand-new title (first INSERT), False
    if it already existed and was refreshed instead. Callers use this
    to decide whether a detail-fetch was "new" or just "refreshed" for
    logging/counting purposes.
    """
    t = parsed["title"]
    existing = conn.execute(
        "SELECT 1 FROM titles WHERE title_id = ?", (t["title_id"],)
    ).fetchone()

    if existing is None:
        conn.execute(
            """INSERT INTO titles
               (title_id, tmdb_id, content_type, name, original_language, release_year,
                runtime_minutes, number_of_seasons, status, imdb_id, wikidata_id,
                overview, detailed_plot, source)
               VALUES (:title_id, :tmdb_id, :content_type, :name, :original_language,
                       :release_year, :runtime_minutes, :number_of_seasons, :status,
                       :imdb_id, :wikidata_id, :overview, :detailed_plot, :source)""",
            t,
        )
        is_new = True
    else:
        conn.execute(
            """UPDATE titles SET
                 name=:name, original_language=:original_language, release_year=:release_year,
                 runtime_minutes=:runtime_minutes, number_of_seasons=:number_of_seasons,
                 status=:status, imdb_id=:imdb_id, wikidata_id=:wikidata_id,
                 overview=:overview, last_refreshed=datetime('now')
               WHERE title_id=:title_id""",
            t,
        )
        is_new = False

    title_id = t["title_id"]

    for g in parsed["genres"]:
        conn.execute("INSERT OR IGNORE INTO title_genres VALUES (?, ?)", (title_id, g))

    conn.execute("DELETE FROM title_keywords WHERE title_id = ?", (title_id,))
    for k in parsed["keywords"]:
        conn.execute("INSERT INTO title_keywords VALUES (?, ?)", (title_id, k))

    for c in parsed["companies"]:
        conn.execute(
            "INSERT OR IGNORE INTO title_companies VALUES (?, ?, ?)",
            (title_id, c["company_id"], c["company_name"]),
        )

    for cr in parsed["credits"]:
        conn.execute(
            "INSERT OR IGNORE INTO title_credits VALUES (?, ?, ?, ?)",
            (title_id, cr["role"], cr["name"], cr["order"]),
        )

    for ce in parsed["crew_extra"]:
        conn.execute(
            "INSERT OR IGNORE INTO title_crew_extra VALUES (?, ?, ?, ?)",
            (title_id, ce["job"], ce["name"], ce["department"]),
        )

    if parsed["external_score"] is not None:
        es = parsed["external_score"]
        conn.execute(
            """INSERT INTO external_scores (title_id, source, score, sample_size)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(title_id, source) DO UPDATE SET
                 score=excluded.score, sample_size=excluded.sample_size,
                 date_pulled=datetime('now')""",
            (title_id, es["source"], es["score"], es["sample_size"]),
        )

    conn.commit()
    return is_new


def known_tmdb_ids(conn, content_type: str) -> set:
    """Loaded once per notebook session, reused across the whole sweep -- not re-queried per page."""
    rows = conn.execute(
        "SELECT tmdb_id FROM titles WHERE content_type = ?", (content_type,)
    ).fetchall()
    return {r[0] for r in rows}


# TODO: OMDb (omdb_awards_text and external_score) & Wikipedia (title_awards and detailed_plot) upsert.


def record_recommendation_link(
    conn: sqlite3.Connection, seed_title_id: str, recommended_title_id: str, rank: int
) -> None:
    """
    Stores one TMDB /recommendations result as real, durable data --
    not just a transient discovery mechanism. (seed_title_id,
    recommended_title_id) is the table's PK, so this is naturally safe
    to call repeatedly without duplicating.
    """
    conn.execute(
        """INSERT OR IGNORE INTO title_recommendation_links
           (seed_title_id, recommended_title_id, rank) VALUES (?, ?, ?)""",
        (seed_title_id, recommended_title_id, rank),
    )
    conn.commit()


def seed_already_processed(conn: sqlite3.Connection, seed_title_id: str) -> bool:
    """
    Has this seed's /recommendations list already been pulled? Checked
    against title_recommendation_links directly -- its mere existence
    for this seed means the API call already happened, so there's no
    separate state table to keep in sync.
    """
    return (
        conn.execute(
            "SELECT 1 FROM title_recommendation_links WHERE seed_title_id = ? LIMIT 1",
            (seed_title_id,),
        ).fetchone()
        is not None
    )
