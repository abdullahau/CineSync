# CineSync — Project Context & Handoff

> Self-contained briefing for continuing CineSync in a fresh conversation. Captures the objective, every significant design decision, the current state of the code, and what comes next. Read top to bottom before resuming, and attach the actual source files alongside it so a fresh Claude reads real code rather than a summary of it.

---

## 1. Objective

Build a **local, notebook/script-based recommendation system** that learns the movie/TV taste of one or more people from their Letterboxd ratings, then helps them discover what to watch next. It doubles as a **hands-on learning vehicle** for data science and ML/deep-learning fundamentals — each phase should teach a specific concept rather than being a black box.

### What the system needs to do
1. **Capture rich metadata** per title — language, genre, director, writer, cast, production company, producer-tier crew + DP, year, theme/style (keywords), plot, awards, and critic/audience scores.
2. **Visualize taste** — clusters/patterns per person, and where tastes overlap or diverge.
3. **Generate recommendations across modes** that mix and filter together:
   - *Personalized fit* — patterns in what each person rated highly.
   - *Mood-based* — free-text query ("something surreal and slow") matched semantically against unwatched titles.
   - *Buzz/trending* — blended from TMDB popularity trend + Reddit discussion velocity + (live-fetched) TMDB trending & Letterboxd popular lists.
   - *Left-field/novelty* — deliberately unlike usual patterns, via a toggleable `novelty` dial.
   - *Recency* — a cross-cutting modifier (not its own mode) controlling how much recent watches weight the taste profile, via adjustable exponential half-life decay.
4. **Score "who'll like it more"** — direct comparison of predicted enjoyment between people.
5. **Filter/sort by weighted critic score** — Letterboxd + RT-critic weighted higher than RT-audience/IMDb/TMDB.
6. **Learn from feedback** — log watched / partially watched / rejected (with reason or "wrong vibe"), retrain periodically.

### Target `recommend()` shape (eventual Phase 9 interface)
```python
recommend(mood="surreal political", novelty=0.7, min_critic_score=60,
          sort_by="novelty_score", buzz_window="weekly",
          recency_half_life="2w")
```

### Hard constraints / cross-cutting values
- Works for **1 person, a couple, or a group** — never hardcoded to two people (long-format tables looping over a `people` list).
- Covers **both movies and TV** — TV at **series level only** (no per-episode rows). `content_type` is just another column, not a separate pipeline.
- **World cinema** properly represented via **per-language** `/discover` sweeps (see `languages_of_interest` in config — 15 languages: en, ko, ja, hi, ur, fr, it, es, fa, de, sv, no, id, ms, bn).
- **Fully local** — SQLite (relational source of truth) + pandas (analysis), no cloud dependency.
- **Orchestration lives in notebooks** (visible, inspectable loops); `src/cinesync/` holds small single-purpose functions. Explicit principle — big opaque "sweep" orchestrators were deliberately removed.
- **Installable package layout** (`src/cinesync/`, hatchling) so notebooks use clean `from cinesync.X import Y` with no `sys.path` hacks.

---

## 2. Tech stack

- **Python ≥3.11**, **uv** for deps + venv. Package installs editable via `uv sync`.
- **SQLite** + **pandas**. SQLite is the source of truth (schema is genuinely relational: FKs, junction tables, feedback→recommendation link). Parquet reserved for later derived numeric matrices (Phase 2 embeddings). pandas over polars to minimize unfamiliar-library friction while also learning UMAP/LightGBM/PyTorch.
- **Planned ML libs:** sentence-transformers (`all-MiniLM-L6-v2`, pinned), scikit-learn, umap-learn, hdbscan, lightgbm, torch, plotly.
- **`numba>=0.59` pinned** in pyproject to resolve a Python-3.12 resolver conflict pulled in transitively via umap-learn — without it, `uv sync` fails.
- **APIs/sources:** TMDB (metadata, discover, recommendations, daily exports), OMDb (IMDb rating + RT critic + awards text), Wikidata/Wikipedia (detailed plot + structured awards), Reddit via PRAW (buzz). RT-audience & Letterboxd require scraping (flagged fragile).

