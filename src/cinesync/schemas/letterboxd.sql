CREATE TABLE letterboxd_movie_stats (
    title_id TEXT PRIMARY KEY,
    tmdb_id INTEGER NOT NULL UNIQUE,
    name TEXT NOT NULL,

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

    -- NULL if not in the Top 250/500 list
    top_rank INTEGER CHECK (
        top_rank IS NULL OR
        (top_rank BETWEEN 1 AND 500)
    )
);