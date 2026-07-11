import random
import sqlite3
import time
from cinesync.paths import DB_PATH
from cinesync.ingestion.imdb import graphql, parse, bulk
from cinesync.ingestion import crud

# {variant: canonical}
GENRE_MAP = {
    "Sci-Fi": "Science Fiction",
    "Sci-Fi & Fantasy": "Science Fiction",
    "Reality-TV": "Reality",
}
MIN_DELAY, MAX_DELAY = 1.0, 2.5

conn = sqlite3.connect(DB_PATH)
id_map = bulk.load_title_id_map(conn)  # {imdb_id: title_id}: join + keep-filter

bulk.normalize_genres(conn, GENRE_MAP)  # rewrite EXISTING (TMDB) rows
bulk.run_ingestion(
    conn, id_map, genre_map=GENRE_MAP
)  # download → write → delete, both files
conn.close()

conn = sqlite3.connect(DB_PATH)
work = crud.titles_missing_imdb_enrichment(conn)  # [(title_id, imdb_id), ...]
print(f"{len(work)} titles to enrich (never fetched or last errored).")

session = graphql.new_session()
try:
    for i, (title_id, imdb_id) in enumerate(work, 1):
        res = graphql.fetch_title(session, imdb_id)
        rec = {"error": res["error"]} if "error" in res else parse.parse(res["title"])
        crud.upsert_imdb_enrichment(conn, title_id, rec, genre_map=GENRE_MAP)
        status = "ok" if "error" not in rec else f"ERR: {rec['error']}"
        print(f"[{i}/{len(work)}] {imdb_id} -> {status}")
        if i < len(work):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
finally:
    conn.close()

# --- Ratings-distribution pass (title_imdb_rating_dist) ---------------------
# Separate resume-safe work list: titles with a valid imdb_id and no
# distribution row yet. Independent of the enrichment pass above.
conn = sqlite3.connect(DB_PATH)
hist_work = crud.titles_missing_imdb_rating_dist(conn)  # [(title_id, imdb_id), ...]
print(f"{len(hist_work)} titles missing an IMDb ratings distribution.")

session = graphql.new_session()
try:
    for i, (title_id, imdb_id) in enumerate(hist_work, 1):
        res = graphql.fetch_ratings_histogram(session, imdb_id)
        if "error" in res:
            print(f"[{i}/{len(hist_work)}] {imdb_id} -> ERR: {res['error']}")
        else:
            rec = parse.parse_ratings_histogram(res["title"])
            wrote = crud.upsert_imdb_rating_dist(conn, title_id, rec)
            status = f"ok ({rec['total_votes']} votes)" if wrote else "no ratings"
            print(f"[{i}/{len(hist_work)}] {imdb_id} -> {status}")
        if i < len(hist_work):
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
finally:
    conn.close()
