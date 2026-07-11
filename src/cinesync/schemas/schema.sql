-- People/Users
CREATE TABLE people (
    person_id   TEXT PRIMARY KEY,
    name        TEXT NOT NULL
);

-- Movie or TV series
CREATE TABLE titles (
    title_id           TEXT PRIMARY KEY,   -- 'movie_<tmdb_id>' or 'tv_<tmdb_id>'
    tmdb_id            INTEGER NOT NULL,
    content_type       TEXT NOT NULL CHECK (content_type IN ('movie','tv')),
    name               TEXT NOT NULL,
    original_language  TEXT,
    release_year       INTEGER,
    certificate        TEXT,                -- US certificate rating from TMDB (R, MA, TV-14)
    runtime_minutes    INTEGER,             -- movies: runtime; tv: avg episode runtime
    number_of_seasons  INTEGER,             -- null for movies
    status             TEXT,                -- 'Released', 'Ended', 'Returning Series', etc.
    imdb_id            TEXT,                -- needed for IMDb data enrichment & rating
    wikidata_id        TEXT,                -- needed for the Wikipedia plot
    tmdb_overview      TEXT,                -- TMDB's short synopsis
    source             TEXT,                -- title discovery source
    date_added         TEXT DEFAULT (datetime('now')), -- immutable
    last_refreshed     TEXT DEFAULT (datetime('now')) -- mutable -- when metadata was last verified/re-fetched.
);
-- IMDb's "movie" box office figures?
-- Rotten Tomato links/url slug - extracted from Wikidata?
-- Create a separate table for detailed plot from Wikipedia?

-- Long-form plot text, 1:1 with titles. Written by IMDb scraper + Wikipedia.
CREATE TABLE title_plots (
    title_id             TEXT NOT NULL PRIMARY KEY REFERENCES titles(title_id),
    imdb_outline         TEXT,   -- IMDb short one-liner
    imdb_summary         TEXT,   -- IMDb medium plot summary
    imdb_synopsis        TEXT,   -- IMDb long detailed synopsis
    wikipedia_plot       TEXT,   -- Wikipedia "Plot" section
    tagline              TEXT,
    imdb_error           TEXT,   -- NULL on success
    imdb_fetched_at      TEXT,   -- NULL until the IMDb scraper has run for this title
    wikipedia_error      TEXT,   -- NULL on success; set only on fetch failure (retryable)
    wikipedia_fetched_at TEXT    -- NULL until the Wikipedia plot fetch has run for this title
);

-- Genres (titles 1:M title_genres)
CREATE TABLE title_genres (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    genre    TEXT NOT NULL,
    PRIMARY KEY (title_id, genre)
);

-- TMDB keyword tags (title 1:M title_keywords)
CREATE TABLE title_keywords (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    keyword  TEXT NOT NULL,
    source   TEXT NOT NULL,
    PRIMARY KEY (title_id, keyword, source)
);

-- Cast, director, writer, and (for TV) creator (title 1:M title_credits)
CREATE TABLE title_credits (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    role     TEXT NOT NULL CHECK (role IN ('director','writer','creator','cast')),
    name     TEXT NOT NULL,
    "order"  INTEGER,       -- "order" is cast billing order from TMDB
    PRIMARY KEY (title_id, role, name)
);

-- Production companies (title 1:M title_companies)
CREATE TABLE title_companies (
    title_id     TEXT NOT NULL REFERENCES titles(title_id),
    company_id   INTEGER NOT NULL,
    company_name TEXT NOT NULL,
    PRIMARY KEY (title_id, company_id)
);

-- Producer-tier credits plus Director of Photography.
CREATE TABLE title_crew_extra (
    title_id   TEXT NOT NULL REFERENCES titles(title_id),
    job        TEXT NOT NULL,      -- verbatim TMDB job title, e.g. 'Executive Producer'
    name       TEXT NOT NULL,
    department TEXT,               -- TMDB department, kept for reference/debugging
    PRIMARY KEY (title_id, job, name)
);

-- Critic & audience scores/ratings from Rotten Tomatoes, IMDB, and TMDB
CREATE TABLE title_scores (
    title_id    TEXT NOT NULL REFERENCES titles(title_id),
    source      TEXT NOT NULL CHECK (source IN
                 ('rt_critic','rt_audience','imdb_rating','tmdb_rating')),
    score       REAL,             -- normalized to a 0-100 scale at write time
    sample_size INTEGER,          -- nullable
    date_pulled TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (title_id, source)
);

