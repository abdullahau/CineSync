"""
Central CRUD layer for cinesync.db.

Every write into the database goes through a function here, so upsert
semantics live in one place instead of being scattered across the
discover/scrape notebooks. Two ingestion sources currently write:

  - TMDB details  (discover -> details -> DB):  upsert_tmdb_title()
  - Letterboxd scrape:                          upsert_letterboxd_stats()

plus TMDB /recommendations link bookkeeping.

Commit policy: each function commits its own transaction, so a caller can
treat one call as one durable unit of work.
"""

import sqlite3


# ===========================================================================
# TMDB title metadata
# ===========================================================================
#
# Upsert semantics, per table:
#   - titles: INSERT on first sight; on a refresh of an existing title,
#     UPDATE the mutable fields and bump last_refreshed. tmdb_id,
#     content_type, original_language never change once set.
#   - title_genres / title_companies / title_credits / title_crew_extra:
#     INSERT OR IGNORE. These are attribute lists, not single values --
#     there's no "update" to perform per row, and if TMDB's data shifts
#     slightly between refreshes (rare), we accept the simplification of
#     not pruning stale rows for v1 rather than diffing the full set.
#   - title_keywords: full replace (DELETE then re-INSERT). Keywords change
#     over time and directly drive theme/mood matching.
#   - title_scores: upsert (overwrite the score/sample_size in place)
#     -- this table is explicitly designed to hold only the current
#     value per (title_id, source), per its own schema comment.


# TODO: modify any other table/column that can be updated in the upsert function below, i.e. genres and credits (maybe?)
def upsert_tmdb_title(conn: sqlite3.Connection, parsed: dict) -> bool:
    """
    Write a parse_tmdb_response() result across every table it touches,
    in one transaction.

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
                tmdb_overview, source)
               VALUES (:title_id, :tmdb_id, :content_type, :name, :original_language,
                       :release_year, :runtime_minutes, :number_of_seasons, :status,
                       :imdb_id, :wikidata_id, :overview, :source)""",
            t,
        )
        is_new = True
    else:
        conn.execute(
            """UPDATE titles SET
                 name=:name, original_language=:original_language, release_year=:release_year,
                 runtime_minutes=:runtime_minutes, number_of_seasons=:number_of_seasons,
                 status=:status, imdb_id=:imdb_id, wikidata_id=:wikidata_id,
                 tmdb_overview=:overview, last_refreshed=datetime('now')
               WHERE title_id=:title_id""",
            t,
        )
        is_new = False

    title_id = t["title_id"]

    for g in parsed["genres"]:
        conn.execute("INSERT OR IGNORE INTO title_genres VALUES (?, ?)", (title_id, g))

    conn.execute(
        "DELETE FROM title_keywords WHERE title_id=? AND source='tmdb'", (title_id,)
    )
    for k in parsed["keywords"]:
        conn.execute(
            "INSERT OR IGNORE INTO title_keywords VALUES (?, ?, 'tmdb')", (title_id, k)
        )

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

    if parsed["score"] is not None:
        es = parsed["score"]
        conn.execute(
            """INSERT INTO title_scores (title_id, source, score, sample_size)
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


# TODO: OMDb (omdb_awards_text and title_score) & Wikipedia (title_awards and detailed_plot) upsert.


# ===========================================================================
# TMDB /recommendations links
# ===========================================================================


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


# ===========================================================================
# Letterboxd stats
# ===========================================================================


def _letterboxd_stats_row(film: dict) -> tuple:
    """
    Map a scraped Letterboxd `film` dict (the scraper's per-title result)
    onto the title_letterboxd_stats column order. The histogram arrives as
    star-labelled buckets; absent buckets default to 0, absent stats to NULL.
    """
    hist = {h["rating"]: h["count"] for h in film.get("histogram", [])}
    stats = film.get("stats") or {}
    return (
        film["title_id"],
        film["ratingValue"],
        film["ratingCount"],
        film["reviewCount"],
        hist.get("half-★", 0),
        hist.get("★", 0),
        hist.get("★½", 0),
        hist.get("★★", 0),
        hist.get("★★½", 0),
        hist.get("★★★", 0),
        hist.get("★★★½", 0),
        hist.get("★★★★", 0),
        hist.get("★★★★½", 0),
        hist.get("★★★★★", 0),
        stats.get("watches"),
        stats.get("lists"),
        stats.get("likes"),
        stats.get("top_rank"),
    )


def titles_missing_letterboxd_stats(conn: sqlite3.Connection) -> list:
    """
    The Letterboxd scrape work list: titles with no title_letterboxd_stats
    row yet. The anti-join is the resume mechanism -- a title drops off the
    list as soon as its row lands, so re-running picks up only what's left.

    Returns (title_id, imdb_id, tmdb_id, content_type) per row. imdb_id may
    be NULL: the scraper falls back to the tmdb slug for movies, while TV
    titles without an imdb_id have no resolvable route.
    """
    return conn.execute(
        """
        SELECT t.title_id, t.imdb_id, t.tmdb_id, t.content_type
        FROM titles t
        WHERE NOT EXISTS (
            SELECT 1 FROM title_letterboxd_stats s WHERE s.title_id = t.title_id
        )
        """
    ).fetchall()


def upsert_letterboxd_stats(conn: sqlite3.Connection, film: dict) -> None:
    """
    Write one scraped title's Letterboxd stats (rating value/count, the
    half-star histogram, and watches/lists/likes/top_rank). INSERT OR REPLACE
    keeps a single current row per title_id.
    """
    conn.execute(
        """INSERT OR REPLACE INTO title_letterboxd_stats (
            title_id, rating_value, rating_count, review_count,

            rating_0_5_count, rating_1_0_count, rating_1_5_count, rating_2_0_count,
            rating_2_5_count, rating_3_0_count, rating_3_5_count, rating_4_0_count,
            rating_4_5_count, rating_5_0_count,

            watches, lists, likes, top_rank
        )
        VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )""",
        _letterboxd_stats_row(film),
    )
    conn.commit()


# ===========================================================================
# IMDB Data
# ===========================================================================


def titles_missing_imdb_enrichment(conn):
    """IMDb scrape work list + resume mechanism: titles with a usable imdb_id
    whose enrichment has never landed OR last errored. A successful row
    (imdb_fetched_at set, imdb_error NULL) drops off the list, so re-running
    picks up only what's left."""
    return conn.execute(
        """
        SELECT t.title_id, t.imdb_id
        FROM titles t
        LEFT JOIN title_plots p ON p.title_id = t.title_id
        WHERE t.imdb_id IS NOT NULL AND t.imdb_id != ''
          AND (p.title_id IS NULL OR p.imdb_fetched_at IS NULL OR p.imdb_error IS NOT NULL)
        """
    ).fetchall()


