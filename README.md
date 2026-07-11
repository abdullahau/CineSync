# CineSync

Local, notebook-based movie/TV recommendation system for an individual,
couple, or small group. Built from Letterboxd ratings, TMDB
metadata, and your own feedback over time.

## Phase 0 -- what's in this folder

- `config.yaml` -- people in your group, pinned embedding model
  version, languages of interest, API keys, thresholds, critic score
  weights. Every notebook reads from here instead of hardcoding values.
- `schema.sql` -- the full SQLite schema (see comments in the file
  for the reasoning behind each table).
- `src/init_db.py` -- run this once to create `data/cinesync.db`.
- `src/config_loader.py` -- shared helper every future notebook will
  import.
- `pyproject.toml` -- everything needed across all phases. uv reads
this and manages the virtual environment for you.

## Setup

```bash
cd cinesync
uv sync
uv run python src/init_db.py
```

Then open `config.yaml` and:
1. Confirm/edit the `people` list.
2. Add your TMDB (free).
3. Add Reddit API credentials if you want the buzz score later
   (Phase 7) -- not needed yet.

## Why the schema looks the way it does

- **Long-format `ratings`** (`person_id`, `title_id`, `rating`) instead
  of one column per person -- adding a 3rd or 4th person later is a
  new row, not a new column.
- **`content_type`** on `titles` distinguishes movie vs. TV without
  needing two separate pipelines -- TV is stored at series level only,
  no episode rows.
- **`title_genres` / `title_credits`** are junction tables because
  genres and cast/director/writer are multi-valued per title.
- **`title_scores`** keeps each rating source (Letterboxd, RT
  critic, RT audience, IMDb) separate so the weighted blend in
  `config.yaml` can change later without re-scraping anything.
- **`recommendations` + `feedback`** are linked by
  `recommendation_id` -- this is what lets Phase 10 trace a rejection
  or rating back to the exact mood query / novelty setting that
  produced it.

## Phase roadmap

| Phase | Notebook | What it does |
|---|---|---|
| 1 | `01_collect.ipynb` | Import Letterboxd ratings, enrich via TMDB |
| 1b | `01b_candidate_pool.ipynb` | Per-language TMDB discover pulls -> candidate universe |
| 2 | `02_features.ipynb` | Encode genre/cast/credits, sentence-transformer embeddings |
| 3 | `03_clusters.ipynb` | UMAP + HDBSCAN taste maps, per person |
| 4 | `04_preference_models.ipynb` | LightGBM model per person |
| 4.5 | (part of 04) | Holdout evaluation |
| 5 | `05_two_tower.ipynb` | PyTorch two-tower model |
| 6 | `06_mood_recommender.ipynb` | Semantic mood search |
| 7 | `07_buzz_score.ipynb` | TMDB trending + Reddit + Letterboxd popular |
| 8 | `08_novelty_critic.ipynb` | Novelty dial + weighted critic score |
| 9 | `09_unified_scoring.ipynb` | The `recommend()` function |
| 10 | `10_feedback_loop.ipynb` | Periodic retraining from logged feedback |

Notebooks get added to `notebooks/` as we build each phase.