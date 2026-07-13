-- IMDb service snapshot: TMDB title spine LEFT JOIN all IMDb-sourced data
-- (plots, keywords, rating, ratings histogram, fetch state).
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_imdb.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.imdb_flat;

CREATE TABLE flatdb.imdb_flat AS
WITH imdb_keywords_agg AS (
    SELECT title_id, GROUP_CONCAT(keyword, ', ') AS imdb_keywords
    FROM title_keywords
    WHERE source = 'imdb'
    GROUP BY title_id
),
imdb_score_agg AS (
    SELECT
        title_id,
        MAX(CASE WHEN source = 'imdb_rating' THEN score END)       AS imdb_rating,
        MAX(CASE WHEN source = 'imdb_rating' THEN sample_size END) AS imdb_rating_count
    FROM title_scores
    GROUP BY title_id
)
SELECT
    t.title_id,
    t.tmdb_id,
    t.content_type,
    t.name,
    t.release_year,
    t.original_language,
    t.imdb_id,
    (t.imdb_id IS NOT NULL)                     AS has_imdb_id,

    -- long-form plot text (full text + length for scannability)
    p.imdb_outline,   LENGTH(p.imdb_outline)    AS imdb_outline_len,
    p.imdb_summary,   LENGTH(p.imdb_summary)    AS imdb_summary_len,
    p.imdb_synopsis,  LENGTH(p.imdb_synopsis)   AS imdb_synopsis_len,

    k.imdb_keywords,

    s.imdb_rating,
    s.imdb_rating_count,

    -- ratings histogram (title_imdb_rating_dist)
    d.total_votes                               AS imdb_dist_total_votes,
    ( 1 * d.votes_1 + 2 * d.votes_2 + 3 * d.votes_3 + 4 * d.votes_4 + 5 * d.votes_5
    + 6 * d.votes_6 + 7 * d.votes_7 + 8 * d.votes_8 + 9 * d.votes_9 + 10 * d.votes_10 )
      * 1.0 / NULLIF(d.total_votes, 0)          AS imdb_hist_implied_rating,
    d.votes_1, d.votes_2, d.votes_3, d.votes_4, d.votes_5,
    d.votes_6, d.votes_7, d.votes_8, d.votes_9, d.votes_10,
    -- histogram total should match title_scores.sample_size for imdb_rating
    (s.imdb_rating_count = d.total_votes)       AS votes_checksum_ok,
    d.histogram_error                           AS imdb_histogram_error,
    d.fetched_at                                AS imdb_dist_fetched_at,

    -- storyline enrichment state (kept separate from the histogram above)
    p.imdb_error,
    p.imdb_fetched_at,
    (p.imdb_fetched_at IS NOT NULL)             AS imdb_fetched
FROM titles t
LEFT JOIN title_plots           p ON p.title_id = t.title_id
LEFT JOIN imdb_keywords_agg     k ON k.title_id = t.title_id
LEFT JOIN imdb_score_agg        s ON s.title_id = t.title_id
LEFT JOIN title_imdb_rating_dist d ON d.title_id = t.title_id;

DETACH DATABASE flatdb;
