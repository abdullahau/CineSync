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

    # A successful ingest clears any prior fetch-failure row for this id.
    conn.execute(
        "DELETE FROM tmdb_ingest_errors WHERE tmdb_id=? AND content_type=?",
        (t["tmdb_id"], t["content_type"]),
    )

    conn.commit()
    return is_new


def mark_tmdb_ingest_error(
    conn: sqlite3.Connection,
    tmdb_id: int,
    content_type: str,
    source: str,
    error: str,
) -> None:
    """Record a TMDB per-title details fetch/parse failure. Keyed by
    (tmdb_id, content_type) because the failure precedes any titles row.
    Overwrites the prior row for this id (last failure wins); a later
    successful upsert_tmdb_title deletes it."""
    conn.execute(
        """INSERT INTO tmdb_ingest_errors (tmdb_id, content_type, source, error, fetched_at)
           VALUES (?, ?, ?, ?, datetime('now'))
           ON CONFLICT(tmdb_id, content_type) DO UPDATE SET
             source=excluded.source, error=excluded.error, fetched_at=excluded.fetched_at""",
        (tmdb_id, content_type, source, error),
    )
    conn.commit()


def known_tmdb_ids(conn, content_type: str) -> set:
    """Loaded once per notebook session, reused across the whole sweep -- not re-queried per page."""
    rows = conn.execute(
        "SELECT tmdb_id FROM titles WHERE content_type = ?", (content_type,)
    ).fetchall()
    return {r[0] for r in rows}


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
    The Letterboxd scrape work list + resume mechanism: titles whose stats
    have never landed OR last errored. A successful row (letterboxd_error
    NULL) drops off the list, so re-running picks up only what's left. The
    stats row is Letterboxd-exclusive, so "row exists with error NULL" == a
    clean success; keying on the error column (not fetched_at) means existing
    pre-migration rows -- written only on success -- stay done without a
    fabricated timestamp backfill.

    Returns (title_id, imdb_id, tmdb_id, content_type) per row. imdb_id may
    be NULL: the scraper falls back to the tmdb slug for movies, while TV
    titles without an imdb_id have no resolvable route.
    """
    return conn.execute(
        """
        SELECT t.title_id, t.imdb_id, t.tmdb_id, t.content_type
        FROM titles t
        LEFT JOIN title_letterboxd_stats s ON s.title_id = t.title_id
        WHERE s.title_id IS NULL OR s.letterboxd_error IS NOT NULL
        """
    ).fetchall()


def upsert_letterboxd_stats(conn: sqlite3.Connection, film: dict) -> None:
    """
    Write one scraped title's Letterboxd stats (rating value/count, the
    half-star histogram, and watches/lists/likes/top_rank). INSERT OR REPLACE
    keeps a single current row per title_id; letterboxd_fetched_at is stamped
    and letterboxd_error cleared, so a success supersedes any prior error row.
    """
    conn.execute(
        """INSERT OR REPLACE INTO title_letterboxd_stats (
            title_id, rating_value, rating_count, review_count,

            rating_0_5_count, rating_1_0_count, rating_1_5_count, rating_2_0_count,
            rating_2_5_count, rating_3_0_count, rating_3_5_count, rating_4_0_count,
            rating_4_5_count, rating_5_0_count,

            watches, lists, likes, top_rank,
            letterboxd_fetched_at, letterboxd_error
        )
        VALUES (
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            datetime('now'), NULL
        )""",
        _letterboxd_stats_row(film),
    )
    conn.commit()


def mark_letterboxd_error(conn: sqlite3.Connection, title_id: str, error: str) -> None:
    """
    Record a failed Letterboxd scrape: stamp letterboxd_fetched_at + the error
    without disturbing any stats already present (mirrors the IMDb/Wikipedia
    error convention). Keeps the title on the resume work list (error non-NULL)
    while making "tried and failed" distinguishable from "never tried".
    """
    conn.execute(
        """INSERT INTO title_letterboxd_stats (title_id, letterboxd_fetched_at, letterboxd_error)
           VALUES (?, datetime('now'), ?)
           ON CONFLICT(title_id) DO UPDATE SET
             letterboxd_fetched_at=excluded.letterboxd_fetched_at,
             letterboxd_error=excluded.letterboxd_error""",
        (title_id, error),
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


def titles_missing_imdb_rating_dist(conn):
    """IMDb ratings-histogram work list + resume mechanism: titles with a usable
    imdb_id that have no clean histogram row -- i.e. no row at all, OR a row whose
    last fetch errored (histogram_error set). A votes row with histogram_error
    NULL drops the title off. (A title that legitimately returns no ratings still
    leaves no row and is re-probed next run -- accepted, most titles rate.)"""
    return conn.execute(
        """
        SELECT t.title_id, t.imdb_id
        FROM titles t
        WHERE t.imdb_id IS NOT NULL AND t.imdb_id != ''
          AND NOT EXISTS (
              SELECT 1 FROM title_imdb_rating_dist d
              WHERE d.title_id = t.title_id AND d.histogram_error IS NULL
          )
        """
    ).fetchall()


def upsert_imdb_rating_dist(conn, title_id, rec):
    """Write one title's worldwide IMDb rating distribution into
    title_imdb_rating_dist (votes_1..votes_10 + total_votes). Overwrite-on-
    refresh via ON CONFLICT. Returns False (writes nothing) when there's no
    distribution -- total_votes falsy -- so a ratingless title leaves no row.
    A success clears any prior histogram_error."""
    if not rec.get("total_votes"):
        return False
    v = rec["votes"]
    conn.execute(
        """INSERT INTO title_imdb_rating_dist
             (title_id, votes_1, votes_2, votes_3, votes_4, votes_5,
              votes_6, votes_7, votes_8, votes_9, votes_10, total_votes,
              histogram_error, fetched_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, datetime('now'))
           ON CONFLICT(title_id) DO UPDATE SET
             votes_1=excluded.votes_1, votes_2=excluded.votes_2,
             votes_3=excluded.votes_3, votes_4=excluded.votes_4,
             votes_5=excluded.votes_5, votes_6=excluded.votes_6,
             votes_7=excluded.votes_7, votes_8=excluded.votes_8,
             votes_9=excluded.votes_9, votes_10=excluded.votes_10,
             total_votes=excluded.total_votes, histogram_error=NULL,
             fetched_at=datetime('now')""",
        (
            title_id,
            v[1],
            v[2],
            v[3],
            v[4],
            v[5],
            v[6],
            v[7],
            v[8],
            v[9],
            v[10],
            rec["total_votes"],
        ),
    )
    conn.commit()
    return True


def mark_imdb_histogram_error(conn, title_id, error):
    """Record a failed IMDb ratings-histogram sub-fetch in title_imdb_rating_dist,
    stamping histogram_error + fetched_at without disturbing any votes already
    present (ON CONFLICT preserves them). Distinct from title_plots.imdb_error,
    which owns storyline-enrichment failures. Keeps the title on the histogram
    resume list (histogram_error non-NULL)."""
    conn.execute(
        """INSERT INTO title_imdb_rating_dist (title_id, histogram_error, fetched_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(title_id) DO UPDATE SET
             histogram_error=excluded.histogram_error, fetched_at=excluded.fetched_at""",
        (title_id, error),
    )
    conn.commit()


def titles_missing_imdb_data(conn):
    """Union work list for the batched IMDb fetch: titles with a usable imdb_id
    that still need EITHER storyline enrichment (title_plots missing / never
    fetched / last errored) OR a ratings-distribution row. One batched request
    covers both, so a title appears once if it needs either and drops off only
    once both sides have landed. It's the OR-union of titles_missing_imdb_
    enrichment and titles_missing_imdb_rating_dist (histogram side retries on
    histogram_error, mirroring the storyline imdb_error retry)."""
    return conn.execute(
        """
        SELECT t.title_id, t.imdb_id
        FROM titles t
        LEFT JOIN title_plots p ON p.title_id = t.title_id
        WHERE t.imdb_id IS NOT NULL AND t.imdb_id != ''
          AND (
              p.title_id IS NULL OR p.imdb_fetched_at IS NULL OR p.imdb_error IS NOT NULL
              OR NOT EXISTS (
                  SELECT 1 FROM title_imdb_rating_dist d
                  WHERE d.title_id = t.title_id AND d.histogram_error IS NULL
              )
          )
        """
    ).fetchall()


# ===========================================================================
# Wikidata / Wikipedia enrichment
# ===========================================================================
#
# Stage A is a BULK refresh from QLever (not per-title WDQS): two global scans
# keyed on imdb_id, filtered to our titles, written in one transaction:
#   - title_awards          full-replace of source='wikidata' (idempotent re-run)
#   - title_wikidata_meta   1:1; wikidata_fetched_at stamped for EVERY attempted
#                           title -- it's the done-flag (a title that won nothing
#                           has zero award rows, so absence can't mean "unfetched")
#   - title_rt              only for titles whose Wikidata item carries a P1258
#                           RT slug; the rest are left for the search-engine resolver.
# Stage B (Wikipedia) fills title_plots.wikipedia_plot, mirroring the IMDb
# enrichment error/fetched_at convention (error preserves existing text).


def wikidata_target_titles(conn):
    """The universe Stage A can enrich: every title with an imdb_id (the QLever
    join key) or a wikidata_id. Returns (title_id, imdb_id, wikidata_id). The
    driver builds the imdb_id->title_id map from this and stamps every returned
    title's wikidata_fetched_at, so titles with no awards still register as done."""
    return conn.execute(
        """
        SELECT title_id, imdb_id, wikidata_id
        FROM titles
        WHERE (imdb_id IS NOT NULL AND imdb_id != '')
           OR (wikidata_id IS NOT NULL AND wikidata_id != '')
        """
    ).fetchall()


def replace_wikidata_data(conn, meta_rows, rt_rows, award_rows):
    """Bulk-write one full Stage-A refresh in a single transaction.

    - meta_rows:  [(title_id, wikipedia_url|None)] for EVERY attempted title
      (stamps wikidata_fetched_at = the done-flag; wikipedia_url may be None).
    - rt_rows:    [(title_id, rt_slug)] only for titles with a P1258 slug.
    - award_rows: [(title_id, statement_id, award_name, result, prestige,
      level, subject, year)] -- title_awards is full-replaced for
      source='wikidata' first, so the refresh is idempotent.
    """
    conn.executemany(
        """INSERT INTO title_wikidata_meta
             (title_id, wikipedia_url, wikidata_fetched_at, wikidata_error)
           VALUES (?, ?, datetime('now'), NULL)
           ON CONFLICT(title_id) DO UPDATE SET
             wikipedia_url=excluded.wikipedia_url,
             wikidata_fetched_at=excluded.wikidata_fetched_at,
             wikidata_error=NULL""",
        meta_rows,
    )
    conn.executemany(
        """INSERT INTO title_rt (title_id, rt_slug, source, resolved_at, last_error)
           VALUES (?, ?, 'wikidata', datetime('now'), NULL)
           ON CONFLICT(title_id) DO UPDATE SET
             rt_slug=excluded.rt_slug, source=excluded.source,
             resolved_at=excluded.resolved_at, last_error=NULL""",
        rt_rows,
    )
    conn.execute("DELETE FROM title_awards WHERE source='wikidata'")
    conn.executemany(
        """INSERT OR IGNORE INTO title_awards
             (title_id, statement_id, award_name, result, prestige, level, subject, year, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'wikidata')""",
        award_rows,
    )
    conn.commit()


def titles_missing_wikipedia_plot(conn):
    """Stage-B work list + resume: titles with a Wikipedia URL (from Stage A)
    whose plot fetch has never run OR last errored. A clean fetch -- whether it
    found a plot or terminally found no plot section (error NULL either way) --
    drops the title off. Returns (title_id, wikipedia_url)."""
    return conn.execute(
        """
        SELECT t.title_id, m.wikipedia_url
        FROM titles t
        JOIN title_wikidata_meta m ON m.title_id = t.title_id
        LEFT JOIN title_plots p ON p.title_id = t.title_id
        WHERE m.wikipedia_url IS NOT NULL AND m.wikipedia_url != ''
          AND (p.title_id IS NULL OR p.wikipedia_fetched_at IS NULL
               OR p.wikipedia_error IS NOT NULL)
        """
    ).fetchall()


def upsert_wikipedia_plot(conn, title_id, plot, error):
    """Write one title's Wikipedia plot into title_plots. On error, only
    wikipedia_error/fetched_at are stamped and existing text is preserved. On
    success (error is None -- plot may still be None for a plotless article),
    wikipedia_plot is written and the error cleared."""
    if error is not None:
        conn.execute(
            """INSERT INTO title_plots (title_id, wikipedia_error, wikipedia_fetched_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(title_id) DO UPDATE SET
                 wikipedia_error=excluded.wikipedia_error,
                 wikipedia_fetched_at=excluded.wikipedia_fetched_at""",
            (title_id, error),
        )
    else:
        conn.execute(
            """INSERT INTO title_plots
                 (title_id, wikipedia_plot, wikipedia_error, wikipedia_fetched_at)
               VALUES (?, ?, NULL, datetime('now'))
               ON CONFLICT(title_id) DO UPDATE SET
                 wikipedia_plot=excluded.wikipedia_plot,
                 wikipedia_error=NULL,
                 wikipedia_fetched_at=excluded.wikipedia_fetched_at""",
            (title_id, plot),
        )
    conn.commit()
