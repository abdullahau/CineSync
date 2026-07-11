# CineSync — Project Context & Handoff

> Self-contained briefing for continuing CineSync in a fresh conversation. Captures the objective, every significant design decision, the current state of the code, and what comes next. Read top to bottom before resuming, and attach the actual source files alongside it so a fresh Claude reads real code rather than a summary of it. **Re-read uploaded files rather than trusting this doc for exact signatures — Abdullah edits between sessions.**

---

## 1. Objective

Build a **local, notebook/script-based recommendation system** that learns the movie/TV taste of one or more people from their Letterboxd ratings, then helps them discover what to watch next. It doubles as a **hands-on learning vehicle** for data science and ML/deep-learning fundamentals — each phase should teach a specific concept rather than being a black box.

### What the system needs to do
1. **Capture rich metadata** per title — language, genre, director, writer, cast, production company, producer-tier crew + DP, year, theme/style (keywords), plot(s), taglines, awards, and critic/audience scores.
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

(buzz_window is good, but I want to be able to state where I want something "buzzing" or not.)

(Consider adding "certificate/age-rating" filter to ensure movies are, as per US standards, at maximum of age rating)

(consider creating a quarterly or monthly "wrapped" - like top movies, genres, themes, aesthetic - similar to spotify wrap)

### Hard constraints / cross-cutting values
- Works for **1 person, a couple, or a group** — never hardcoded to two people (long-format tables looping over a `people` list).
- Covers **both movies and TV** — TV at **series level only** (no per-episode rows). `content_type` is just another column, not a separate pipeline.
- **World cinema** properly represented via **per-language** `/discover` sweeps (15 languages: en, ko, ja, hi, ur, fr, it, es, fa, de, sv, no, id, ms, bn).
- **Fully local** — SQLite (relational source of truth) + pandas (analysis), no cloud dependency.
- **Orchestration lives in notebooks** (visible, inspectable loops, now as `notebooks/*.py` scripts); `src/cinesync/` holds small single-purpose functions. Opaque "sweep" orchestrators were deliberately removed — the once-standalone `tmdb_sweep.py` was folded back into `notebooks/tmdb_ingest.py` (see §5/§6).
- **Installable package layout** (`src/cinesync/`, hatchling) so notebooks use clean `from cinesync.X import Y` with no `sys.path` hacks.
- **Explicit over clever** — inspectable, minimal code; no auto-detection logic, CLI wrappers, or unnecessary abstractions. Surface design decisions rather than applying them silently. Transformation logic lives in pandas (notebook layer), not SQL, so joins/aggregations stay visible.

---

## 2. Tech stack

- **Python ≥3.11**, **uv** for deps + venv (`uv sync`, `uv run --env-file .env`). Package installs editable.
- **SQLite** (`cinesync.db`, source of truth) + **pandas**. `cinesync_flat.db` is a denormalized export (`titles_flat`) rebuilt via `ATTACH DATABASE`. SQLite **≥ 3.35** confirmed (needed for `DROP COLUMN`); `GROUP_CONCAT ... FILTER` needs ≥ 3.25.
- **Planned ML libs:** sentence-transformers, scikit-learn, umap-learn, hdbscan, lightgbm, torch, plotly.
- **`numba>=0.59` pinned** in pyproject to resolve a Python-3.12 resolver conflict pulled in transitively via umap-learn — without it `uv sync` fails.
- **Data sources & how they're reached:**
  - **TMDB** (primary metadata, `/discover`, `/recommendations`, daily ID exports/popularity) — API key.
  - **IMDb** — now a **first-class source, replacing OMDb** (OMDb abandoned: rate limits). Two channels:
    - **Bulk TSV datasets** (`datasets.imdbws.com`) → ratings + genres, streamed and joined locally.
    - **GraphQL scraper** (`caching.graphql.imdb.com`, `Title_Storyline` persisted query, via `curl_cffi` with `impersonate="chrome"`) → plot outline/summary/synopsis, taglines, keywords.
  - **Letterboxd** — scraped (no API), `curl_cffi` async, JSON-LD parse. **Routes by IMDb ID** (`letterboxd.com/imdb/{imdb_id}/`) with a **TMDB-ID fallback** (`letterboxd.com/tmdb/{tmdb_id}/`, movies only).
  - **Wikidata SPARQL** — awards, credits, RT IDs; plot text needs a **two-step Wikipedia parse-API** fetch.
  - **Rotten Tomatoes** — RT ID from Wikidata; scores scraped (flagged fragile).
  - **Reddit via PRAW** (buzz, planned).

