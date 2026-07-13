-- Rotten Tomatoes service snapshot: TMDB title spine LEFT JOIN the RT slug
-- (title_rt) and the RT ratings (title_scores rt_critic/rt_audience).
--
-- Two DISTINCT timestamps, deliberately separated because they answer different
-- questions:
--   rt_slug_resolved_at   -- when the RT URL/slug was RESOLVED (Wikidata/search)
--   rt_ratings_fetched_at -- when the RT critic/audience SCORES were last pulled
-- (title_scores.date_pulled). The slug resolving says nothing about whether the
-- ratings behind it have been scraped yet.
--
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_rt.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.rt_flat;

CREATE TABLE flatdb.rt_flat AS
WITH rt_score_agg AS (
    SELECT
        title_id,
        MAX(CASE WHEN source = 'rt_critic'   THEN score END)       AS rt_critic,
        MAX(CASE WHEN source = 'rt_critic'   THEN sample_size END) AS rt_critic_count,
        MAX(CASE WHEN source = 'rt_audience' THEN score END)       AS rt_audience,
        MAX(CASE WHEN source = 'rt_audience' THEN sample_size END) AS rt_audience_count,
        -- when the RT ratings were last pulled (latest across the two sources)
        MAX(CASE WHEN source IN ('rt_critic','rt_audience') THEN date_pulled END) AS rt_ratings_fetched_at
    FROM title_scores
    GROUP BY title_id
)
SELECT
    t.title_id,
    t.tmdb_id,
    t.content_type,
    t.name,
    t.release_year,

    -- slug resolution (title_rt): how the RT page was located, and when
    rt.rt_slug,
    (rt.rt_slug IS NOT NULL)                    AS has_rt_slug,
    rt.source                                   AS rt_slug_source,
    rt.resolved_at                              AS rt_slug_resolved_at,
    rt.last_error                               AS rt_slug_last_error,

    -- ratings (title_scores): the scores + when they were last pulled
    s.rt_critic,
    s.rt_critic_count,
    s.rt_audience,
    s.rt_audience_count,
    (s.rt_critic IS NOT NULL OR s.rt_audience IS NOT NULL) AS has_rt_ratings,
    s.rt_ratings_fetched_at
FROM titles t
LEFT JOIN title_rt     rt ON rt.title_id = t.title_id
LEFT JOIN rt_score_agg s  ON s.title_id  = t.title_id;

DETACH DATABASE flatdb;
