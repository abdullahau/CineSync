-- ============================================================
-- CineSync database schema (SQLite)
-- Phase 0: schema lock-in
--
-- Run `uv run cinesync-init-db` to create `data/cinesync.db`
-- ============================================================

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
    runtime_minutes    INTEGER,             -- movies: runtime; tv: avg episode runtime
    number_of_seasons  INTEGER,             -- null for movies
    status             TEXT,                -- 'Released', 'Ended', 'Returning Series', etc.
    imdb_id            TEXT,                -- needed for OMDb critic scores
    wikidata_id        TEXT,                -- needed for the Wikipedia plot
    overview           TEXT,                -- TMDB's short synopsis
    detailed_plot      TEXT,                -- longer Wikipedia "Plot" section, when available
    omdb_awards_text   TEXT,                -- raw, unparsed OMDb "Awards" string
    source             TEXT,                -- 'letterboxd_import' or 'tmdb_discover'
    date_added         TEXT DEFAULT (datetime('now')), -- immutable
    last_refreshed     TEXT DEFAULT (datetime('now')) -- mutable -- when metadata was last verified/re-fetched.
);

-- Genres (titles 1:M title_genres)
CREATE TABLE title_genres (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    genre    TEXT NOT NULL,
    PRIMARY KEY (title_id, genre)
);

-- Cast, director, writer, and (for TV) creator (title 1:M title_credits)
CREATE TABLE title_credits (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    role     TEXT NOT NULL CHECK (role IN ('director','writer','creator','cast')),
    name     TEXT NOT NULL,
    "order"  INTEGER,       -- "order" is cast billing order from TMDB
    PRIMARY KEY (title_id, role, name)
);

-- TMDB keyword tags (title 1:M title_keywords)
CREATE TABLE title_keywords (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    keyword  TEXT NOT NULL,
    PRIMARY KEY (title_id, keyword)
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

-- "Current rating" and "last watched" as derived values
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

-- Critic & audience scores/ratings
CREATE TABLE external_scores (
    title_id    TEXT NOT NULL REFERENCES titles(title_id),
    source      TEXT NOT NULL CHECK (source IN
                 ('letterboxd_rating','rt_critic','rt_audience','imdb_rating','tmdb_rating')),
    score       REAL,             -- normalized to a 0-100 scale at write time
    sample_size INTEGER,          -- nullable
    date_pulled TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (title_id, source)
);

-- Popularity & mention time series
CREATE TABLE title_buzz_snapshots (
    title_id      TEXT NOT NULL REFERENCES titles(title_id),
    source        TEXT NOT NULL CHECK (source IN ('tmdb_popularity','reddit_mentions')),
    snapshot_date TEXT NOT NULL,
    value         REAL NOT NULL,        -- TMDB popularity or reddit mentions
    PRIMARY KEY (title_id, source, snapshot_date)
);

-- Awards received (P166) and nominations (P1411)
CREATE TABLE title_awards (
    title_id   TEXT NOT NULL REFERENCES titles(title_id),
    award_name TEXT NOT NULL,        -- e.g. 'Cannes Film Festival: Palme d'Or'
    result     TEXT NOT NULL CHECK (result IN ('won','nominated')),
    year       INTEGER,
    source     TEXT DEFAULT 'wikidata',
    PRIMARY KEY (title_id, award_name, result, year)
);

-- Eligible titles for recommendations
CREATE TABLE candidate_pool (
    title_id    TEXT NOT NULL REFERENCES titles(title_id),
    pulled_via  TEXT,        -- 'discover_lang_ja', 'discover_lang_hi', 'general', etc.
    date_pulled TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (title_id, pulled_via)
);

-- Recommendation shown to user groups
CREATE TABLE recommendations (
    recommendation_id       TEXT PRIMARY KEY,    -- uuid, generated at recommend() call time
    title_id                TEXT NOT NULL REFERENCES titles(title_id),
    generated_at            TEXT DEFAULT (datetime('now')),
    mode                    TEXT,               -- 'personal_fit','mood','buzz','novelty','blended'
    mood_query              TEXT,
    novelty_dial            REAL,
    recency_half_life_days  REAL,            -- numeric value to track recency dial
    buzz_window             TEXT,            -- 'daily' / 'weekly' -- a real scoring input, same
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