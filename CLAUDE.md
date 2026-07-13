# CLAUDE.md — CineSync

Operating brief for Claude Code. This is the lean, every-session file; the full design history, schema, and rationale live in **`PROJECT_CONTEXT.md`** — read that before any non-trivial change.

## What this is
CineSync is a **local, script-based movie & TV recommendation system** that learns taste from Letterboxd ratings. SQLite (`cinesync.db`) is the relational source of truth; pandas is the analysis layer; orchestration lives in `pipelines/*.py` scripts (plus a couple of analysis notebooks). It's also a learning vehicle for DS/ML fundamentals, so favor inspectable code over black boxes.

## Environment & commands
- Package manager is **`uv`** (not pip/conda). Editable install.
  - Install/sync deps: `uv sync`
  - Run anything needing env vars (TMDB key, `EMAIL`, etc.): `uv run --env-file .env <cmd>`
  - Initialize the DB from schema: `uv run cinesync-init-db` (won't overwrite an existing DB)
  - Ingest drivers (all under `pipelines/`, run with `uv run --env-file .env python pipelines/<x>.py`): `tmdb_ingest.py` (discover/recommendations sweep, parameterized by `config.yaml`'s `tmdb_discover`), `imdb_ingest.py` (bulk TSV + GraphQL enrichment), `letterboxd_ingest.py` (stats scrape), `wikidata_ingest.py` (awards + RT slug + Wikipedia plot).
- Python **≥3.14** (per `pyproject.toml`). Heavy ML libs (sentence-transformers, umap-learn, hdbscan, lightgbm, torch, scikit-learn, beautifulsoup4) are **commented out** in pyproject until their phases — HTML parsing currently uses `parsel` (already a dep). `numba` was historically pinned for a umap-learn/3.12 resolver conflict; re-add that pin if you re-enable umap-learn.
- Tests: _(no suite yet — don't invent a `pytest` command; verify logic by running it in a scratch/synthetic SQLite DB instead, see Working style)._

## Repo layout
- `src/cinesync/` — canonical single-purpose functions. Drivers import `from cinesync.X import Y`.
  - Top level: `paths.py` (`DATA_DIR`, `LOGS_DIR`, `TMP_DIR`, `NOTEBOOKS_DIR`, `DB_PATH`, `DB_SCHEMA_PATH`), `config_loader.py`, `init_db.py`, `recency.py`, `critic_score.py`, `utils/net.py`
  - `schemas/` — `schema.sql` (canonical DB schema), `table_flat.sql`
  - `ingestion/` — **all ingestion + CRUD lives here, in per-source subpackages:**
    - `crud.py` — **all CRUD** (TMDB titles, recommendation links, Letterboxd stats, IMDb enrichment, Wikidata awards/meta/RT, Wikipedia plot)
    - `tmdb/` — `fetch.py` (discover/details/recommendations primitives), `parse.py`, `date_windows.py`, `popularity.py`
    - `imdb/` — `bulk.py` (bulk TSV), `graphql.py` (async GraphQL scraper), `parse.py`
    - `wikidata/` — `sparql.py` (QLever bulk fetch: spine + award statements + label resolution, imdb-keyed), `parse.py` (`tag_prestige` + `assemble_spine`/`assemble_awards`), `wikipedia.py` (plot fetch), `__init__.py` (`USER_AGENT`, contact email from `EMAIL` env)
- Orchestration loops live in **`pipelines/`** as plain `.py` scripts (`tmdb_ingest.py`, `imdb_ingest.py`, `letterboxd_ingest.py`, `wikidata_ingest.py`); `src/` stays loop-free. Analysis notebooks (`01a`, `01b`) live in `notebooks/`.
- **Retired modules** (don't reference — folded elsewhere): `discover.py`/`sync_pipeline.py`→`tmdb/fetch.py`; `tmdb_export_ingest.py`→`tmdb/popularity.py`; `db_crud.py`→`crud.py`; `imdb_dataset.py`→`imdb/bulk.py`; `imdb_fetch.py`→`imdb/graphql.py`; `imdb_parser.py`→`imdb/parse.py`; `tmdb_sweep.py`/`letterboxd_scrape.py`→`pipelines/`.
- **Per-service flat snapshots** are **rebuilt-per-session** denormalized read models, one standalone DB each under `data/` (`cinesync_flat_{tmdb,letterboxd,imdb,wiki,rt,coverage}.db`) so each opens on its own in a single-file SQLite viewer. Built from the `schemas/flat_*.sql` files by `pipelines/build_flats.py`; each `flat_*.sql` `ATTACH`es its own DB, full-`CREATE TABLE AS`. Never migrate them — regenerate. `coverage_flat` is the completeness/missing-data view (per-title presence + `*_fetched_at`/`*_error` flags across every service). *(The legacy single-file `cinesync_flat.db`/`titles_flat` via `table_flat.sql` is retained but superseded.)*

## Working style (how Abdullah wants changes made)
- **Explicit over clever.** No auto-detection, CLI wrappers, or speculative abstraction. Surface design decisions in the response; don't apply them silently.
- **Verify before presenting.** For any DB/logic change, run it against an in-memory or synthetic SQLite DB first and show it works. This project has a history of silent-failure bugs — assume they exist.
- **Re-read files, don't trust memory.** Abdullah edits between sessions. Open the actual file before editing; don't reconstruct signatures from prior context or from `PROJECT_CONTEXT.md`.
- **Transformation logic in pandas, not SQL.** Keep joins/aggregations visible in the notebook layer; `src/` functions take a DB connection and return DataFrames.
- **Flag bugs by severity.** Prefer a small, reviewable diff; propose, don't auto-apply large rewrites.

## Facts that bite (silent-failure watchlist)
- **SQLite is single-writer.** TMDB discovery uses a **thread pool** (workers network-only, main thread owns the one connection + all shared-set mutation). IMDb + Letterboxd use **asyncio** (all coroutines on one event-loop thread; the **main coroutine** does every write in the `as_completed` loop, fetch coroutines do network only). Never write from a worker thread or a fetch coroutine.
- **Rate limiting is per-service under `config.yaml`'s `rate_limiting.<service>` block.** Plain-`requests` fetchers (tmdb/wikidata/wikipedia) go through **`net.paced_request(session, url, service=…, …)`** (GET/POST, retries 429+5xx). The two `curl_cffi` async scrapers (imdb/letterboxd) share **`net.AsyncRateGate`** (global even-spacing gate) + **`net.paced_request_async`**; their block uses `concurrency`/`min_interval`/`max_retries`/`timeout` (IMDb also nothing else; Letterboxd same). **Endpoint URLs and User-Agents live in code, not config**; the Wikidata/Wikipedia UA contact email is imported from the `EMAIL` env var (`ingestion/wikidata/__init__.USER_AGENT`).
- **`title_id` = `movie_<tmdb_id>` / `tv_<tmdb_id>`.** TMDB movie/TV IDs share a numeric namespace — this is why Letterboxd routing is **IMDb-ID-first** with a TMDB-ID fallback (TMDB fallback resolves movies only).
- **IMDb IDs** are `tt`-prefixed strings; bare digits silently break joins. Empty-string `imdb_id`/`wikidata_id`/`tmdb_overview` must be NULL, not `''`.
- **`title_keywords` PK is `(title_id, keyword, source)`** — keyword replace is **per-source** so a TMDB full-replace can't wipe IMDb keywords.
- **Genres are sourceless**, converged via the canonical `GENRE_MAP` (`Sci-Fi`/`Sci-Fi & Fantasy` → `Science Fiction`, `Reality-TV` → `Reality`).
- **Schema convention:** column-level `NOT NULL` + a separate table-level `PRIMARY KEY (...)`, not inline `TEXT PRIMARY KEY`. Match sibling tables.
- **Scores table is `title_scores`** (renamed from `external_scores`), sources `{rt_critic, rt_audience, imdb_rating, tmdb_rating}`. Letterboxd rating is NOT here — it's in `title_letterboxd_stats`.
- **Wikidata enrichment is a BULK QLever export, not per-title WDQS** (WDQS timed out at 70k scale; `ingestion/wikidata/sparql.ENDPOINT` = `qlever.dev`). Two **global** scans keyed on **`imdb_id`** (P345, `tt`-prefixed — unambiguous since IMDb IDs are globally unique, unlike the TMDB movie/tv namespace): the **spine** (imdb_id → RT slug + enwiki URL) and all **award statements** (QIDs only). Both filtered to our titles by imdb_id; **labels resolved separately** in batched `VALUES` queries (joining labels *inside* the statement scan is what times QLever out). One transaction (`crud.replace_wikidata_data`) writes `title_awards` (PK `(title_id, statement_id)`, `level ∈ {title,person}`, `subject`, `prestige`; full-replace of `source='wikidata'`), `title_wikidata_meta` (`wikidata_fetched_at` stamped for **every** attempted title = done-flag; a title with no awards still registers), and `title_rt` (RT slug, only when P1258 present, `source`-tagged for the future search-engine resolver). It's an **idempotent full refresh** (~15s), not incrementally resumable. RT *ratings* still go to `title_scores`, not `title_rt`.
- **Nominated-excluding-won** award dedup uses `MINUS` per subject+award (Wikidata logs some wins under both P166 and P1411; `MINUS` runs on QLever + WDQS alike). **Prestige family** is tagged by award-label prefix in Python (`parse.tag_prestige`), not QID paths — an unmatched label fails visibly as `NULL`. Counts/rollups are derived in pandas, not stored.
- **Wikipedia plot** is a **single async TextExtracts call per title** (`prop=extracts&explaintext&exsectionformat=wiki` → whole article as plain text → `wikipedia.slice_plot` cuts the `== Plot ==` section by heading level), landing in `title_plots.wikipedia_plot`. Stage B is **async/concurrent** (`rate_limiting.wikipedia.concurrency` + `AsyncRateGate`; Wikipedia throttles past ~20-30 req/s). `wikipedia_fetched_at`/`wikipedia_error` mirror the IMDb resume/error convention (a plotless article is a terminal success, error preserves existing text). *(The old two-call sections→section-HTML→`parsel` approach was 2 req/title and sequential — ~15h; this is ~10-20×.)*
- **Discover `min_rating` is a plain 0–10 float in `config.yaml`** (`tmdb_discover.rating.min_rating`), passed straight to TMDB's `vote_average.gte` — no scaling (the old 0–100 divide-by-10 rule is gone). Discover sort is always date-ascending. TV omits runtime/`include_video` params (they silently drop shows like Breaking Bad).
- **Discover date bounds** are passed explicitly (`date_gte=`, `date_lte=`), never via `**filters` (raises `TypeError`). `pop` them out of the filters dict first.
- **Bulk deletes:** use `ATTACH`/temp-table strategies, not big `IN (...)` clauses (SQLite bound-variable limit). Purge order is in `PROJECT_CONTEXT.md` §4.
- **Unmatched titles: accept the gap** — log to a side file, never guess a TMDB match.

## Do not
- Commit or read `*.db`, IMDb bulk `*.gz`, `.env`, or `logs/` into context (see `.claudeignore`).
- Reintroduce OMDb (abandoned for rate limits — IMDb bulk + GraphQL replaced it).
- Hardcode two people — always loop over the `people` list.