(Rotten Tomato links for each title can be potentially extracted from Wikidata Query SPARQL)

---

## 3. Phase roadmap

| Phase | Notebook (planned) | Teaches | Status |
|---|---|---|---|
| 0 | — | setup, schema, package | **DONE** |
| 1 | `01_collect` | data wrangling, APIs | TMDB parser + writers **DONE**; IMDb bulk (ratings/genres) **DONE**; IMDb GraphQL enrichment (plots/taglines/keywords) **DONE**; Letterboxd scrape **DONE**; Letterboxd *watch-history* import + Wikidata awards/RT **TODO** |
| 1b | `01b_Candidate_Summary` | candidate generation, threading, pagination | fetch primitives + adaptive date-windowing **DONE**; sweep loop in `notebooks/tmdb_ingest.py` (votes/rating/lang) **DONE**; summary notebook built |
| — | `analysis` (EDA) | pandas EDA, missingness | spine + helpers verified **DONE**; plotly viz **IN PROGRESS** |
| 2 | `02_features` | encoding, embeddings | TODO |
| 3 | `03_clusters` | UMAP + HDBSCAN, faceted per person | TODO |
| 4 | `04_preference_models` | LightGBM per person, feature importance | TODO |
| 4.5 | (in 04) | holdout eval (split by **title**, not row) | TODO |
| 5 | `05_two_tower` | PyTorch (movie tower + N-person embeddings) | TODO |
| 6 | `06_mood_recommender` | semantic search / nearest-neighbor | TODO |
| 7 | `07_buzz_score` | combining heterogeneous signals, z-scores | TODO |
| 8 | `08_novelty_critic` | weighted scoring, distances | `critic_score()` **DONE**; novelty dial **TODO** |
| 9 | `09_unified_scoring` | the `recommend()` interface, `disagreement_score` | TODO |
| 10 | `10_feedback_loop` | implicit vs explicit signal | TODO |

---

## 4. Database schema (current)

Lives at `src/cinesync/schema.sql`. Created via `uv run cinesync-init-db`. `title_id` convention: `'movie_<tmdb_id>'` / `'tv_<tmdb_id>'`. Schema convention throughout: **column-level `NOT NULL` + a separate table-level `PRIMARY KEY (...)`** constraint (not inline `TEXT PRIMARY KEY`), consistent across sibling tables.

### Core
- **`people`** `(person_id PK, name)`.
- **`titles`** `(title_id PK, tmdb_id, content_type, name, original_language, release_year, certificate, runtime_minutes, number_of_seasons, status, imdb_id, wikidata_id, tmdb_overview, source, date_added, last_refreshed)`.
  - `certificate` = US age-rating (`R`, `TV-14`, `TV-MA`, …), sourced from TMDB. Nullable; feeds a planned `recommend()` age-rating filter.
  - **Renamed:** `omdb_overview` → `imdb_overview` earlier, then plot fields moved off the spine entirely (see `title_plots`). `tmdb_overview` stays on the spine.
  - **Dropped:** `omdb_awards_text` (awards now live structurally in `title_awards`); `detailed_plot` migrated into `title_plots.wikipedia_plot`.
  - `source` carries specific provenance (`discover_lang_ja`, `recommendations_via_movie_1083381`, `letterboxd_import`). `date_added` immutable; `last_refreshed` bumped on re-fetch.
  - Empty-string `imdb_id`/`wikidata_id`/`tmdb_overview` are normalized to **NULL** (in the parser and retroactively).

