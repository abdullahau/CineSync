ATTACH DATABASE 'data/cinesync_flat.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.titles_flat;

CREATE TABLE flatdb.titles_flat AS
WITH genres_agg AS (
    SELECT title_id, GROUP_CONCAT(genre, ', ') AS genres
    FROM title_genres
    GROUP BY title_id
),
keywords_agg AS (
    SELECT title_id, GROUP_CONCAT(keyword, ', ') AS keywords
    FROM title_keywords
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
        GROUP_CONCAT(name ORDER BY "order", ', ') FILTER (WHERE role = 'cast') AS cast_members
    FROM title_credits
    GROUP BY title_id
),
scores_agg AS (
    SELECT
        title_id,
        MAX(CASE WHEN source = 'letterboxd_rating' THEN score END) AS letterboxd_rating,
        MAX(CASE WHEN source = 'rt_critic'         THEN score END) AS rt_critic,
        MAX(CASE WHEN source = 'rt_audience'       THEN score END) AS rt_audience,
        MAX(CASE WHEN source = 'imdb_rating'       THEN score END) AS imdb_rating,
        MAX(CASE WHEN source = 'tmdb_rating'       THEN score END) AS tmdb_rating
    FROM external_scores
    GROUP BY title_id
)
SELECT
    t.*,
    g.genres,
    k.keywords,
    c.companies,
    cr.directors,
    cr.writers,
    cr.creators,
    cr.cast_members,
    s.letterboxd_rating,
    s.rt_critic,
    s.rt_audience,
    s.imdb_rating,
    s.tmdb_rating
FROM titles t
LEFT JOIN genres_agg    g  ON g.title_id  = t.title_id
LEFT JOIN keywords_agg  k  ON k.title_id  = t.title_id
LEFT JOIN companies_agg c  ON c.title_id  = t.title_id
LEFT JOIN credits_agg   cr ON cr.title_id = t.title_id
LEFT JOIN scores_agg    s  ON s.title_id  = t.title_id;

DETACH DATABASE flatdb;