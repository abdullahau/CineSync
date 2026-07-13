-- TMDB service snapshot. One row per title (TMDB is the source of every title).
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_tmdb.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.tmdb_flat;

CREATE TABLE flatdb.tmdb_flat AS
WITH genres_agg AS (
    SELECT title_id, GROUP_CONCAT(genre, ', ') AS genres
    FROM title_genres
    GROUP BY title_id
),
tmdb_keywords_agg AS (
    SELECT title_id, GROUP_CONCAT(keyword, ', ') AS tmdb_keywords
    FROM title_keywords
    WHERE source = 'tmdb'
    GROUP BY title_id
),
companies_agg AS (
    SELECT title_id, GROUP_CONCAT(company_name, ', ') AS companies
    FROM title_companies
    GROUP BY title_id
),
credits_agg AS (
    SELECT
        title_id,
        GROUP_CONCAT(name, ', ') FILTER (WHERE role = 'director') AS directors,
        GROUP_CONCAT(name, ', ') FILTER (WHERE role = 'writer')   AS writers,
        GROUP_CONCAT(name, ', ') FILTER (WHERE role = 'creator')  AS creators,
        GROUP_CONCAT(name, ', ' ORDER BY "order") FILTER (WHERE role = 'cast') AS cast_members
    FROM title_credits
    GROUP BY title_id
),
crew_agg AS (
    SELECT
        title_id,
        GROUP_CONCAT(name, ', ') FILTER (WHERE job LIKE '%Producer%')            AS producers,
        GROUP_CONCAT(name, ', ') FILTER (WHERE job = 'Director of Photography')  AS dop
    FROM title_crew_extra
    GROUP BY title_id
),
tmdb_score_agg AS (
    SELECT
        title_id,
        MAX(CASE WHEN source = 'tmdb_rating' THEN score END)       AS tmdb_rating,
        MAX(CASE WHEN source = 'tmdb_rating' THEN sample_size END) AS tmdb_rating_count
    FROM title_scores
    GROUP BY title_id
),
pop_agg AS (
    -- latest tmdb_popularity snapshot per title
    SELECT title_id, value AS tmdb_popularity_latest, snapshot_date AS tmdb_popularity_date
    FROM (
        SELECT title_id, value, snapshot_date,
               ROW_NUMBER() OVER (PARTITION BY title_id ORDER BY snapshot_date DESC) AS rn
        FROM title_popularity
        WHERE source = 'tmdb_popularity'
    )
    WHERE rn = 1
),
recs_out_agg AS (
    SELECT seed_title_id AS title_id, COUNT(*) AS recs_out
    FROM title_recommendation_links
    GROUP BY seed_title_id
),
recs_in_agg AS (
    SELECT recommended_title_id AS title_id, COUNT(*) AS recs_in
    FROM title_recommendation_links
    GROUP BY recommended_title_id
)
SELECT
    t.title_id,
    t.tmdb_id,
    t.content_type,
    t.name,
    t.original_language,
    t.release_year,
    t.certificate,
    t.runtime_minutes,
    t.number_of_seasons,
    t.status,
    t.tmdb_overview,
    LENGTH(t.tmdb_overview)                    AS tmdb_overview_len,
    t.source,
    t.date_added,
    t.last_refreshed,
    (t.imdb_id     IS NOT NULL)                AS has_imdb_id,
    (t.wikidata_id IS NOT NULL)                AS has_wikidata_id,
    g.genres,
    k.tmdb_keywords,
    c.companies,
    cr.directors,
    cr.writers,
    cr.creators,
    cr.cast_members,
    cw.producers,
    cw.dop,
    p.tagline,
    ts.tmdb_rating,
    ts.tmdb_rating_count,
    pop.tmdb_popularity_latest,
    pop.tmdb_popularity_date,
    COALESCE(ro.recs_out, 0)                   AS recs_out,
    COALESCE(ri.recs_in, 0)                    AS recs_in
FROM titles t
LEFT JOIN genres_agg        g   ON g.title_id   = t.title_id
LEFT JOIN tmdb_keywords_agg k   ON k.title_id   = t.title_id
LEFT JOIN companies_agg     c   ON c.title_id   = t.title_id
LEFT JOIN credits_agg       cr  ON cr.title_id  = t.title_id
LEFT JOIN crew_agg          cw  ON cw.title_id  = t.title_id
LEFT JOIN title_plots       p   ON p.title_id   = t.title_id
LEFT JOIN tmdb_score_agg    ts  ON ts.title_id  = t.title_id
LEFT JOIN pop_agg           pop ON pop.title_id = t.title_id
LEFT JOIN recs_out_agg      ro  ON ro.title_id  = t.title_id
LEFT JOIN recs_in_agg       ri  ON ri.title_id  = t.title_id;

DETACH DATABASE flatdb;