### Metadata junction tables
- **`title_genres`** `(title_id, genre)` — **sourceless**; relies on a canonical `GENRE_MAP` so TMDB and IMDb vocabularies converge (`"Sci-Fi"` / `"Sci-Fi & Fantasy"` → `"Science Fiction"`, `"Reality-TV"` → `"Reality"`). Trade-off accepted: some fantasy-tagged TV inherits the Science Fiction label.
- **`title_keywords`** `(title_id, keyword, source)` — **PK `(title_id, keyword, source)`**. The `source` column is load-bearing: it stops a TMDB keyword full-replace from silently wiping IMDb-sourced keywords. Replace is **per-source** (delete-then-reinsert within a source). Keywords are the most direct theme/style signal.
- **`title_credits`** `(title_id, role, name, "order")` — `role ∈ {director, writer, creator, cast}`. **Match on `job`, never `known_for_department`.**
- **`title_companies`** `(title_id, company_id, company_name)` — **PK `(title_id, company_id)`** so distinct companies sharing a name aren't merged (a title can list many companies; `company_id` is the identity).
- **`title_crew_extra`** `(title_id, job, name, department)` — producer-tier credits + DP; `job` stored **verbatim** (seniority preserved). **PK `(title_id, job, name)`.**
- **`title_plots`** `(title_id PK, imdb_outline, imdb_summary, imdb_synopsis, wikipedia_plot, tagline, imdb_error, imdb_fetched_at)` — **1:1 with titles**, holds the long-form plot text (IMDb three tiers + Wikipedia) plus a single IMDb `tagline`. Kept off the spine so the wide text columns don't bloat `titles`. `imdb_fetched_at`/`imdb_error` are the GraphQL-scraper's resume/error state: a row with `imdb_fetched_at` set and `imdb_error` NULL is a success and drops off the work list; on failure only those two columns are written, preserving any existing text and `wikipedia_plot`.
  - **The old standalone `title_taglines` table is gone** — collapsed into `title_plots.tagline` (IMDb owns the column, first tagline wins). Multi-tagline history was dropped as not worth a junction table.

### Ratings / watch history
- **`watch_events`** `(watch_event_id PK, person_id, title_id, watched_date, is_rewatch, rating_at_watch)` — single ingestion target for `diary.csv` and bare `ratings.csv` (`is_rewatch` NULL = unknown). **UNIQUE INDEX `(person_id, title_id, watched_date)`** → idempotent re-imports via `INSERT OR IGNORE`.
- **`current_ratings`** (VIEW) — latest rating + last-watched per (person, title). Derived, can't drift.

### Scores & signals
- **`title_scores`** `(title_id, source, score REAL 0-100, sample_size, date_pulled)` — **PK `(title_id, source)`**; `source ∈ {rt_critic, rt_audience, imdb_rating, tmdb_rating}`. **(Renamed from `external_scores`.)** Overwrite-on-refresh. Missing source = no row; the blend rescales remaining weights, never backfills. (Letterboxd rating is NOT here — it lives in `title_letterboxd_stats`.)
- **`title_letterboxd_stats`** `(title_id PK, rating_value, rating_count, review_count, rating_0_5_count … rating_5_0_count, watches, lists, likes, top_rank)` — **migrated in from the old standalone `letterboxd.db`.**
  - Official `rating_value` uses a proprietary anti-gaming weighted algorithm and is **withheld below a rating-count threshold** (frequently NULL). When it's NULL, `rating_count`/`review_count` are nullified too.
  - `top_rank` is NULL unless in the Top 500 (movies) / Top 250 (documentary) list.
- **`title_imdb_rating_dist`** `(title_id PK, votes_1 … votes_10, total_votes, fetched_at)` — **placeholder**, to be populated later from the IMDb ratings HTML page. `total_votes` checksums against `title_scores.sample_size` for `imdb_rating`.
- **`title_popularity`** `(title_id, source, snapshot_date, value)` — **PK `(title_id, source, snapshot_date)`**; **time series**; `source ∈ {tmdb_popularity, reddit_mentions}`. **(Renamed from `title_buzz_snapshots`.)** Needs a baseline to detect a spike. (See §7 for the EWMA scaling decision.)
- **`title_awards`** `(title_id, award_name, result, year, source)` — `result ∈ {won, nominated}`, from Wikidata P166/P1411. Low-confidence supplementary signal.

