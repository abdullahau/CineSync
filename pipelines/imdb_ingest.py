import sqlite3
import asyncio
import json
import time
from datetime import datetime, timezone

from cinesync.paths import DB_PATH, LOGS_DIR
from cinesync.config_loader import load_config
from cinesync.ingestion.imdb import graphql, parse, bulk
from cinesync.ingestion import crud
from cinesync.utils.net import AsyncRateGate

# {variant: canonical}
GENRE_MAP = {
    "Sci-Fi": "Science Fiction",
    "Sci-Fi & Fantasy": "Science Fiction",
    "Reality-TV": "Reality",
}

_cfg = load_config()
_rl = _cfg["rate_limiting"]["imdb"]
CONCURRENCY = _rl["concurrency"]
MIN_INTERVAL = _rl["min_interval"]
MAX_RETRIES = _rl["max_retries"]
TIMEOUT = _rl["timeout"]
STORYLINE_SHA256 = _cfg["apis"]["imdb"]["storyline_sha256"]
PROGRESS_EVERY = 100

FAILURE_LOG_PATH = LOGS_DIR / "imdb_enrichment_failures.jsonl"


def log_failure(
    title_id: str,
    imdb_id: str,
    stage: str,
    error_msg: str,
) -> None:
    """Append one failed sub-fetch to the JSONL side log. `stage` is
    'storyline' | 'histogram' | an exception class name (malformed response);
    same one-line-per-failure shape as letterboxd_ingest's log_failure."""
    entry = {
        "title_id": title_id,
        "imdb_id": imdb_id,
        "stage": stage,
        "error_message": error_msg[:300],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    with open(FAILURE_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


# ============================ bulk datasets =============================
conn = sqlite3.connect(DB_PATH)
id_map = bulk.load_title_id_map(conn)  # {imdb_id: title_id}: join + keep-filter

bulk.normalize_genres(conn, GENRE_MAP)  # rewrite EXISTING (TMDB) rows
bulk.run_ingestion(
    conn, id_map, genre_map=GENRE_MAP
)  # download → write → delete, both files
conn.close()

# ====================== GraphQL enrichment (async) ======================
# One batched request per title fetches storyline + ratings histogram together
# (see graphql.fetch_enrichment_batch). All coroutines run on the one event-loop
# thread, so the MAIN coroutine owns the single SQLite connection and does every
# write as results arrive -- no cross-thread writes. A shared AsyncRateGate caps
# the aggregate request rate; a Semaphore caps in-flight requests.


async def enrich():
    conn = sqlite3.connect(DB_PATH)
    work = crud.titles_missing_imdb_data(conn)  # [(title_id, imdb_id), ...]
    total = len(work)
    print(f"{total} titles need IMDb enrichment and/or a ratings distribution.")
    if total == 0:
        conn.close()
        return

    gate = AsyncRateGate(MIN_INTERVAL)
    sem = asyncio.Semaphore(CONCURRENCY)
    session = graphql.new_session()

    async def fetch_one(title_id, imdb_id):
        """Worker coroutine: gate-paced batched fetch, no DB access."""
        async with sem:
            await gate.wait()
            batch = await graphql.fetch_enrichment_batch(
                session,
                imdb_id,
                sha256=STORYLINE_SHA256,
                max_retries=MAX_RETRIES,
                timeout=TIMEOUT,
            )
            return title_id, imdb_id, batch

    done = 0
    story_ok = story_err = hist_ok = hist_err = 0
    start = time.monotonic()
    tasks = [asyncio.create_task(fetch_one(t, i)) for t, i in work]

    try:
        for coro in asyncio.as_completed(tasks):
            title_id, imdb_id, batch = await coro
            done += 1
            try:
                # storyline -> title_plots / genres / imdb keywords. upsert_imdb_
                # enrichment's own error path records imdb_error and preserves text.
                s = batch["storyline"]
                srec = (
                    {"error": s["error"]} if "error" in s else parse.parse(s["title"])
                )
                crud.upsert_imdb_enrichment(conn, title_id, srec, genre_map=GENRE_MAP)
                if "error" in srec:
                    story_err += 1
                    log_failure(title_id, imdb_id, "storyline", srec["error"])
                else:
                    story_ok += 1

                # histogram -> title_imdb_rating_dist (skips titles with no ratings)
                h = batch["histogram"]
                if "error" in h:
                    hist_err += 1
                    log_failure(title_id, imdb_id, "histogram", h["error"])
                else:
                    crud.upsert_imdb_rating_dist(
                        conn, title_id, parse.parse_ratings_histogram(h["title"])
                    )
                    hist_ok += 1
            except Exception as exc:
                # one malformed response must not sink a multi-hour run; the
                # title simply stays on the resume list for the next pass.
                story_err += 1
                hist_err += 1
                log_failure(title_id, imdb_id, type(exc).__name__, str(exc))
                print(f"  ! {imdb_id}: {type(exc).__name__}: {exc}")
                continue

            if done % PROGRESS_EVERY == 0 or done == total:
                elapsed = time.monotonic() - start
                rate = done / elapsed if elapsed else 0
                eta_min = (total - done) / rate / 60 if rate else float("inf")
                print(
                    f"[{done}/{total}] story ok={story_ok} err={story_err} | "
                    f"hist ok={hist_ok} err={hist_err} | "
                    f"{rate:.1f} titles/s eta={eta_min:.0f}min"
                )
    finally:
        conn.close()
        await session.close()

    print(
        f"\nDone. story ok={story_ok} err={story_err} | "
        f"hist ok={hist_ok} err={hist_err} out of {total}."
    )
    if story_err or hist_err:
        print(f"Failure details: {FAILURE_LOG_PATH}")


if __name__ == "__main__":
    asyncio.run(enrich())
