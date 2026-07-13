-- Letterboxd service snapshot: TMDB title spine LEFT JOIN Letterboxd stats.
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_letterboxd.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.letterboxd_flat;

CREATE TABLE flatdb.letterboxd_flat AS
SELECT
    t.title_id,
    t.tmdb_id,
    t.content_type,
    t.name,
    t.release_year,
    t.original_language,
    (l.title_id IS NOT NULL)                   AS has_lb_stats,
    l.letterboxd_fetched_at,
    l.letterboxd_error,

    l.rating_value                             AS letterboxd_rating,
    l.rating_count,
    l.review_count,

    -- raw distribution buckets
    l.rating_0_5_count, l.rating_1_0_count, l.rating_1_5_count,
    l.rating_2_0_count, l.rating_2_5_count, l.rating_3_0_count,
    l.rating_3_5_count, l.rating_4_0_count, l.rating_4_5_count,
    l.rating_5_0_count,

    -- derived from the buckets
    ( l.rating_0_5_count + l.rating_1_0_count + l.rating_1_5_count
    + l.rating_2_0_count + l.rating_2_5_count + l.rating_3_0_count
    + l.rating_3_5_count + l.rating_4_0_count + l.rating_4_5_count
    + l.rating_5_0_count )                      AS lb_rating_count_derived,
    ( 0.5 * l.rating_0_5_count + 1.0 * l.rating_1_0_count + 1.5 * l.rating_1_5_count
    + 2.0 * l.rating_2_0_count + 2.5 * l.rating_2_5_count + 3.0 * l.rating_3_0_count
    + 3.5 * l.rating_3_5_count + 4.0 * l.rating_4_0_count + 4.5 * l.rating_4_5_count
    + 5.0 * l.rating_5_0_count )                AS lb_rating_weighted_sum,
    ( 0.5 * l.rating_0_5_count + 1.0 * l.rating_1_0_count + 1.5 * l.rating_1_5_count
    + 2.0 * l.rating_2_0_count + 2.5 * l.rating_2_5_count + 3.0 * l.rating_3_0_count
    + 3.5 * l.rating_3_5_count + 4.0 * l.rating_4_0_count + 4.5 * l.rating_4_5_count
    + 5.0 * l.rating_5_0_count )
      / NULLIF( l.rating_0_5_count + l.rating_1_0_count + l.rating_1_5_count
              + l.rating_2_0_count + l.rating_2_5_count + l.rating_3_0_count
              + l.rating_3_5_count + l.rating_4_0_count + l.rating_4_5_count
              + l.rating_5_0_count, 0)          AS lb_implied_rating,

    l.watches,
    l.lists,
    l.likes,
    l.top_rank
FROM titles t
LEFT JOIN title_letterboxd_stats l ON l.title_id = t.title_id;

DETACH DATABASE flatdb;