### Recommendation discovery & output
- **`unwatched_titles`** (VIEW) — `titles` minus anything in `watch_events`. Replaced the old `candidate_pool` table (which held watched titles as "eligible" — a real bug). Eligibility is now derived, always correct.
- **`title_recommendation_links`** `(seed_title_id, recommended_title_id, rank, date_pulled)` — TMDB `/recommendations` output as durable data; also the dedup check for the recommendations sweep.
- **`recommendations`** `(recommendation_id PK, title_id, generated_at, mode, mood_query, novelty_dial, recency_half_life_days, buzz_window, min_critic_score, aggregation_mode, score_breakdown_json)`. `recency_half_life_days` stored **resolved/numeric**. `sort_by` deliberately NOT stored (display-only).
- **`feedback`** `(feedback_id PK, recommendation_id FK, person_id, action, rating, reject_reason, date_logged)` — `action ∈ {watched_full, watched_partial, rejected_pre_watch}`. Linked to `recommendations` so Phase 10 can trace which mood/novelty context produced an outcome.

### `cinesync_flat.db` — `titles_flat`
Denormalized snapshot, one row per title, everything pre-joined. **Materialized (`CREATE TABLE AS`), not a view — rebuild it in the notebook's first cell** via the `ATTACH DATABASE 'cinesync_flat.db' … DROP/CREATE … DETACH` block so every session is fresh. Aggregates genres/keywords/companies/credits with `GROUP_CONCAT`, pivots `title_scores` into `rt_critic`/`rt_audience`/`imdb_rating`/`tmdb_rating` columns, and pulls Letterboxd from `title_letterboxd_stats` (`letterboxd_rating`, `lb_watches`, `lb_lists`, `lb_likes`, `lb_top_rank`, the ten buckets, `lb_rating_dist_count`, and `lb_implied_rating`). Deletion order for purge operations (both FK directions respected): `feedback` → `recommendations` → `title_recommendation_links` → `watch_events` → `title_awards` → `title_popularity` → `title_scores` → `title_crew_extra` → `title_companies` → `title_keywords` → `title_credits` → `title_genres` → (`title_plots`, `title_letterboxd_stats`, `title_imdb_rating_dist`) → `titles`. Use `ATTACH`/temp-table strategies (e.g. a `_purge` table) rather than large `IN (...)` clauses to stay under SQLite's bound-variable limit.

---

## 5. Code modules

**Layout note (changed):** `src/cinesync/` holds only cross-cutting helpers + the two pure scoring utilities; **all ingestion modules now live under `src/cinesync/ingestion/`**; and **orchestration lives in `notebooks/` as plain `.py` scripts** (`tmdb_ingest.py`, `imdb_ingest.py`, `letterboxd_ingest.py`) plus two analysis notebooks (`01a_Data_Wrangling.ipynb`, `01b_Candidate_Summary.ipynb`). The earlier `discover.py` / `sync_pipeline.py` / `tmdb_sweep.py` / `tmdb_export_ingest.py` / top-level `tmdb_parser.py` / `letterboxd_scrape.py` modules **no longer exist** — see the mapping below.

### `src/cinesync/` (top level)
- **`paths.py`** — `PROJECT_ROOT`, `DATA_DIR`, `DB_SCHEMA_PATH`, **`DB_PATH`** (`data/cinesync.db`), `NOTEBOOKS_DIR`, `LOGS_DIR`, `TMP_DIR`. Notebooks import `DB_PATH` from here.
- **`config_loader.py`** — `load_config()`; substitutes `${ENV_VAR}` placeholders, raises clearly if unset.
- **`init_db.py`** — `init_db()`, console script `cinesync-init-db`; loads `schema.sql` (via `DB_SCHEMA_PATH`/`importlib.resources`). Won't overwrite an existing DB.
- **`recency.py`** — `recency_weight(watched_date, half_life_days)` = `0.5 ** (days_since / half_life)` + presets.
- **`critic_score.py`** — `critic_score(scores, weights)` weighted blend; missing sources excluded and remaining weights rescaled to sum to 1; None if nothing available.
- **`utils/net.py`** — `paced_get()` / `force_ipv4()` rate-limited GET utility (user-authored). `tmdb_fetch.py` imports `paced_get` from here.

