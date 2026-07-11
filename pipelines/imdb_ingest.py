import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from cinesync.paths import DB_PATH
from cinesync.ingestion.imdb import graphql, parse, bulk
from cinesync.ingestion import crud

# {variant: canonical}
GENRE_MAP = {
    "Sci-Fi": "Science Fiction",
    "Sci-Fi & Fantasy": "Science Fiction",
    "Reality-TV": "Reality",
}

MAX_WORKERS = 5          # worker threads: network-only, one curl_cffi session each
REQ_PER_SEC = 8          # global cap; backoff in graphql.* handles 403/429/5xx
MIN_INTERVAL = 1.0 / REQ_PER_SEC
PROGRESS_EVERY = 100

# ============================ bulk datasets =============================
conn = sqlite3.connect(DB_PATH)
id_map = bulk.load_title_id_map(conn)  # {imdb_id: title_id}: join + keep-filter

bulk.normalize_genres(conn, GENRE_MAP)  # rewrite EXISTING (TMDB) rows
bulk.run_ingestion(
    conn, id_map, genre_map=GENRE_MAP
)  # download → write → delete, both files
conn.close()

# ===================== GraphQL enrichment (threaded) ====================
# One batched request per title fetches storyline + ratings histogram together
# (see graphql.fetch_enrichment_batch). Worker threads do network only; the
# MAIN thread owns the single SQLite connection and does every write. A global
# token bucket paces the aggregate request rate regardless of worker count.

_rate_lock = threading.Lock()
_next_slot = 0.0


def rate_limit():
    """Reserve the next evenly-spaced request slot (thread-safe), then sleep to
    it OUTSIDE the lock -- caps the aggregate rate at REQ_PER_SEC across all
    workers without serializing the reservation."""
    global _next_slot
    with _rate_lock:
        slot = max(time.monotonic(), _next_slot)
        _next_slot = slot + MIN_INTERVAL
    wait = slot - time.monotonic()
    if wait > 0:
        time.sleep(wait)


def get_session(thread_local):
    if not hasattr(thread_local, "session"):
        thread_local.session = graphql.new_session()
    return thread_local.session


def fetch_only(imdb_id, thread_local):
    """Runs in a worker thread: rate-limited batched fetch, no DB access."""
    rate_limit()
    return graphql.fetch_enrichment_batch(get_session(thread_local), imdb_id)


conn = sqlite3.connect(DB_PATH)
work = crud.titles_missing_imdb_data(conn)  # [(title_id, imdb_id), ...]
total = len(work)
print(f"{total} titles need IMDb enrichment and/or a ratings distribution.")

thread_local = threading.local()
done = 0
story_ok = story_err = hist_ok = hist_err = 0
start = time.monotonic()

try:
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(fetch_only, imdb_id, thread_local): (title_id, imdb_id)
            for title_id, imdb_id in work
        }
        for fut in as_completed(futures):
            title_id, imdb_id = futures.pop(fut)
            done += 1
            try:
                batch = fut.result()

                # storyline -> title_plots / genres / imdb keywords. upsert_imdb_
                # enrichment's own error path records imdb_error and preserves text.
                s = batch["storyline"]
                srec = {"error": s["error"]} if "error" in s else parse.parse(s["title"])
                crud.upsert_imdb_enrichment(conn, title_id, srec, genre_map=GENRE_MAP)
                if "error" in srec:
                    story_err += 1
                else:
                    story_ok += 1

                # histogram -> title_imdb_rating_dist (skips titles with no ratings)
                h = batch["histogram"]
                if "error" in h:
                    hist_err += 1
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
