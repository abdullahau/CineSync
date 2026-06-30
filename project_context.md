# CineSync — Project Context & Handoff

> This document is a self-contained briefing for continuing the CineSync project in a fresh conversation. It captures the objective, every significant design decision made so far, the current state of the code, and what comes next. Read it top to bottom before resuming work.

---

## 1. Objective

Build a **local, notebook/script-based recommendation system** that learns the movie/TV taste of one or more people from their Letterboxd ratings, then helps them discover what to watch next. It doubles as a **hands-on learning vehicle** for data science and ML/deep-learning fundamentals — so each phase should teach a specific concept rather than being a black box.

### What the system needs to do
1. **Capture rich metadata** per title — language, genre, director, writer, cast, production company, year, theme/style (keywords), plot, awards, and critic/audience scores — not just a title and a rating.
2. **Visualize taste** — clusters/patterns in what each person enjoys individually, and where tastes overlap or diverge.
3. **Generate recommendations across modes** that mix and filter together:
   - *Personalized fit* — patterns in what each person rated highly.
   - *Mood-based* — free-text query ("something surreal and slow") matched semantically against unwatched titles.
   - *Buzz/trending* — blended from TMDB popularity trend + Reddit discussion velocity + (live-fetched) TMDB trending & Letterboxd popular lists.
   - *Left-field/novelty* — deliberately unlike usual patterns, via a toggleable `novelty` dial (taste-adjacent stretch → totally outside the lane).
   - *Recency* — a cross-cutting modifier (not its own mode) controlling how much recent watches weight the taste profile, via adjustable exponential half-life decay.
4. **Score "who'll like it more"** — direct comparison of predicted enjoyment between people.
5. **Filter/sort by weighted critic score** — Letterboxd + RT-critic weighted higher than RT-audience/IMDb/TMDB.
6. **Learn from feedback** — log watched / partially watched / rejected (with reason or "wrong vibe"), retrain periodically so it improves over time.

### Target `recommend()` shape (the eventual Phase 9 interface)
```python
recommend(mood="surreal political", novelty=0.7, min_critic_score=60,
          sort_by="novelty_score", buzz_window="weekly",
          recency_half_life="2w")
```

### Hard constraints / cross-cutting design values
- Works for **1 person, a couple, or a larger group** — never hardcoded to two people. Achieved via long-format tables that loop over a `people` list.
- Covers **both movies and TV** — TV stored at **series level only** (no per-episode rows). `content_type` is just another column, not a separate pipeline.
- **World cinema** properly represented (Japanese, Hindi, Korean, French, etc.) via **per-language** `/discover` sweeps, so global popularity sort doesn't bury non-English titles.
- **Fully local** — own machine, SQLite for relational data, pandas for analysis, no cloud dependency.
- **Orchestration lives in notebooks** (visible loops), `src/` holds small single-purpose functions. This is an explicit architectural principle — see §6.
- **Installable package layout** (`src/cinesync/`) is non-negotiable, so notebooks use clean `from cinesync.X import Y` imports with no `sys.path` hacks.

---

## 2. Tech stack

- **Python ≥3.11**, **uv** for dependency management and the virtual environment.
- **SQLite** (relational source of truth) + **pandas** (analysis). Decision: SQLite stays the source of truth because the schema is genuinely relational (FKs, junction tables, the feedback→recommendation link). Parquet is reserved for later derived numeric matrices (e.g. the embeddings matrix in Phase 2). pandas over polars to minimize unfamiliar-library friction while also learning UMAP/LightGBM/PyTorch.
- **Planned ML libs:** sentence-transformers (`all-MiniLM-L6-v2`, pinned), scikit-learn, umap-learn, hdbscan, lightgbm, torch, plotly.
- **APIs/sources:** TMDB (metadata, discover, recommendations, daily exports), OMDb (IMDb rating + RT critic + awards text), Wikidata/Wikipedia (detailed plot + structured awards), Reddit via PRAW (buzz). RT-audience & Letterboxd require scraping (flagged fragile).

---

## 3. Phase roadmap

