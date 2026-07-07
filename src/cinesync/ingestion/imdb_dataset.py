"""
IMDb bulk-dataset ingestion -- writes straight into cinesync.db, no staging DB.

Per file: download -> stream-read -> write into cinesync -> delete, before
moving on. Nothing large is held in memory: the .gz streams to disk in chunks,
is read back line by line, and rows are written in bounded batches.

  title.ratings.tsv.gz  -> title_scores  (source='imdb_rating', 0-10 -> 0-100)
  title.basics.tsv.gz   -> title_genres  (genres split on comma, deduped)

The tconst -> title_id join the old staging+merge did in SQL now happens in
Python via id_map = {imdb_id: title_id} loaded from titles. A tconst not in the
map is skipped (that is also the "keep only my titles" filter). Fields are '\\N'
for null.

Source: https://datasets.imdbws.com/  (personal / non-commercial use)
Schema definitions: https://developer.imdb.com/non-commercial-datasets/

GENRE VOCABULARY
----------------
TMDB and IMDb name genres differently (TMDB 'Sci-Fi & Fantasy' / 'Science
Fiction'; IMDb 'Sci-Fi'). Whether two labels are the same genre is your call.
genre_map = {variant: canonical} is direction-agnostic and applied to incoming
IMDb genres; normalize_genres() applies the same map to your EXISTING (TMDB)
rows. Use one shared map and both vocabularies converge. Default None = no
rewriting.
"""

import gzip
import requests
from cinesync.paths import TMP_DIR

BASE_URL = "https://datasets.imdbws.com/"


def load_title_id_map(conn):
    rows = conn.execute(
        "SELECT imdb_id, title_id FROM titles "
        "WHERE imdb_id IS NOT NULL AND imdb_id != ''"
    ).fetchall()
    return {imdb_id: title_id for imdb_id, title_id in rows}


def _cast(raw, cast):
    if raw == "\\N" or raw == "":
        return None
    if cast is str:
        return raw
    try:
        return cast(raw)
    except ValueError, TypeError:
        return None


def download_dataset(filename, session, tmp_dir=TMP_DIR, timeout=60):
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / filename
    with session.get(BASE_URL + filename, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        with open(tmp_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                fh.write(chunk)
    return tmp_path


def _stream_tsv(
    conn, gz_path, needed_cols, emit, sql, batch_size=50_000, progress_every=2_000_000
):
    """The shared skeleton: open, header-map `needed_cols` (fails fast if IMDb
    drops one), stream lines, skip malformed, batch the rows `emit` yields,
    commit. `emit(fields, idx) -> iterable of tuples` is the ONLY per-file part
    -- it may yield 0 rows (ratings, filtered/missing) or many (genre fan-out).
    Returns (rows_changed, malformed_skipped)."""
    before = conn.total_changes
    skipped = read = 0
    batch = []
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        pos = {name: i for i, name in enumerate(header)}
        idx = {name: pos[name] for name in needed_cols}  # KeyError if column gone
        n_expected = len(header)
        for line in f:
            read += 1
            if progress_every and read % progress_every == 0:
                print(f"    ...{read:,} lines read")
            fields = line.rstrip("\n").split("\t")
            if len(fields) != n_expected:
                skipped += 1
                continue
            batch.extend(emit(fields, idx))
            if len(batch) >= batch_size:
                conn.executemany(sql, batch)
                conn.commit()
                batch.clear()
        if batch:
            conn.executemany(sql, batch)
            conn.commit()
    return conn.total_changes - before, skipped


_RATINGS_SQL = (
    "INSERT INTO title_scores (title_id, source, score, sample_size, date_pulled) "
    "VALUES (?, 'imdb_rating', ?, ?, datetime('now')) "
    "ON CONFLICT(title_id, source) DO UPDATE SET "
    "score=excluded.score, sample_size=excluded.sample_size, date_pulled=excluded.date_pulled"
)
_GENRES_SQL = "INSERT OR IGNORE INTO title_genres (title_id, genre) VALUES (?, ?)"


def ingest_ratings(conn, gz_path, id_map, **kw):
    """1:1 upsert into title_scores; averageRating*10 -> 0-100."""

    def emit(fields, idx):
        title_id = id_map.get(fields[idx["tconst"]])
        if title_id is None:
            return ()
        avg = _cast(fields[idx["averageRating"]], float)
        if avg is None:
            return ()
        return ((title_id, round(avg * 10.0, 1), _cast(fields[idx["numVotes"]], int)),)

    return _stream_tsv(
        conn, gz_path, ("tconst", "averageRating", "numVotes"), emit, _RATINGS_SQL, **kw
    )


def ingest_genres(conn, gz_path, id_map, genre_map=None, **kw):
    """1:N fan-out into title_genres; comma-split, mapped, deduped by PK."""
    genre_map = genre_map or {}

    def emit(fields, idx):
        title_id = id_map.get(fields[idx["tconst"]])
        if title_id is None:
            return
        raw = _cast(fields[idx["genres"]], str)
        if not raw:
            return
        for g in raw.split(","):
            g = g.strip()
            if g:
                yield (title_id, genre_map.get(g, g))

    return _stream_tsv(conn, gz_path, ("tconst", "genres"), emit, _GENRES_SQL, **kw)


def _load_genre_map(conn, genre_map):
    conn.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _genre_map "
        "(variant TEXT PRIMARY KEY, canonical TEXT)"
    )
    conn.execute("DELETE FROM _genre_map")
    if genre_map:
        conn.executemany(
            "INSERT INTO _genre_map (variant, canonical) VALUES (?, ?)",
            list(genre_map.items()),
        )


def normalize_genres(conn, genre_map):
    """Rewrite genres already in title_genres per {variant: canonical}.
    Direction-agnostic; rewrite collisions dedupe via UPDATE OR REPLACE.
    Returns rows changed."""
    if not genre_map:
        return 0
    _load_genre_map(conn, genre_map)
    before = conn.total_changes
    conn.execute(
        """
        UPDATE OR REPLACE title_genres
        SET genre = (SELECT canonical FROM _genre_map WHERE variant = title_genres.genre)
        WHERE genre IN (SELECT variant FROM _genre_map)
        """
    )
    conn.commit()
    return conn.total_changes - before


def run_ingestion(conn, id_map, genre_map=None, batch_size=50_000):
    """Download -> ingest into cinesync -> delete, ratings then basics.
    Does NOT normalize existing rows -- call normalize_genres() for that."""
    session = requests.Session()
    for filename, fn in (
        (
            "title.ratings.tsv.gz",
            lambda p: ingest_ratings(conn, p, id_map, batch_size=batch_size),
        ),
        (
            "title.basics.tsv.gz",
            lambda p: ingest_genres(
                conn, p, id_map, genre_map=genre_map, batch_size=batch_size
            ),
        ),
    ):
        print(f"Downloading {filename} ...")
        p = download_dataset(filename, session)
        try:
            changed, skipped = fn(p)
        finally:
            p.unlink(missing_ok=True)
        print(
            f"  {changed} rows changed"
            + (f", {skipped} malformed skipped" if skipped else "")
        )
