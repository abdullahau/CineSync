-- ============================================================
-- CineSync database schema (SQLite)
-- Phase 0: schema lock-in
--
-- Run src/init_db.py to turn this file into data/cinesync.db
-- ============================================================

-- One row per person in the group. Works for 1, 2, or N people --
-- everything downstream loops over this table instead of hardcoding
-- "me" and "wife" as separate columns anywhere.
CREATE TABLE people (
    person_id   TEXT PRIMARY KEY,   -- e.g. 'person_1'
    name        TEXT NOT NULL
);

-- One row per movie or TV series. TV is stored at SERIES level only
-- -- no per-episode rows. content_type is just another column, so
-- every feature/model treats movie vs TV as one more signal, not a
-- separate pipeline.
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
    overview           TEXT,                -- synopsis -- source text for theme embeddings
    source             TEXT,                -- 'letterboxd_import' or 'tmdb_discover'
    date_added         TEXT DEFAULT (datetime('now'))
);

-- Genres are multi-valued per title, so they get their own table
-- instead of a comma-separated column. This is the standard fix for
-- "one movie, many genres" in a relational schema -- it also makes
-- one-hot encoding in Phase 2 a one-line groupby instead of string
-- parsing.
CREATE TABLE title_genres (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    genre    TEXT NOT NULL,
    PRIMARY KEY (title_id, genre)
);

-- Cast, director, writer, and (for TV) creator all live here with a
-- role label. Same multi-valued fix as genres. "order" is cast
-- billing order from TMDB, useful later for top-N frequency bucketing
-- (Phase 2) so you don't one-hot encode every extra who's ever
-- appeared in anything.
CREATE TABLE title_credits (
    title_id TEXT NOT NULL REFERENCES titles(title_id),
    role     TEXT NOT NULL CHECK (role IN ('director','writer','creator','cast')),
    name     TEXT NOT NULL,
    "order"  INTEGER,
    PRIMARY KEY (title_id, role, name)
);

-- Long format: one row per (person, title, rating) rather than one
-- column per person. This single choice is what makes adding a 3rd,
-- 4th, 5th person later just a new person_id -- not a new column and
-- not a schema migration.
CREATE TABLE ratings (
    person_id  TEXT NOT NULL REFERENCES people(person_id),
    title_id   TEXT NOT NULL REFERENCES titles(title_id),
    rating     REAL NOT NULL,        -- normalized 0-5 to match Letterboxd's scale
    source     TEXT,                 -- 'letterboxd_import'
    date_rated TEXT,
    PRIMARY KEY (person_id, title_id)
);

-- Critic/audience scores kept separate per source rather than
-- pre-blended into one number. The weighted critic_score (Phase 8)
-- is computed on read from these rows, so you can change the
-- weights in config.yaml later without re-scraping anything.
CREATE TABLE external_scores (
    title_id    TEXT NOT NULL REFERENCES titles(title_id),
    source      TEXT NOT NULL CHECK (source IN
                 ('letterboxd_rating','rt_critic','rt_audience','imdb_rating')),
    score       REAL,             -- normalized to a 0-100 scale at write time
    date_pulled TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (title_id, source)
);

-- Tracks how a title entered the candidate pool (Phase 1b) -- which
-- language query or discover call surfaced it, and when. Lets you
-- debug "why is this even a candidate" and cleanly exclude anything
-- already in `ratings`.
CREATE TABLE candidate_pool (
    title_id    TEXT NOT NULL REFERENCES titles(title_id),
    pulled_via  TEXT,        -- 'discover_lang_ja', 'discover_lang_hi', 'general', etc.
    date_pulled TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (title_id, pulled_via)
);

-- One row per recommendation actually SHOWN to the group. This is
-- the linkage Phase 10 depends on: without recommendation_id,
-- feedback can't be traced back to the mood query, novelty setting,
-- or aggregation mode that produced it.
CREATE TABLE recommendations (
    recommendation_id    TEXT PRIMARY KEY,   -- uuid, generated at recommend() call time
    title_id             TEXT NOT NULL REFERENCES titles(title_id),
    generated_at         TEXT DEFAULT (datetime('now')),
    mode                 TEXT,                -- 'personal_fit','mood','buzz','novelty','blended'
    mood_query           TEXT,
    novelty_dial         REAL,
    min_critic_score     REAL,
    aggregation_mode     TEXT,               -- 'mean','min','harmonic_mean','show_all'
    score_breakdown_json TEXT                -- raw per-person/per-signal scores, for debugging
);

-- One row per person's reaction to a shown recommendation. This is
-- what Phase 10's retraining notebook reads from. reject_reason
-- distinguishes feature-level rejections (train on them, down-
-- weighted) from vibe/mood rejections (route to the separate
-- acceptance model instead).
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