import random
import sqlite3
import time
from cinesync.paths import DB_PATH
from cinesync.ingestion.imdb_fetch import new_session, fetch_title
from cinesync.ingestion.imdb_parser import parse
from cinesync.ingestion.db_crud import (
    titles_missing_imdb_enrichment,
    upsert_imdb_enrichment,
)
from cinesync.ingestion.imdb_dataset import (
    load_title_id_map,
    run_ingestion,
    normalize_genres,
)

# {variant: canonical}
GENRE_MAP = {
    "Sci-Fi": "Science Fiction",
    "Sci-Fi & Fantasy": "Science Fiction",
    "Reality-TV": "Reality",
}
MIN_DELAY, MAX_DELAY = 1.0, 2.5

conn = sqlite3.connect(DB_PATH)
id_map = load_title_id_map(conn)  # {imdb_id: title_id}: join + keep-filter

normalize_genres(conn, GENRE_MAP)  # rewrite EXISTING (TMDB) rows
run_ingestion(
    conn, id_map, genre_map=GENRE_MAP
)  # download → write → delete, both files
conn.close()

conn = sqlite3.connect(DB_PATH)
work = titles_missing_imdb_enrichment(conn)  # [(title_id, imdb_id), ...]
print(f"{len(work)} titles to enrich (never fetched or last errored).")

session = new_session()
try:
    for i, (title_id, imdb_id) in enumerate(work, 1):
        res = fetch_title(session, imdb_id)
        rec = {"error": res["error"]} if "error" in res else parse(res["title"])
        upsert_imdb_enrichment(conn, title_id, rec, genre_map=GENRE_MAP)
        status = "ok" if "error" not in rec else f"ERR: {rec['error']}"
        print(f"[{i}/{len(work)}] {imdb_id} -> {status}")
        if i < len(work):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
finally:
    conn.close()