-- Letterboxd ratings and stats
CREATE TABLE title_letterboxd_stats (
    title_id TEXT NOT NULL PRIMARY KEY REFERENCES titles(title_id),

    -- Aggregate ratings
    rating_value REAL,
    rating_count INTEGER,
    review_count INTEGER,

    -- Rating distribution (number of ratings in each bucket)
    rating_0_5_count INTEGER NOT NULL DEFAULT 0,
    rating_1_0_count INTEGER NOT NULL DEFAULT 0,
    rating_1_5_count INTEGER NOT NULL DEFAULT 0,
    rating_2_0_count INTEGER NOT NULL DEFAULT 0,
    rating_2_5_count INTEGER NOT NULL DEFAULT 0,
    rating_3_0_count INTEGER NOT NULL DEFAULT 0,
    rating_3_5_count INTEGER NOT NULL DEFAULT 0,
    rating_4_0_count INTEGER NOT NULL DEFAULT 0,
    rating_4_5_count INTEGER NOT NULL DEFAULT 0,
    rating_5_0_count INTEGER NOT NULL DEFAULT 0,

    -- Letterboxd statistics
    watches INTEGER,
    lists INTEGER,
    likes INTEGER,

    -- NULL if not in the Top 500 (movies)/Top 250 (documentary) list
    top_rank INTEGER CHECK (
        top_rank IS NULL OR
        (top_rank BETWEEN 1 AND 500)
    )
);

-- PLACEHOLDER: populated later from the IMDb ratings HTML page.
CREATE TABLE title_imdb_rating_dist (
    title_id    TEXT NOT NULL PRIMARY KEY REFERENCES titles(title_id),
    votes_1  INTEGER, votes_2  INTEGER, votes_3  INTEGER, votes_4  INTEGER, votes_5 INTEGER,
    votes_6  INTEGER, votes_7  INTEGER, votes_8  INTEGER, votes_9  INTEGER, votes_10 INTEGER,
    total_votes INTEGER,   -- checksum against title_scores.sample_size for imdb_rating
    fetched_at  TEXT DEFAULT (datetime('now'))
);

-- Awards received (P166) and nominations (P1411), from Wikidata. One row per
-- award statement: title-level (Best Picture) and person-level (an actor's win,
-- via the P1686 "for work" qualifier) both land here, distinguished by `level`.
-- `statement_id` is Wikidata's statement GUID -- the natural dedup key, so a
-- re-fetch full-replaces this title's rows idempotently. Counts/prestige
-- rollups are derived in pandas, not stored.
CREATE TABLE title_awards (
    title_id     TEXT NOT NULL REFERENCES titles(title_id),
    statement_id TEXT NOT NULL,      -- Wikidata ?st statement URI (natural dedup key)
    award_name   TEXT NOT NULL,
    result       TEXT NOT NULL CHECK (result IN ('won','nominated')),
    prestige     TEXT,               -- 'Oscars'/'BAFTA'/... or NULL if not a tracked family
    level        TEXT NOT NULL CHECK (level IN ('title','person')),
    subject      TEXT,               -- person name for level='person'; NULL for level='title'
    year         INTEGER,
    source       TEXT DEFAULT 'wikidata',
    PRIMARY KEY (title_id, statement_id)
);

-- Single-valued outputs of the Wikidata SPARQL pass + its fetch state.
-- (Awards fan out to title_awards; the RT slug lives in title_rt.)
-- wikidata_fetched_at is the done-flag: a title that legitimately won nothing
-- has zero title_awards rows, so "no award rows" can't mean "not fetched yet".
CREATE TABLE title_wikidata_meta (
    title_id            TEXT NOT NULL PRIMARY KEY REFERENCES titles(title_id),
    wikipedia_url       TEXT,
    wikidata_fetched_at TEXT,
    wikidata_error      TEXT
);

