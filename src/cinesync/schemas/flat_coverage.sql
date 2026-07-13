-- Completeness / coverage snapshot: one row per title, presence + fetch-state
-- flags across every service. The workhorse for "which titles are missing X"
-- and "is missingness correlated with content_type / year / language". The
-- *_fetched_at vs *_error columns let you separate "never fetched" from
-- "fetched but legitimately empty".
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_coverage.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.coverage_flat;

CREATE TABLE flatdb.coverage_flat AS
SELECT
    t.title_id,
    t.content_type,
    t.release_year,
    t.original_language,

    -- cross-service linkage IDs
    (t.imdb_id     IS NOT NULL) AS has_imdb_id,
    (t.wikidata_id IS NOT NULL) AS has_wikidata_id,

    -- TMDB coverage
    EXISTS (SELECT 1 FROM title_genres         x WHERE x.title_id = t.title_id)                          AS has_genres,
    EXISTS (SELECT 1 FROM title_keywords       x WHERE x.title_id = t.title_id AND x.source = 'tmdb')     AS has_tmdb_keywords,
    EXISTS (SELECT 1 FROM title_credits        x WHERE x.title_id = t.title_id)                          AS has_credits,
    EXISTS (SELECT 1 FROM title_companies      x WHERE x.title_id = t.title_id)                          AS has_companies,
    EXISTS (SELECT 1 FROM title_scores         x WHERE x.title_id = t.title_id AND x.source = 'tmdb_rating') AS has_tmdb_rating,
    (t.tmdb_overview IS NOT NULL)                                                                        AS has_tmdb_overview,

    -- Letterboxd coverage
    (lb.title_id IS NOT NULL)                                                                           AS has_lb_stats,
    lb.letterboxd_fetched_at,
    (lb.letterboxd_error IS NOT NULL)                                                                    AS lb_errored,

    -- IMDb coverage
    EXISTS (SELECT 1 FROM title_keywords x WHERE x.title_id = t.title_id AND x.source = 'imdb')          AS has_imdb_keywords,
    (COALESCE(pl.imdb_outline, pl.imdb_summary, pl.imdb_synopsis) IS NOT NULL)                           AS has_imdb_plot,
    EXISTS (SELECT 1 FROM title_scores x WHERE x.title_id = t.title_id AND x.source = 'imdb_rating')     AS has_imdb_rating,
    (d.total_votes IS NOT NULL)                                                                          AS has_imdb_dist,
    pl.imdb_fetched_at,
    (pl.imdb_error IS NOT NULL)                                                                          AS imdb_errored,
    (d.histogram_error IS NOT NULL)                                                                      AS imdb_histogram_errored,

    -- Wikidata coverage
    (wm.title_id IS NOT NULL)                                                                            AS has_wikidata_meta,
    wm.wikidata_fetched_at,
    (wm.wikidata_error IS NOT NULL)                                                                      AS wikidata_errored,
    EXISTS (SELECT 1 FROM title_awards x WHERE x.title_id = t.title_id)                                  AS has_awards,

    -- Wikipedia coverage
    (pl.wikipedia_plot IS NOT NULL)                                                                      AS has_wikipedia_plot,
    pl.wikipedia_fetched_at,
    (pl.wikipedia_error IS NOT NULL)                                                                     AS wikipedia_errored,

    -- Rotten Tomatoes coverage (slug resolution vs ratings fetch are separate)
    (rt.rt_slug IS NOT NULL)                                                                             AS has_rt_slug,
    rt.resolved_at                                                                                       AS rt_slug_resolved_at,
    EXISTS (SELECT 1 FROM title_scores x WHERE x.title_id = t.title_id AND x.source IN ('rt_critic','rt_audience')) AS has_rt_ratings,
    (SELECT MAX(x.date_pulled) FROM title_scores x WHERE x.title_id = t.title_id AND x.source IN ('rt_critic','rt_audience')) AS rt_ratings_fetched_at
FROM titles t
LEFT JOIN title_plots            pl ON pl.title_id = t.title_id
LEFT JOIN title_imdb_rating_dist d  ON d.title_id  = t.title_id
LEFT JOIN title_wikidata_meta    wm ON wm.title_id = t.title_id
LEFT JOIN title_letterboxd_stats lb ON lb.title_id = t.title_id
LEFT JOIN title_rt               rt ON rt.title_id = t.title_id;

DETACH DATABASE flatdb;