---

## 3. Phase roadmap

| Phase | Notebook (planned) | Teaches | Status |
|---|---|---|---|
| 0 | — | setup, schema, package | **DONE** |
| 1 | `01_collect` | data wrangling, APIs | metadata parser + writers **DONE**; Letterboxd import + OMDb/Wikidata enrichment **TODO** |
| 1b | `01b_candidate_discovery` | candidate generation, threading, pagination | fetch primitives + date-windowing **DONE**; notebook loop **IN PROGRESS** (working, being instrumented) |
| 2 | `02_features` | encoding, embeddings | TODO |
| 3 | `03_clusters` | dimensionality reduction, clustering (UMAP + HDBSCAN, faceted per person) | TODO |
| 4 | `04_preference_models` | gradient boosting (one LightGBM per person), train/test, feature importance | TODO |
| 4.5 | (in 04) | holdout eval (split by **title**, not row, to avoid rewatch leakage) | TODO |
| 5 | `05_two_tower` | embeddings, PyTorch (movie tower + N-person embedding table) | TODO |
| 6 | `06_mood_recommender` | semantic search / nearest-neighbor | TODO |
| 7 | `07_buzz_score` | combining heterogeneous signals, z-scores | TODO |
| 8 | `08_novelty_critic` | weighted scoring, distance metrics | `critic_score()` **DONE**; novelty dial **TODO** |
| 9 | `09_unified_scoring` | the `recommend()` interface, `disagreement_score` | TODO |
| 10 | `10_feedback_loop` | iterative improvement, implicit vs explicit signal | TODO |

---

## 4. Database schema (current — 15 tables, 2 views, 1 unique index)

Lives at `src/cinesync/schema.sql`. Created via `uv run cinesync-init-db`.

### Core
- **`people`** `(person_id PK, name)`.
- **`titles`** `(title_id PK = 'movie_<tmdb_id>'|'tv_<tmdb_id>', tmdb_id, content_type, name, original_language, release_year, runtime_minutes, number_of_seasons, status, imdb_id, wikidata_id, overview, detailed_plot, omdb_awards_text, source, date_added, last_refreshed)`.
  - `source` carries **specific provenance** (e.g. `discover_lang_ja`, `recommendations_via_movie_1083381`, `letterboxd_import`).
  - `date_added` immutable; `last_refreshed` mutable (bumped on every re-fetch).

### Metadata junction tables
- **`title_genres`** `(title_id, genre)`.
- **`title_credits`** `(title_id, role, name, "order")` — `role ∈ {director, writer, creator, cast}`. **Match on `job`, never `known_for_department`.**
- **`title_keywords`** `(title_id, keyword)` — the most direct theme/style signal. **Written via DELETE-then-reINSERT (full replace)**, unlike the other junction tables, so keywords removed on TMDB's side actually disappear (they drive theme/mood matching; staleness matters most here).
- **`title_companies`** `(title_id, company_id, company_name)` — **PK on `company_id`** so distinct companies sharing a name aren't merged.
- **`title_crew_extra`** `(title_id, job, name, department)` — producer-tier credits + DP; `job` stored **verbatim** (seniority preserved).

### Ratings / watch history
- **`watch_events`** `(watch_event_id PK, person_id, title_id, watched_date, is_rewatch, rating_at_watch)` — single ingestion target for both `diary.csv` and bare `ratings.csv` (`is_rewatch` NULL = unknown).
  - **UNIQUE INDEX `idx_watch_events_unique (person_id, title_id, watched_date)`** → idempotent re-imports via `INSERT OR IGNORE`.
- **`current_ratings`** (VIEW) — latest rating + last-watched date per (person, title). Derived, can't drift.

