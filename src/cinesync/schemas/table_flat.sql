ATTACH DATABASE 'data/cinesync_flat.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.titles_flat;

CREATE TABLE flatdb.titles_flat AS
WITH genres_agg AS (
    SELECT title_id, GROUP_CONCAT(genre, ', ') AS genres
    FROM title_genres
    GROUP BY title_id
),
keywords_agg AS (
    SELECT
        title_id,
        GROUP_CONCAT(keyword, ', ')                              AS keywords,
        GROUP_CONCAT(keyword, ', ') FILTER (WHERE source = 'imdb') AS imdb_keywords
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
        GROUP_CONCAT(name, ', ' ORDER BY "order") FILTER (WHERE role = 'cast') AS cast_members
    FROM title_credits
    GROUP BY title_id
),
scores_agg AS (
    SELECT
        title_id,
        MAX(CASE WHEN source = 'rt_critic'   THEN score END) AS rt_critic,
        MAX(CASE WHEN source = 'rt_audience' THEN score END) AS rt_audience,
        MAX(CASE WHEN source = 'imdb_rating' THEN score END) AS imdb_rating,
        MAX(CASE WHEN source = 'imdb_rating' THEN sample_size END) AS imdb_rating_count,
        MAX(CASE WHEN source = 'tmdb_rating' THEN score END) AS tmdb_rating,
        MAX(CASE WHEN source = 'tmdb_rating' THEN sample_size END) AS tmdb_rating_count
    FROM title_scores
    GROUP BY title_id
),
letterboxd_base AS (
    SELECT
        title_id,
        rating_value AS letterboxd_rating,
        watches      AS lb_watches,
        lists        AS lb_lists,
        likes        AS lb_likes,
        top_rank     AS lb_top_rank,
        ( 0.5 * rating_0_5_count + 1.0 * rating_1_0_count + 1.5 * rating_1_5_count
        + 2.0 * rating_2_0_count + 2.5 * rating_2_5_count + 3.0 * rating_3_0_count
        + 3.5 * rating_3_5_count + 4.0 * rating_4_0_count + 4.5 * rating_4_5_count
        + 5.0 * rating_5_0_count ) AS lb_rating_weighted_sum,
        ( rating_0_5_count + rating_1_0_count + rating_1_5_count
        + rating_2_0_count + rating_2_5_count + rating_3_0_count
        + rating_3_5_count + rating_4_0_count + rating_4_5_count
        + rating_5_0_count ) AS lb_rating_count
    FROM title_letterboxd_stats
),
letterboxd_agg AS (
    SELECT
        title_id,
        letterboxd_rating,
        lb_watches,
        lb_lists,
        lb_likes,
        lb_top_rank,
        lb_rating_count,
        lb_rating_weighted_sum / NULLIF(lb_rating_count, 0) AS lb_implied_rating
    FROM letterboxd_base
),
imdb_dist_agg AS (
    -- Worldwide IMDb ratings histogram (title_imdb_rating_dist). total_votes
    -- checksums against imdb_rating_count (title_scores.sample_size); the
    -- implied rating is the vote-weighted mean on IMDb's native 1-10 scale.
    SELECT
        title_id,
        total_votes AS imdb_dist_total_votes,
        ( 1 * votes_1 + 2 * votes_2 + 3 * votes_3 + 4 * votes_4 + 5 * votes_5
        + 6 * votes_6 + 7 * votes_7 + 8 * votes_8 + 9 * votes_9 + 10 * votes_10 )
        * 1.0 / NULLIF(total_votes, 0) AS imdb_hist_implied_rating
    FROM title_imdb_rating_dist
)
SELECT
    t.*,
    g.genres,
    k.keywords,
    k.imdb_keywords,
    c.companies,
    cr.directors,
    cr.writers,
    cr.creators,
    cr.cast_members,
    p.tagline,
    p.imdb_outline,
    p.imdb_summary,
    p.imdb_synopsis,
    p.wikipedia_plot,
    p.imdb_error,
    p.imdb_fetched_at,
    lb.letterboxd_rating,
    lb.lb_rating_count,
    lb.lb_implied_rating,
    lb.lb_watches,
    lb.lb_lists,
    lb.lb_likes,
    lb.lb_top_rank,
    s.tmdb_rating,
    s.tmdb_rating_count,    
    s.imdb_rating,
    s.imdb_rating_count,
    id.imdb_dist_total_votes,
    id.imdb_hist_implied_rating,
    s.rt_critic,
    s.rt_audience
FROM titles t
LEFT JOIN genres_agg     g  ON g.title_id  = t.title_id
LEFT JOIN keywords_agg   k  ON k.title_id  = t.title_id
LEFT JOIN companies_agg  c  ON c.title_id  = t.title_id
LEFT JOIN credits_agg    cr ON cr.title_id = t.title_id
LEFT JOIN title_plots    p  ON p.title_id  = t.title_id
LEFT JOIN letterboxd_agg lb ON lb.title_id = t.title_id
LEFT JOIN scores_agg     s  ON s.title_id  = t.title_id
LEFT JOIN imdb_dist_agg  id ON id.title_id = t.title_id;

DETACH DATABASE flatdb;
