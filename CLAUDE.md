# CLAUDE.md — CineSync

Operating brief for Claude Code. This is the lean, every-session file; the full design history, schema, and rationale live in **`PROJECT_CONTEXT.md`** — read that before any non-trivial change.

## What this is
CineSync is a **local, notebook/script-based movie & TV recommendation system** that learns taste from Letterboxd ratings. SQLite (`cinesync.db`) is the relational source of truth; pandas is the analysis layer; orchestration lives in Jupyter notebooks. It's also a learning vehicle for DS/ML fundamentals, so favor inspectable code over black boxes.

## Environment & commands
- Package manager is **`uv`** (not pip/conda). Editable install.
  - Install/sync deps: `uv sync`
  - Run anything needing env vars (TMDB key, etc.): `uv run --env-file .env <cmd>`
  - Initialize the DB from schema: `uv run cinesync-init-db` (won't overwrite an existing DB)
  - Run a TMDB discover sweep: `uv run --env-file .env python notebooks/tmdb_ingest.py` (loop lives in the notebook script; parameterized by `config.yaml`'s `tmdb_discover` block)
- Python **≥3.11**. `numba>=0.59` is pinned to keep `uv sync` from failing on a 3.12 resolver conflict via umap-learn — don't unpin it.
- Tests: _(no suite yet — don't invent a `pytest` command; verify logic by running it in a scratch/synthetic SQLite DB instead, see Working style)._

## Repo layout
- `src/cinesync/` — canonical single-purpose functions. Notebooks import `from cinesync.X import Y`.
  - Top level: `paths.py` (`DATA_DIR`, `LOGS_DIR`, `TMP_DIR`, `NOTEBOOKS_DIR`, `DB_PATH`, `DB_SCHEMA_PATH`), `config_loader.py`, `init_db.py`, `recency.py`, `critic_score.py`, `utils/net.py`
  - `schemas/` — `schema.sql` (canonical DB schema), `table_flat.sql`
  - `ingestion/` — **all ingestion + CRUD lives here now:**
    - `tmdb_parser.py`, `tmdb_fetch.py` (discover/details/recommendations primitives), `date_windows.py`, `tmdb_popularity.py` (daily-export popularity)
    - `db_crud.py` — **all CRUD** (TMDB titles, recommendation links, Letterboxd stats, IMDb enrichment)
    - `imdb_dataset.py` (bulk TSV), `imdb_fetch.py` + `imdb_parser.py` (GraphQL scraper)
- Orchestration loops live in `notebooks/` as plain `.py` scripts (`tmdb_ingest.py`, `imdb_ingest.py`, `letterboxd_ingest.py` — the Letterboxd async scraper lives here, not in `src/`) plus analysis notebooks; `src/` stays loop-free.
- **Retired modules** (don't reference — folded elsewhere): `discover.py`/`sync_pipeline.py`→`tmdb_fetch.py`; `tmdb_export_ingest.py`→`tmdb_popularity.py`; `imdb_ingest.py`(src)→`imdb_dataset.py`; `tmdb_sweep.py`/`letterboxd_scrape.py`→notebooks.
- `cinesync_flat.db` (`titles_flat`) is a **rebuilt-per-session** denormalized snapshot — regenerate it via the `ATTACH DATABASE` block, never migrate it separately.

## Working style (how Abdullah wants changes made)
- **Explicit over clever.** No auto-detection, CLI wrappers, or speculative abstraction. Surface design decisions in the response; don't apply them silently.
- **Verify before presenting.** For any DB/logic change, run it against an in-memory or synthetic SQLite DB first and show it works. This project has a history of silent-failure bugs — assume they exist.
- **Re-read files, don't trust memory.** Abdullah edits between sessions. Open the actual file before editing; don't reconstruct signatures from prior context or from `PROJECT_CONTEXT.md`.
- **Transformation logic in pandas, not SQL.** Keep joins/aggregations visible in the notebook layer; `src/` functions take a DB connection and return DataFrames.
- **Flag bugs by severity.** Prefer a small, reviewable diff; propose, don't auto-apply large rewrites.

## Facts that bite (silent-failure watchlist)
- **SQLite is single-writer.** In the threaded discovery loop, worker threads do network-only work; the **main thread owns the one connection** and does every write + all shared-set mutation. Never write from workers.
- **`title_id` = `movie_<tmdb_id>` / `tv_<tmdb_id>`.** TMDB movie/TV IDs share a numeric namespace — this is why Letterboxd routing is **IMDb-ID-first** with a TMDB-ID fallback (TMDB fallback resolves movies only).
- **IMDb IDs** are `tt`-prefixed strings; bare digits silently break joins. Empty-string `imdb_id`/`wikidata_id`/`tmdb_overview` must be NULL, not `''`.
- **`title_keywords` PK is `(title_id, keyword, source)`** — keyword replace is **per-source** so a TMDB full-replace can't wipe IMDb keywords.
- **Genres are sourceless**, converged via the canonical `GENRE_MAP` (`Sci-Fi`/`Sci-Fi & Fantasy` → `Science Fiction`, `Reality-TV` → `Reality`).
- **Schema convention:** column-level `NOT NULL` + a separate table-level `PRIMARY KEY (...)`, not inline `TEXT PRIMARY KEY`. Match sibling tables.
- **Scores table is `title_scores`** (renamed from `external_scores`), sources `{rt_critic, rt_audience, imdb_rating, tmdb_rating}`. Letterboxd rating is NOT here — it's in `title_letterboxd_stats`.
- **Discover `min_rating` is a plain 0–10 float in `config.yaml`** (`tmdb_discover.rating.min_rating`), passed straight to TMDB's `vote_average.gte` — no scaling (the old 0–100 divide-by-10 rule is gone). Discover sort is always date-ascending. TV omits runtime/`include_video` params (they silently drop shows like Breaking Bad).
- **Discover date bounds** are passed explicitly (`date_gte=`, `date_lte=`), never via `**filters` (raises `TypeError`). `pop` them out of the filters dict first.
- **Bulk deletes:** use `ATTACH`/temp-table strategies, not big `IN (...)` clauses (SQLite bound-variable limit). Purge order is in `PROJECT_CONTEXT.md` §4.
- **Unmatched titles: accept the gap** — log to a side file, never guess a TMDB match.

## Do not
- Commit or read `*.db`, IMDb bulk `*.gz`, `.env`, or `logs/` into context (see `.claudeignore`).
- Reintroduce OMDb (abandoned for rate limits — IMDb bulk + GraphQL replaced it).
- Hardcode two people — always loop over the `people` list.