### Scores & signals
- **`external_scores`** `(title_id, source, score 0-100, sample_size, date_pulled)` — `source ∈ {letterboxd_rating, rt_critic, rt_audience, imdb_rating, tmdb_rating}`. Overwrite-on-refresh. Missing source = no row; the blend rescales remaining weights, never backfills.
- **`title_buzz_snapshots`** `(title_id, source, snapshot_date, value)` — **time series**. `source ∈ {tmdb_popularity, reddit_mentions}`. Needs a baseline to detect a spike.
- **`title_awards`** `(title_id, award_name, result, year, source)` — `result ∈ {won, nominated}`, from Wikidata P166/P1411. Low-confidence supplementary signal.

### Recommendation discovery & output
- **`unwatched_titles`** (VIEW) — `titles` minus anything in `watch_events`. **Replaced the old `candidate_pool` table** (which had a real bug: watched titles sat in it as "eligible"). Eligibility is now derived, always correct.
- **`title_recommendation_links`** `(seed_title_id, recommended_title_id, rank, date_pulled)` — TMDB `/recommendations` output as durable data; also the dedup check for the recommendations sweep.
- **`recommendations`** `(recommendation_id PK, title_id, generated_at, mode, mood_query, novelty_dial, recency_half_life_days, buzz_window, min_critic_score, aggregation_mode, score_breakdown_json)`. `recency_half_life_days` stored **resolved/numeric**. `sort_by` deliberately NOT stored (display-only).
- **`feedback`** `(feedback_id PK, recommendation_id FK, person_id, action, rating, reject_reason, date_logged)` — `action ∈ {watched_full, watched_partial, rejected_pre_watch}`. Linked to `recommendations` so Phase 10 can trace which mood/novelty context produced an outcome.

---

## 5. Code modules (all under `src/cinesync/`)

- **`paths.py`** — `PROJECT_ROOT`, `DATA_DIR`, `NOTEBOOKS_DIR`.
- **`config_loader.py`** — `load_config()`; substitutes `${ENV_VAR}` placeholders (whole-value or embedded), raises clearly if unset.
- **`init_db.py`** — `init_db()`, exposed as console script `cinesync-init-db`; loads `schema.sql` via `importlib.resources`. Won't overwrite an existing DB.
- **`tmdb_parser.py`** — `parse_tmdb_response(data, content_type, source)` → dict of rows for every table (`title`, `genres`, `keywords`, `companies`, `credits`, `crew_extra`, `external_score`). Handles all movie/TV shape differences (keywords key `keywords` vs `results`; TV runtime fallback to `last_episode_to_air`; `created_by` for TV creators; crew dedup; TMDB score 0-10→0-100; `external_ids` for imdb/wikidata). Call TMDB with `?append_to_response=keywords,credits,external_ids` for both types.
- **`db_writer.py`** — `upsert_parsed_title()` (insert-or-refresh, returns is_new; **keywords full-replace**, other junctions INSERT OR IGNORE, external_scores upsert), `record_recommendation_link()`, `seed_already_processed()`.
- **`discover.py`** — `build_discover_params(content_type, original_language, ..., date_gte=None, date_lte=None)` + `paced_get()` (self-throttle, 429 backoff via `Retry-After`).
  - **Branches on `content_type`**: movies use `primary_release_date.gte/.lte`, `with_runtime.gte`, `include_video`; TV uses `first_air_date.gte/.lte` and **omits runtime + include_video** (TV `with_runtime` filters by often-empty `episode_run_time`, silently dropping shows like Breaking Bad).
  - Uses `with_original_language` (content filter), NOT `language` (translation only). No `vote_average` floor.
  - Date params **only included when non-None** (a None value would send a broken URL param). No years-ago fallback anymore — the caller supplies bounds.