def upsert_imdb_enrichment(conn, title_id, rec, genre_map=None):
    """Fan one scraped IMDb record across title_plots (plots + tagline),
    title_genres (additive), and title_keywords (source='imdb', full-replace
    scoped to that source). On error, only imdb_error/imdb_fetched_at are
    written -- existing text and wikipedia_plot are preserved."""
    err = rec.get("error")
    if err is not None:
        conn.execute(
            """INSERT INTO title_plots (title_id, imdb_fetched_at, imdb_error)
               VALUES (?, datetime('now'), ?)
               ON CONFLICT(title_id) DO UPDATE SET
                 imdb_fetched_at=excluded.imdb_fetched_at,
                 imdb_error=excluded.imdb_error""",
            (title_id, err),
        )
        conn.commit()
        return

    genre_map = genre_map or {}
    taglines = rec.get("taglines") or []
    tagline = (
        taglines[0] if taglines else None
    )  # collapse to the first; IMDb owns this column

    conn.execute(
        """INSERT INTO title_plots
             (title_id, imdb_outline, imdb_summary, imdb_synopsis,
              tagline, imdb_fetched_at, imdb_error)
           VALUES (?, ?, ?, ?, ?, datetime('now'), NULL)
           ON CONFLICT(title_id) DO UPDATE SET
             imdb_outline=excluded.imdb_outline, imdb_summary=excluded.imdb_summary,
             imdb_synopsis=excluded.imdb_synopsis, tagline=excluded.tagline,
             imdb_fetched_at=excluded.imdb_fetched_at, imdb_error=NULL""",
        (
            title_id,
            rec.get("outline"),
            rec.get("summary"),
            rec.get("synopsis"),
            tagline,
        ),
    )

    for g in rec.get("genres") or []:
        g = g.strip()
        if g:
            conn.execute(
                "INSERT OR IGNORE INTO title_genres VALUES (?, ?)",
                (title_id, genre_map.get(g, g)),
            )

    conn.execute(
        "DELETE FROM title_keywords WHERE title_id=? AND source='imdb'", (title_id,)
    )
    conn.executemany(
        "INSERT OR IGNORE INTO title_keywords (title_id, keyword, source) VALUES (?, ?, 'imdb')",
        [(title_id, k) for k in (rec.get("keywords") or [])],
    )
    conn.commit()