### `src/cinesync/ingestion/`
- **`tmdb_parser.py`** — `parse_tmdb_response(data, content_type, source)` → dict of rows for every table (`title`/`genres`/`keywords`/`companies`/`credits`/`crew_extra`/`score`). Handles movie/TV shape differences (keywords key `keywords` vs `results`; TV runtime = mean of `episode_run_time`, fallback to `last_episode_to_air.runtime`; `created_by` for TV creators; credit + crew dedup; TMDB score 0-10→0-100; `external_ids` for imdb/wikidata). Call TMDB with `?append_to_response=keywords,credits,external_ids`. *(Still emits a legacy `detailed_plot: None` key the writer ignores.)*
- **`tmdb_fetch.py`** — **absorbs the old `discover.py` + `sync_pipeline.py`.** `build_discover_params(content_type, page, lang=None, min_rating=None, min_vote_count=50, min_runtime_minutes=40, date_gte=None, date_lte=None)`, plus the fetch primitives `fetch_title_details`, `fetch_discover_page`, `fetch_recommendations_page`, and `get_highly_rated_seed_titles(conn, content_type, min_rating=4.0)` (seeds from `current_ratings`). Uses `paced_get` from `utils.net` (not defined here).
  - `build_discover_params`: movies use `primary_release_date.gte/.lte`, `with_runtime.gte`, `include_video`, `sort_by=primary_release_date.asc`; TV uses `first_air_date.gte/.lte`, `sort_by=first_air_date.asc`, and **omits runtime + include_video** (TV `with_runtime` filters by often-empty `episode_run_time`, silently dropping Breaking Bad / Mad Men). `with_original_language` (content) NOT `language` (translation). **Sort is ALWAYS date-ascending.** `min_rating` maps to `vote_average.gte` **only when passed** — there is no floor on plain discovery. Date params included only when non-None.
- **`date_windows.py`** — solves TMDB's **hard 500-page pagination cap** (`TMDB_MAX_PAGES = 500`). `earliest_date(probe_payload, content_type)` (floor date from a probe's first dated result), `split_window(gte, lte)` (date-bisect), and **`resolve_windows(probe_window, date_gte, date_lte, content_type, probe_session, max_iterations=2000, **params)`** — **renamed from `resolve_windows_under_cap`**, and simplified: it starts from the **full range as one window** and bisects by date only when a probed window is still over the cap (no pre-chunking / `chunk_years`). `probe_window(gte, lte, content_type, probe_session, **params) -> (total_pages, total_results)` is the injected callable.
- **`db_crud.py`** — **consolidated CRUD** (four banner sections: TMDB title metadata / TMDB recommendation links / Letterboxd stats / IMDb data). Every function commits its own transaction. Key functions:
  - `upsert_tmdb_title(conn, parsed)` — **renamed from `upsert_parsed_title`.** Insert-or-refresh, returns is_new; keywords per-source replace (`source='tmdb'`), other junctions `INSERT OR IGNORE`, `title_scores` upsert.
  - `known_tmdb_ids()`, `record_recommendation_link()`, `seed_already_processed()` (names unchanged).
  - `titles_missing_letterboxd_stats(conn)` — anti-join work list `(title_id, imdb_id, tmdb_id, content_type)`.
  - `upsert_letterboxd_stats(conn, film)` — writes the scraper's per-title dict (`INSERT OR REPLACE`, commits per call).
  - `titles_missing_imdb_enrichment(conn)` — IMDb-scrape work list `(title_id, imdb_id)`: titles with a usable `imdb_id` whose `title_plots` row is missing, never fetched (`imdb_fetched_at IS NULL`), or last errored (`imdb_error IS NOT NULL`).
  - `upsert_imdb_enrichment(conn, title_id, rec, genre_map=None)` — fans one scraped IMDb record into `title_plots` (plots + first `tagline`), `title_genres` (additive, mapped), and `title_keywords` (scoped `source='imdb'`, per-source full-replace). On `rec['error']`, writes only `imdb_error`/`imdb_fetched_at`. **Takes `title_id` directly** (the work-list query does the `imdb_id`→`title_id` resolution, not `load_title_id_map`).