- **`date_windows.py`** — solves TMDB's **hard 500-page pagination cap**. `initial_windows()` (coarse year chunks), `split_window()` (halve a window by date), `resolve_windows_under_cap(probe_total_pages, date_gte, date_lte, chunk_years=10)` (adaptively splits any window still >500 pages via an injected probe callable; accepts full 'YYYY-MM-DD' strings, converts years to int internally), `date_param_names()`.
- **`sync_pipeline.py`** — notebook-driven fetch primitives (loop lives in the notebook, not here): `known_tmdb_ids`, `fetch_title_details`, `fetch_discover_page` (passes `**filter_kwargs` incl. date bounds straight through to `build_discover_params`), `fetch_recommendations_page`, `process_one_candidate`, `get_highly_rated_seed_titles`.
- **`tmdb_export_ingest.py`** — daily ID export → `title_buzz_snapshots` (tmdb_popularity). Watermark-resumable (`MAX(snapshot_date)`), `export_start ∈ {"watermark","full"}`, 90-day retention clamp, streams the gzip line-by-line.
- **`recency.py`** — `recency_weight(watched_date, half_life_days)` = `0.5 ** (days_since / half_life)` + presets (`2d`…`lifetime`).
- **`critic_score.py`** — `critic_score(scores, weights)` weighted blend; missing sources excluded and remaining weights rescaled to sum to 1; returns None if nothing available.

