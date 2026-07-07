import sqlite3
from cinesync.paths import DB_PATH
from cinesync.ingestion.imdb_dataset import (
    load_title_id_map,
    run_ingestion,
    normalize_genres,
)

GENRE_MAP = {
    "Sci-Fi & Fantasy": "Sci-Fi",  # {variant: canonical}
    "Reality-TV": "Reality",
}

conn = sqlite3.connect(DB_PATH)
id_map = load_title_id_map(conn)  # {imdb_id: title_id}: join + keep-filter

normalize_genres(conn, GENRE_MAP)  # rewrite EXISTING (TMDB) rows
run_ingestion(
    conn, id_map, genre_map=GENRE_MAP
)  # download → write → delete, both files
conn.close()