-- Rotten Tomatoes page link + how it was resolved. Standalone because link
-- resolution is its own multi-source process: the Wikidata pass fills slugs for
-- popular titles that carry P1258, and a later search-engine fallback
-- (DuckDuckGo/Bing) resolves the rest. RT *ratings* are NOT here -- they land in
-- title_scores (rt_critic/rt_audience); this table is the slug the ratings
-- scrape consumes.
CREATE TABLE title_rt (
    title_id    TEXT NOT NULL PRIMARY KEY REFERENCES titles(title_id),
    rt_slug     TEXT,   -- 'm/titanic' / 'tv/breaking_bad'; NULL if unresolved. Build URL at read time.
    source      TEXT,   -- resolver: 'wikidata','duckduckgo','bing','manual'
    resolved_at TEXT,   -- when a slug was found; NULL while unresolved
    last_error  TEXT    -- last resolver note, e.g. 'no P1258','not_found'
);

-- Popularity & mention time series
CREATE TABLE title_popularity (
    title_id      TEXT NOT NULL REFERENCES titles(title_id),
    source        TEXT NOT NULL CHECK (source IN ('tmdb_popularity','reddit_mentions')),
    snapshot_date TEXT NOT NULL,
    value         REAL NOT NULL,        -- TMDB popularity or reddit mentions
    PRIMARY KEY (title_id, source, snapshot_date)
);

-- TMDB's /recommendations links -> relevance ordering, 1 = most relevant.
CREATE TABLE title_recommendation_links (
    seed_title_id        TEXT NOT NULL REFERENCES titles(title_id),
    recommended_title_id TEXT NOT NULL REFERENCES titles(title_id),
    rank                  INTEGER,
    date_pulled           TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (seed_title_id, recommended_title_id)
);

-- Diary / Ratings / Watchlist
CREATE TABLE watch_events (
    watch_event_id  TEXT PRIMARY KEY,    -- uuid
    person_id       TEXT NOT NULL REFERENCES people(person_id),
    title_id        TEXT NOT NULL REFERENCES titles(title_id),
    watched_date    TEXT NOT NULL,
    is_rewatch      INTEGER CHECK (is_rewatch IN (0,1)),  -- nullable
    rating_at_watch REAL
);

-- Makes re-importing a Letterboxd export idempotent
CREATE UNIQUE INDEX idx_watch_events_unique
    ON watch_events (person_id, title_id, watched_date);

-- "Current rating" and "last watched" derived from watch_events
CREATE VIEW current_ratings AS
SELECT person_id, title_id, rating_at_watch AS rating, watched_date
FROM (
    SELECT person_id, title_id, rating_at_watch, watched_date,
           ROW_NUMBER() OVER (
               PARTITION BY person_id, title_id
               ORDER BY watched_date DESC
           ) AS rn
    FROM watch_events
    WHERE rating_at_watch IS NOT NULL
)
WHERE rn = 1;

-- Recommendation eligibility derived from anti-join of titles & watch_events
CREATE VIEW unwatched_titles AS
SELECT t.*
FROM titles t
WHERE t.title_id NOT IN (SELECT DISTINCT title_id FROM watch_events);

-- Recommendation shown to user groups
CREATE TABLE recommendations (
    recommendation_id       TEXT PRIMARY KEY,   -- uuid, generated at recommend() call time
    title_id                TEXT NOT NULL REFERENCES titles(title_id),
    generated_at            TEXT DEFAULT (datetime('now')),
    mode                    TEXT,               -- 'personal_fit','mood','buzz','novelty','blended'
    mood_query              TEXT,
    novelty_dial            REAL,
    recency_half_life_days  REAL,               -- numeric value to track recency dial
    buzz_window             TEXT,               -- 'daily' / 'weekly' -- a real scoring input, same
    min_critic_score        REAL,
    aggregation_mode        TEXT,               -- 'mean','min','harmonic_mean','show_all'
    score_breakdown_json    TEXT                -- raw per-person/per-signal scores, for debugging
);

-- Person's reaction to a shown recommendation
CREATE TABLE feedback (
    feedback_id       TEXT PRIMARY KEY,    -- uuid
    recommendation_id TEXT NOT NULL REFERENCES recommendations(recommendation_id),
    person_id         TEXT NOT NULL REFERENCES people(person_id),
    action            TEXT NOT NULL CHECK (action IN
                       ('watched_full','watched_partial','rejected_pre_watch')),
    rating            REAL,                -- filled in only if watched
    reject_reason     TEXT,                -- 'genre','cast','pacing','mood_mismatch','vibe', etc.
    date_logged       TEXT DEFAULT (datetime('now'))
);