- **`imdb_dataset.py`** — **renamed from `imdb_ingest.py`.** IMDb **bulk TSV** straight into `cinesync.db`, no staging DB. Per file: download → stream-read → write → delete. Shared `_stream_tsv(conn, gz_path, needed_cols, emit, sql, …)` skeleton owns open/header-map/line-loop/skip-malformed/batch/commit/progress; `emit(fields, idx) -> iterable of tuples` is the only per-file seam. `ingest_ratings` (1:1 upsert → `title_scores`, `imdb_rating`, 0-10→0-100), `ingest_genres` (1:N fan-out → `title_genres`, comma-split, mapped, ignore-on-conflict), `normalize_genres()` (applies the shared `GENRE_MAP` to existing TMDB rows via a temp `_genre_map` table), `run_ingestion()` (ratings then basics). `tconst`→`title_id` join done in Python via **`load_title_id_map` (lives here now, not in `db_crud`)** — a `tconst` not in the map is skipped = the "keep only my titles" filter.
- **`imdb_fetch.py`** — IMDb GraphQL **network + retry only** (`Title_Storyline` persisted query, `curl_cffi` `impersonate="chrome"`, exponential backoff on 403/429/5xx). `fetch_title(session, imdb_id, retries=4)` returns `{'title': …}` or `{'error': …}`.
- **`imdb_parser.py`** — raw IMDb JSON → normalized enrichment record via `parse(title)` (plot outline/summary/synopsis through `strip_html`, taglines, keywords, genres). No error handling (that's the fetch layer); `certificate`/`keywords_total` deliberately dropped (certificate comes from TMDB).
- **`tmdb_popularity.py`** — **renamed from `tmdb_export_ingest.py`.** Daily ID export → **`title_popularity`** (`source='tmdb_popularity'`). Watermark-resumable (`MAX(snapshot_date)`), 90-day retention clamp, streams gzip line-by-line, `INSERT OR IGNORE` for idempotency. `run_ingestion(conn, content_types=('movie','tv'), export_start='watermark'|'full')`.

### Orchestration moved to `notebooks/` (was `tmdb_sweep.py` + `letterboxd_scrape.py`)
- **`notebooks/tmdb_ingest.py`** — the discover/recommendations sweep loop (probe → adaptive windows → paginate → thread-pool detail fetch → main-thread upsert). Replaces the removed config-driven `tmdb_sweep.py`; the `config.yaml` `tmdb_discover` block (`votes` / `rating` / `lang`) still parameterizes it, and **`min_rating` is now a plain 0–10 float in config** (`rating.min_rating: 6.5`) passed straight through — the earlier "0–100, divide by 10 at the driver" rule is **gone**.
- **`notebooks/imdb_ingest.py`** — bulk-dataset ingest + `normalize_genres`, then the GraphQL enrichment loop over `titles_missing_imdb_enrichment` with jittered pacing. Owns the canonical `GENRE_MAP`.
- **`notebooks/letterboxd_ingest.py`** — the async Letterboxd scraper (was `letterboxd_scrape.py`). IMDb-slug-first routing with TMDB-slug fallback (movies only), `curl_cffi` `AsyncSession(impersonate="chrome124")`, `CONCURRENCY=8`, JSON-LD/`parsel` parse, failures logged to `data/logs/letterboxd_scrape_failures.jsonl`. Writes via `upsert_letterboxd_stats`.

---

## 6. Candidate discovery (Phase 1b) — how the sweep works

**The problem chain:** a broad sweep (all English movies since 1940) is ~2000 pages, but **TMDB hard-caps pagination at 500**. So the date range is split into windows (`date_gte`/`date_lte`) each under 500 pages. Title density isn't uniform (streaming era ≫ 1940s), so fixed chunks don't reliably stay under the cap — `resolve_windows` probes each window and adaptively bisects dense ones.

**Threading model (correctness-critical):** parallelize fetches, serialize writes. SQLite is single-writer. Worker threads (`ThreadPoolExecutor`, `MAX_WORKERS≈5`, under TMDB's 20-connection ceiling) do network-only work, each with its own `requests.Session` via thread-local. The **main thread owns the single SQLite connection** and does every upsert + all `known_ids` set mutation/dedup (avoids a race on the shared set). Per-**title** threading, not per-page (~95% of I/O per page is the ≤20 detail calls). Pagination stays sequential. A global token-bucket rate limiter (~19 req/s) is cleaner than per-thread sleeps. **Always add request timeouts** or a hung request silently blocks an executor thread.

**`filters` vs date-bounds separation (repeatedly-hit gotcha):** the sweep's per-request filter params (`min_runtime_minutes`, `min_vote_count`, `lang`, `min_rating`) come from `config.yaml`'s `tmdb_discover` block; date bounds are held separately. In the notebook, keep the date bounds **out** of the `filters` dict (e.g. `SWEEP_DATE_GTE`/`SWEEP_DATE_LTE`); `filters` must hold only constant per-request params. Date bounds are passed **explicitly** (`date_gte=gte, date_lte=lte`), never via `**filters` — both ways raises `TypeError: multiple values for keyword argument`. Use the **same ceiling string** in the probe and the windows.

**Reconciliation:** a bounded pre-windowing probe (page 1 of the full floor→ceiling range) gives `total_results` as a control total. Summing each window's `total_results` should reconcile to within ~1-2%. A wild mismatch (>5%) signals a gap or an unsplit over-cap window.

---

## 7. Key decisions & rationale (so they aren't relitigated)

**Architecture**
- Long-format tables over wide/per-person columns → adding a person is a new row.
- Notebooks own orchestration; `src/` holds single-purpose functions. Derived facts are VIEWs (`current_ratings`, `unwatched_titles`) → can't drift.
- Installable package (hatchling `force-include` for `schema.sql`). Editable install resolves paths; a non-editable wheel would mis-resolve `PROJECT_ROOT`.

**Data sourcing**
- **OMDb abandoned** (rate limits) → **IMDb** is the source of truth for IMDb rating + genres (bulk TSV) and plot/taglines/keywords (GraphQL scraper).
- TMDB `/discover` (per language, date-windowed) = candidate universe; daily exports only for popularity history.
- TMDB `/recommendations` (real collaborative filtering) is ingested; `/similar` (genre+keyword overlap, redundant with embeddings) and `/reviews` (sparse) are NOT.
- `tmdb_rating` IS in the critic blend — confirmed via TMDB staff it's genuine independent TMDB-user ratings.
- `with_original_language` (content) vs `language` (translation only). TV date/runtime params differ from movie.
- No `vote_average` floor on discovery — low average can mean niche/polarizing, which the project wants. Quality filtering belongs in `recommend()`'s `min_critic_score`.
- Letterboxd IMDb-ID-first routing is critical: TMDB movie/TV IDs share a numeric namespace, and `letterboxd.com/tmdb/{id}` resolves movies only, so a TV title routed by TMDB ID would collide.

**Signals**
- Three-tier model: `vote_average` = cumulative *sentiment* (overwrite); popularity/Reddit mentions = *attention*, needs time-series baseline; `/trending` & Letterboxd popular = short-window/curated, fetched live, not stored.
- **Buzz storage at scale:** daily snapshots for all ~71–80k titles is unnecessary. Prefer an **EWMA running-state (one row per title, updated in place)** for longitudinal baseline detection (~9MB vs ~780MB); retain a raw series only for a dynamic watchlist of actively-moving titles if buzz-trajectory ML is needed later.
- Letterboxd official `rating_value` is anti-gaming-weighted and withheld below a threshold; `lb_implied_rating` (naive weighted histogram mean over the ten buckets, 0–5 scale, `NULLIF` for zero-denominator safety) is the fallback and consistently runs **higher** than the official value. Coverage flags: `has_letterboxd_rating`, `has_lb_implied`, `has_lb_any`.
- Recency = exponential half-life decay (adjustable), not a hard cutoff. Composes with rewatch-as-evidence in Phase 4's LightGBM `sample_weight`.
- Critic blend rescales weights for missing sources (never zero-fills or backfills).
- Keyword replace is **per-source** (a TMDB refresh must not wipe IMDb keywords); genres stay sourceless and converge via `GENRE_MAP`.

**Scope guards**
- TV at series level only. Awards stored but low-confidence (uneven niche coverage). Reddit buzz searched per-known-title; cross-sectional z-score now, longitudinal once history accumulates. (X/Instagram dropped — no practical API.)

**Silent-failure watchlist (the primary risk class)**
- TMDB movie/TV IDs share a numeric namespace (Letterboxd routing). IMDb `tt`-prefix vs bare digits silently breaks joins. `GROUP_CONCAT ... FILTER` needs SQLite ≥ 3.25; `TEXT PRIMARY KEY` without `NOT NULL` silently accepts NULL in older SQLite; `executescript` vs `execute` differ for multi-statement SQL; `INSERT OR REPLACE` without a uniqueness constraint silently appends. `all-MiniLM-L6-v2` silently truncates at ~256 tokens — dangerous for multi-paragraph plots. Wikidata records some wins under both P166 and P1411 → `FILTER NOT EXISTS` for award dedup; label-prefix matching beats QID paths for prestige families.

---

## 8. Current state & immediate next steps

**Done & tested:** Phase 0; TMDB metadata parser; consolidated `db_crud.py` writers (incl. per-source keyword replace); discover/recommendations primitives (`tmdb_fetch.py`); adaptive date-windowing (`date_windows.resolve_windows`); the sweep loop now in `notebooks/tmdb_ingest.py`; daily-export popularity ingestion → `title_popularity` (`tmdb_popularity.py`); recency & critic-score utilities. **IMDb bulk TSV** (ratings + genres, `imdb_dataset.py`) and **IMDb GraphQL enrichment** (plots/tagline/keywords, `imdb_fetch.py`/`imdb_parser.py` + `upsert_imdb_enrichment`) into `cinesync.db`. **Letterboxd stats scrape** (IMDb-slug routing + TMDB fallback, `notebooks/letterboxd_ingest.py`) into `cinesync.db`. **Module reorg:** all ingestion under `ingestion/`; `discover`/`sync_pipeline`/`tmdb_sweep`/`tmdb_export_ingest`/`letterboxd_scrape` retired into `tmdb_fetch.py`/`tmdb_popularity.py`/notebooks. **Schema evolution** since last handoff: `certificate` added to `titles`; `title_taglines` collapsed into `title_plots` (+`tagline`/`imdb_error`/`imdb_fetched_at`); `title_buzz_snapshots` renamed `title_popularity`; (earlier) `title_scores` rename, `title_imdb_rating_dist` added, `title_keywords` re-PK'd with `source`, OMDb columns retired. EDA spine verified against a synthetic DB, incl. `lb_implied_rating`. Full `uv sync` works.

**Not yet built:**
1. **Letterboxd *watch-history* import** — `ratings.csv`/`diary.csv` → `watch_events` (+ TMDB `/search` resolution; "accept the gap" — log unmatched to a side file, don't guess). *This is the recommended next action: `watch_events` is the foundation `unwatched_titles`, the recommendations seed query, and reconciliation all depend on.*
2. **Wikidata enrichment** — populate `title_awards`, RT IDs, and Wikipedia plot (`title_plots.wikipedia_plot`); RT-critic/RT-audience into `title_scores`.
3. **IMDb ratings-distribution HTML scrape** → `title_imdb_rating_dist`.
4. **Plotly EDA visualizations** — missingness heatmaps first, then keyword-richness drill-downs.
5. Phase 2 onward (embeddings, clusters, models).

**Embedding design (Phase 2 direction):** long-context models (`BAAI/bge-m3`, `nomic-embed-text-v1.5`) preferred over SBERT for multi-paragraph plot text; a theme-forward composed field (keywords + genres + taglines) is the recommended primary embedding target.

**Housekeeping:** canonical code lives only under `src/cinesync/` (ingestion in `ingestion/`). Delete any lingering flat `src/*.py`, root-level `schema.sql`, or the retired standalone `letterboxd.db` / IMDb staging DB.

---

## 9. People & taste profile
- `person_1` = Abdullah, `person_2` = Rehab (collaborator). Never hardcode to two — loop over `people`.
- Taste: world cinema (Japanese, Korean, Hindi, French, Urdu, and more — see the 15-language config), period pieces, mind-bending mystery/horror, and creative niche/boundary-pushing films with social/political themes in surreal styles.

## Notes

Running this command creates a flattened table for review
```bash
sqlite3 data/cinesync.db < src/cinesync/schemas/table_flat.sql
```

Clean unused spaces in side a sqlite DB:
```bash
sqlite3 data/cinesync.db "VACUUM;"
```

Export `.env` variables into a terminal session:
```bash
export $(cat .env | xargs)
```

or 
```bash
uv run --env-file .env <file.py>
```
