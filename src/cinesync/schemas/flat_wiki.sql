-- Wikidata + Wikipedia (MediaWiki) service snapshot: TMDB title spine LEFT JOIN
-- Wikidata meta, awards rollup, and Wikipedia plot. Rotten Tomatoes lives in its
-- own flat_rt.sql (the RT slug is *resolved* here via the Wikidata pass, but its
-- ratings and fetch timing are a separate concern).
-- Standalone DB so it opens on its own in a single-file SQLite viewer.
-- Rebuilt per session; never migrated. Run via pipelines/build_flats.py.
ATTACH DATABASE 'data/cinesync_flat_wiki.db' AS flatdb;

DROP TABLE IF EXISTS flatdb.wiki_flat;

CREATE TABLE flatdb.wiki_flat AS
WITH awards_agg AS (
    SELECT
        title_id,
        SUM(result = 'won')                                AS awards_won,
        SUM(result = 'nominated')                          AS awards_nominated,
        SUM(result = 'won' AND level = 'title')            AS title_awards_won,
        SUM(result = 'won' AND level = 'person')           AS person_awards_won,
        GROUP_CONCAT(DISTINCT prestige)                    AS prestige_families,
        SUM(result = 'won' AND prestige = 'Oscars')        AS oscars_won,
        SUM(result = 'nominated' AND prestige = 'Oscars')  AS oscars_nominated
    FROM title_awards
    GROUP BY title_id
)
SELECT
    t.title_id,
    t.tmdb_id,
    t.content_type,
    t.name,
    t.release_year,
    t.wikidata_id,
    t.imdb_id,
    (t.wikidata_id IS NOT NULL)                 AS has_wikidata_id,

    -- Wikidata single-valued outputs + fetch state
    wm.wikipedia_url,
    wm.wikidata_fetched_at,
    wm.wikidata_error,
    (wm.title_id IS NOT NULL)                   AS wikidata_meta_present,

    -- Wikipedia plot (full text + length) + fetch state
    p.wikipedia_plot,
    LENGTH(p.wikipedia_plot)                    AS wikipedia_plot_len,
    p.wikipedia_fetched_at,
    p.wikipedia_error,
    (p.wikipedia_fetched_at IS NOT NULL)        AS wikipedia_fetched,

    -- awards rollup (derived here, not stored)
    COALESCE(a.awards_won, 0)                   AS awards_won,
    COALESCE(a.awards_nominated, 0)             AS awards_nominated,
    COALESCE(a.title_awards_won, 0)             AS title_awards_won,
    COALESCE(a.person_awards_won, 0)            AS person_awards_won,
    a.prestige_families,
    COALESCE(a.oscars_won, 0)                   AS oscars_won,
    COALESCE(a.oscars_nominated, 0)             AS oscars_nominated
FROM titles t
LEFT JOIN title_wikidata_meta wm ON wm.title_id = t.title_id
LEFT JOIN title_plots         p  ON p.title_id  = t.title_id
LEFT JOIN awards_agg          a  ON a.title_id  = t.title_id;

DETACH DATABASE flatdb;