| Phase | Notebook (planned) | Teaches | Status |
|---|---|---|---|
| 0 | — | setup, schema | **DONE** |
| 1 | `01_collect` | data wrangling, APIs | metadata parser + writers **DONE**; Letterboxd import + OMDb/Wikidata enrichment **TODO** |
| 1b | `01b_candidate_discovery` | candidate generation | fetch primitives **DONE**; notebook loop **TODO** |
| 2 | `02_features` | encoding, embeddings | TODO |
| 3 | `03_clusters` | dimensionality reduction, clustering (UMAP + HDBSCAN, faceted per person) | TODO |
| 4 | `04_preference_models` | gradient boosting (one LightGBM model per person), train/test, feature importance | TODO |
| 4.5 | (in 04) | holdout evaluation (split by **title**, not row, to avoid rewatch leakage) | TODO |
| 5 | `05_two_tower` | embeddings, PyTorch (movie tower + N-person embedding table) | TODO |
| 6 | `06_mood_recommender` | semantic search / nearest-neighbor | TODO |
| 7 | `07_buzz_score` | combining heterogeneous signals, z-scores | TODO |
| 8 | `08_novelty_critic` | weighted scoring, distance metrics | `critic_score()` **DONE**; novelty dial **TODO** |
| 9 | `09_unified_scoring` | the `recommend()` interface, `disagreement_score` | TODO |
| 10 | `10_feedback_loop` | iterative improvement, implicit vs explicit signal | TODO |

---

## 4. Database schema (current — 14 tables, 2 views, 1 index)

Lives at `src/cinesync/schema.sql`. Created via `uv run cinesync-init-db`.

### Core
- **`people`** `(person_id PK, name)` — one row per person; everything loops over this.
- **`titles`** `(title_id PK = 'movie_<tmdb_id>'|'tv_<tmdb_id>', tmdb_id, content_type, name, original_language, release_year, runtime_minutes, number_of_seasons, status, imdb_id, wikidata_id, overview, detailed_plot, omdb_awards_text, source, date_added, last_refreshed)`.
  - `source` carries **specific provenance** (e.g. `discover_lang_ja`, `recommendations_via_movie_1083381`, `letterboxd_import`), not a generic bucket.
  - `date_added` immutable; `last_refreshed` mutable (bumped on every re-fetch).

### Metadata junction tables (multi-valued per title)
- **`title_genres`** `(title_id, genre)`.
- **`title_credits`** `(title_id, role, name, "order")` — `role ∈ {director, writer, creator, cast}`. `"order"` is cast billing order. **Match on `job`, never `known_for_department`** when parsing crew.
- **`title_keywords`** `(title_id, keyword)` — TMDB keyword tags, the most direct "theme/style/topic" signal.
- **`title_companies`** `(title_id, company_id, company_name)` — **PK on `company_id`** (not name) so distinct companies sharing a name aren't merged during Phase-2 frequency bucketing.
- **`title_crew_extra`** `(title_id, job, name, department)` — producer-tier credits + Director of Photography. `job` stored **verbatim** (seniority tiers preserved) rather than collapsed to a fixed role.

### Ratings / watch history
- **`watch_events`** `(watch_event_id PK, person_id, title_id, watched_date, is_rewatch, rating_at_watch)` — the **single ingestion target** for both Letterboxd `diary.csv` (multi-row, rewatch flag, per-watch rating) and bare `ratings.csv` (one row, `is_rewatch` NULL = unknown).
  - **UNIQUE INDEX `idx_watch_events_unique (person_id, title_id, watched_date)`** makes re-imports idempotent via `INSERT OR IGNORE`.
- **`current_ratings`** (VIEW) — derives the latest rating + last-watched date per (person, title) from `watch_events`. No duplicated stored data → can't drift.