*(Note: `utils/net.py` with `force_ipv4()` is referenced in the user's notebooks but authored by the user — not part of the reviewed module set.)*

---

## 6. Candidate discovery (Phase 1b) — how the notebook loop works

The most involved runtime flow — combines threading, pagination, and date-windowing.

**The problem chain that shaped it:**
1. A broad sweep (all English movies since 1940) is ~2000 pages, but **TMDB hard-caps pagination at 500** (status_code 22 beyond that).
2. So the date range is split into windows via `date_gte`/`date_lte`, each staying under 500 pages.
3. Title density isn't uniform (streaming era >> 1940s), so **fixed chunks don't reliably stay under the cap** — `resolve_windows_under_cap` probes each window and adaptively splits dense ones. Prevents silent truncation.

**Threading model (correctness-critical):**
- **Parallelize the fetches, serialize the writes.** SQLite is single-writer; concurrent writers get `database is locked`.
- Worker threads (`ThreadPoolExecutor`, `MAX_WORKERS≈5`, under TMDB's 20-connection ceiling) do **network-only** work (`fetch_title_details` + parse), each with its own `requests.Session` via thread-local.
- The **main thread owns the single SQLite connection** and does every `upsert_parsed_title`, plus all `known_ids` set mutation/dedup (avoids a race on the shared set).
- Per-**title** threading, not per-page: ~95% of I/O per page is the ≤20 detail calls, not the 1 discover call. Pagination stays sequential (it learns `total_pages` as it goes).
- Memory: completed `Future` results accumulate until the `with ThreadPoolExecutor` block exits; bounded per-page (~20 titles). Only matters if consolidating to one long-lived pool across pages, where you'd `futures.pop(fut)` after consuming.

**The `filters` vs date-bounds separation (a repeatedly-hit gotcha):**
- `config.yaml`'s `discover_filter` holds `min_runtime_minutes`, `min_vote_count`, `date_gte`, `date_lte`.
- In the notebook, **`pop` the date bounds out** of the `filters` dict into `SWEEP_DATE_GTE`/`SWEEP_DATE_LTE`. `filters` must then hold only the constant per-request params.
- Date bounds vary per window, so they're always passed **explicitly** (`date_gte=gte, date_lte=lte`), never via `**filters` — passing them both ways raises `TypeError: multiple values for keyword argument`.
- Use the **same ceiling string** (`date_lte`) in the probe and the windows, or the control total won't reconcile.

**Reconciliation:** a bounded pre-windowing probe (page 1 of the full floor→ceiling range) gives `total_results` as a control total. Summing each window's `total_results` should reconcile to within ~1-2% (TMDB counts shift between calls; boundary titles can double-count). A wild mismatch (>5%) signals a gap or an unsplit over-cap window.

---

## 7. Key decisions & rationale (so they aren't relitigated)

**Architecture**
- Long-format tables over wide/per-person columns → adding a person is a new row.
- Notebooks own orchestration; `src/` holds single-purpose functions. Opaque sweep orchestrators removed.
- Installable package (`src/cinesync/`, hatchling `force-include` for `schema.sql`). Editable install resolves paths correctly; a non-editable wheel would mis-resolve `PROJECT_ROOT` — acceptable, never distributed.
- Derived facts are VIEWs, not tables (`current_ratings`, `unwatched_titles`) → can't drift.

**Data sourcing**
- TMDB `/discover` (per language, date-windowed) = candidate universe; daily exports only for popularity history.
- TMDB `/recommendations` (real collaborative filtering) is ingested; `/similar` is NOT (just genre+keyword overlap, redundant with our embeddings); `/reviews` is NOT (sparse for niche titles).
- `tmdb_rating` IS in the critic blend — confirmed via TMDB staff it's genuine independent TMDB-user ratings, never imported from IMDb/RT.
- `with_original_language` (content) vs `language` (translation only). TV date/runtime params differ from movie — a real bug that silently dropped Breaking Bad/Mad Men.
- No `vote_average` floor on discovery — low average can mean "niche/polarizing," which the project wants. Quality filtering belongs in `recommend()`'s `min_critic_score`.

**Signals**
- Three-tier model: `vote_average` = cumulative *sentiment* (overwrite); `popularity`/Reddit mentions = *attention*, needs time-series baseline (`title_buzz_snapshots`); `/trending` & Letterboxd popular = already short-window/curated, fetched live, not stored.
- Recency = exponential half-life decay (adjustable), not a hard cutoff. Composes with rewatch-as-evidence in Phase 4's LightGBM `sample_weight`.
- Rewatch is a real behavioral signal; multiple `watch_events` rows feed a derived count/weight rather than complicating `current_ratings`.
- Critic blend rescales weights for missing sources (never zero-fills or averages-backfills).
- Keywords full-replace on refresh (removed tags should vanish); other metadata lists INSERT OR IGNORE (staleness tolerated).

**Scope guards**
- TV at series level only.
- Awards: stored but low-confidence (uneven coverage for niche titles).
- Reddit buzz: search **per known title** (not mention-extraction); cross-sectional z-score immediately, longitudinal once history accumulates. (X/Instagram dropped — no practical API.)

---

## 8. Current state & immediate next steps

**Done & tested:** Phase 0; TMDB metadata parser; DB writers (incl. keyword full-replace); discover/recommendations fetch primitives; date-windowing with adaptive split; daily-export popularity ingestion; recency & critic-score utilities; the threaded, windowed Phase 1b discovery loop (working in the notebook, being instrumented with reconciliation counters). Full `uv sync` works (`numba>=0.59` pinned).

**Not yet built:**
1. **Letterboxd import** — `ratings.csv`/`diary.csv` → `watch_events` (+ TMDB `/search` resolution with a manual-review fallback for unmatched titles — "accept the gap": log unmatched to a side file, don't guess).
2. **OMDb + Wikidata enrichment** — populate `external_scores` (imdb/rt), `omdb_awards_text`, `title_awards`, `detailed_plot`.
3. The Phase 1 / 1b **notebooks** as saved artifacts (loops currently live in scratch cells).
4. Everything Phase 2 onward.

**Suggested next action:** build the Phase 1 Letterboxd import (the watched list is the foundation everything keys off — `unwatched_titles`, the recommendations seed query, and reconciliation all depend on `watch_events` being populated).

**Housekeeping:** canonical code lives only under `src/cinesync/`. Delete any lingering flat `src/*.py` or root-level `schema.sql` from earlier iterations.

---

## 9. People & taste profile
- `person_1` = Abdullah, `person_2` = Rehab. Taste: world cinema (Japanese, Korean, Hindi, French, and more — see the 15-language config), period pieces, mind-bending mystery/horror, and creative niche/boundary-pushing films with social/political themes in surreal styles.