### Scores & signals
- **`external_scores`** `(title_id, source, score 0-100, sample_size, date_pulled)` — `source ∈ {letterboxd_rating, rt_critic, rt_audience, imdb_rating, tmdb_rating}`. Overwrite-on-refresh (only current value matters). `sample_size` nullable (vote count where the source provides it). **Missing source = no row**; the blend rescales remaining weights, never backfills.
- **`title_buzz_snapshots`** `(title_id, source, snapshot_date, value)` — **time series** (not overwrite). `source ∈ {tmdb_popularity, reddit_mentions}`. These need a baseline to detect a spike; TMDB popularity comes free from the daily export.
- **`title_awards`** `(title_id, award_name, result, year, source)` — `result ∈ {won, nominated}`, from Wikidata P166/P1411. Low-confidence supplementary signal (uneven coverage for niche titles). Coarser free-text awards live on `titles.omdb_awards_text`.

### Recommendation discovery & output
- **`unwatched_titles`** (VIEW) — `titles` minus anything in `watch_events`. This **replaced the old `candidate_pool` table** (which had a real bug: watched titles sat in it as "eligible" because nothing checked `watch_events`). Eligibility is now derived, always correct.
- **`title_recommendation_links`** `(seed_title_id, recommended_title_id, rank, date_pulled)` — stores TMDB `/recommendations` output as durable data; also serves as the dedup check for the recommendations sweep (seed already processed = a row exists).
- **`recommendations`** `(recommendation_id PK, title_id, generated_at, mode, mood_query, novelty_dial, recency_half_life_days, buzz_window, min_critic_score, aggregation_mode, score_breakdown_json)` — one row per rec shown. `recency_half_life_days` stored **resolved/numeric**. `sort_by` deliberately NOT stored (display-only, doesn't affect scores).
- **`feedback`** `(feedback_id PK, recommendation_id FK, person_id, action, rating, reject_reason, date_logged)` — `action ∈ {watched_full, watched_partial, rejected_pre_watch}`. Linked to `recommendations` so Phase 10 can trace which mood/novelty context produced an outcome.

---

## 5. Code modules (all under `src/cinesync/`)

- **`paths.py`** — `PROJECT_ROOT`, `DATA_DIR`, `NOTEBOOKS_DIR`. Central path source.
- **`config_loader.py`** — `load_config()` reads `config.yaml` and substitutes `${ENV_VAR}` placeholders (whole-value or embedded), raising clearly if a var is unset.
- **`init_db.py`** — `init_db()`, exposed as console script `cinesync-init-db`. Won't overwrite an existing DB.
- **`tmdb_parser.py`** — `parse_tmdb_response(data, content_type, source)` → dict of rows for every table. Handles all movie/TV shape differences (keywords key `keywords` vs `results`; TV runtime fallback to `last_episode_to_air`; `created_by` for TV creators; crew dedup; TMDB score 0-10→0-100). Call TMDB with `?append_to_response=keywords,credits,external_ids` for both types.
- **`db_writer.py`** — `upsert_parsed_title()` (insert-or-refresh, returns is_new), `record_recommendation_link()`, `seed_already_processed()`.
- **`discover.py`** — `build_discover_params()` (uses `with_original_language`, NOT `language`; no `vote_average` floor) + `paced_get()` (self-throttle, 429 backoff via `Retry-After`).
- **`sync_pipeline.py`** — small fetch primitives meant to be driven by a **visible notebook loop**: `known_tmdb_ids`, `fetch_title_details`, `fetch_discover_page`, `fetch_recommendations_page`, `process_one_candidate`, `get_highly_rated_seed_titles`. (The old opaque `sync_*_sweep` orchestrators were removed.)
- **`tmdb_export_ingest.py`** — daily ID export → `title_buzz_snapshots` (tmdb_popularity). Watermark-resumable (`MAX(snapshot_date)`), `export_start ∈ {"watermark","full"}`, 90-day retention clamp, streams the gzip line-by-line.
- **`recency.py`** — `recency_weight(watched_date, half_life_days)` = `0.5 ** (days_since / half_life)` + presets (`2d`…`lifetime`).
- **`critic_score.py`** — `critic_score(scores, weights)` weighted blend; missing sources excluded and remaining weights rescaled to sum to 1; returns None if nothing available.

---

## 6. Key decisions & rationale (the "why", so they aren't relitigated)

**Architecture**
- **Long-format tables** (`watch_events`, etc.) over wide/per-person columns → adding a person is a new row, never a schema change.
- **Notebooks own orchestration; `src/` holds single-purpose functions.** Big "sweep" functions that hid pagination + fetch + parse + upsert were explicitly removed for being unreadable/undebuggable from a notebook.
- **Installable package** (`src/cinesync/`, hatchling, `force-include` for `schema.sql`) for clean imports. (Editable install resolves paths correctly; a non-editable wheel install would mis-resolve `PROJECT_ROOT` — acceptable, project is never distributed.)
- **Derived facts are VIEWs, not tables** (`current_ratings`, `unwatched_titles`) → cannot drift out of sync.

**Data sourcing**
- TMDB `/discover` (per language) is the candidate universe; daily exports are only for popularity history (they lack runtime/votes/etc. for filtering).
- TMDB `/recommendations` (real collaborative filtering) is worth ingesting; TMDB `/similar` is NOT (just genre+keyword overlap, redundant with our own embeddings); TMDB `/reviews` is NOT (sparse, especially for niche titles).
- `tmdb_rating` IS part of the critic blend — confirmed via TMDB staff it's genuine independent TMDB-user ratings, never imported from IMDb/RT.
- `with_original_language` (content filter) vs `language` (translation only) — a real, easy-to-miss bug.
- No `vote_average` floor on discovery — low average can mean "niche/polarizing," which this project wants. Quality filtering belongs in `recommend()`'s `min_critic_score`.

**Signals**
- **Three-tier signal model:** `vote_average` = cumulative *sentiment* (overwrite); `popularity`/Reddit mentions = *attention*, needs a time-series baseline to detect spikes (`title_buzz_snapshots`); `/trending` & Letterboxd popular = already short-window/curated, fetched live, not stored.
- **Recency** = exponential half-life decay (adjustable), not a hard cutoff (avoids sparse-data cliff). Composes with rewatch-as-evidence in Phase 4's LightGBM `sample_weight`.
- **Rewatch** is a real behavioral signal; kept as multiple `watch_events` rows feeding a derived count/weight, rather than complicating `current_ratings`.
- **Critic blend** rescales weights for missing sources (never zero-fills or averages-backfills).

**Scope guards**
- TV at series level only.
- Awards: store, but treat as low-confidence (coverage uneven for the niche titles we care most about).
- Reddit buzz: search **per known title** (not mention-extraction); use cross-sectional z-score immediately, longitudinal once history accumulates. (X/Instagram dropped — no practical API.)

---

## 7. Current state & immediate next steps

**Done & tested:** Phase 0 (schema, config, package layout, `cinesync-init-db`); the TMDB metadata parser; DB writers; discover/recommendations fetch primitives; daily-export popularity ingestion; recency & critic-score utilities. Full `uv sync` works (note: `numba>=0.59` pinned to fix a Python-3.12 resolver conflict).

**Not yet built:**
1. **Letterboxd import** — `ratings.csv`/`diary.csv` → `watch_events` (+ TMDB `/search` resolution with a manual-review fallback for unmatched titles — "accept the gap").
2. **OMDb + Wikidata enrichment** — populate `external_scores` (imdb/rt), `omdb_awards_text`, `title_awards`, `detailed_plot`.
3. **The Phase 1 / 1b notebooks** themselves (the visible orchestration loops).
4. Everything Phase 2 onward.

**Suggested next action:** build the Phase 1 Letterboxd import (the watched list is the foundation everything else keys off), then the 1b candidate-discovery notebook that drives the existing fetch primitives.

**Housekeeping:** the old flat `src/*.py` files and the root-level `schema.sql` should be deleted if any linger — canonical code now lives only under `src/cinesync/`.

---

## 8. People in this project
- `person_1` = Abdullah, `person_2` = Rehab. Taste leans toward world cinema (Japanese, Hindi, Korean, French, etc.), period pieces, mind-bending mystery/horror, and creative niche/boundary-pushing films with social/political themes in surreal styles.