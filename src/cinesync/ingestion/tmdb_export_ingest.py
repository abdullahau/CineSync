"""
TMDB daily ID export ingestion -- builds title_buzz_snapshots
(source='tmdb_popularity') for every title already in your `titles`
table, using TMDB's bulk daily export files.

Every run sweeps every date between watermark (MAX(snapshot_date)
already in title_buzz_snapshots) and today, checking against your
COMPLETE CURRENT titles table each time.
"""

import gzip
import json
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path
from cinesync.paths import DATA_DIR

import requests

EXPORT_RETENTION_DAYS = 90  # TMDB's documented retention window
TMP_DIR = DATA_DIR / "tmdb_popularity"


def url_for(content_type: str, d: date) -> str:
    """content_type: 'movie' or 'tv'. Date format is MM_DD_YYYY -- confirmed exact format."""
    name = "movie_ids" if content_type == "movie" else "tv_series_ids"
    return f"https://files.tmdb.org/p/exports/{name}_{d.strftime('%m_%d_%Y')}.json.gz"


def watermark_date(conn: sqlite3.Connection) -> date:
    """
    Last successfully-processed date, derived from the data itself --
    nothing to keep in sync. First-ever run (empty table) falls back
    to the oldest date TMDB still has available.
    """
    row = conn.execute(
        "SELECT MAX(snapshot_date) FROM title_buzz_snapshots WHERE source = 'tmdb_popularity'"
    ).fetchone()
    if row[0] is None:
        return date.today() - timedelta(days=EXPORT_RETENTION_DAYS)
    return date.fromisoformat(row[0])


def known_title_ids(conn: sqlite3.Connection, content_type: str) -> set:
    rows = conn.execute(
        "SELECT title_id FROM titles WHERE content_type = ?", (content_type,)
    ).fetchall()
    return {r[0] for r in rows}


def download_export_file(content_type: str, d: date, session, tmp_dir: Path = TMP_DIR):
    """
    Returns the local path to the downloaded .gz file, or None if TMDB
    returned 404 (file not yet published today, or past the 90-day
    retention window).
    """
    url = url_for(content_type, d)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = tmp_dir / f"{content_type}_{d.isoformat()}.json.gz"
    response = session.get(url, stream=True, timeout=60)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    with open(tmp_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            f.write(chunk)
    return tmp_path


def ingest_export_file(
    conn: sqlite3.Connection,
    content_type: str,
    snapshot_date: str,
    gz_path: Path,
    known_ids: set,
) -> int:
    """
    Streams the gz file line by line -- never loads the full
    decompressed content into memory at once. Keeps only entries whose
    title_id is already in your titles table. Safe to call twice on
    the same file/date: INSERT OR IGNORE relies on title_buzz_snapshots'
    (title_id, source, snapshot_date) primary key for idempotency.
    """
    title_prefix = "movie_" if content_type == "movie" else "tv_"
    inserted = 0
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            title_id = f"{title_prefix}{entry['id']}"
            if title_id not in known_ids:
                continue
            cur = conn.execute(
                "INSERT OR IGNORE INTO title_buzz_snapshots (title_id, source, snapshot_date, value) "
                "VALUES (?, 'tmdb_popularity', ?, ?)",
                (title_id, snapshot_date, entry["popularity"]),
            )
            inserted += cur.rowcount
    conn.commit()
    return inserted


def process_one_file(
    conn, content_type, d: date, session, known_ids, pace_seconds: float = 1.0
):
    """Download -> ingest -> delete, in that order, before moving to the next date."""
    gz_path = download_export_file(content_type, d, session)
    if gz_path is None:
        return -1
    inserted = ingest_export_file(conn, content_type, d.isoformat(), gz_path, known_ids)
    gz_path.unlink()
    time.sleep(pace_seconds)
    return inserted


def run_ingestion(
    conn: sqlite3.Connection,
    content_types=("movie", "tv"),
    export_start: str = "watermark",
):
    """
    export_start:
      "watermark" (default) -- resume from the day after the last
          successfully-processed date, derived from the data itself.
      "full" -- force a sweep of the entire ~90-day retention window,
          even for dates already covered.
    """
    if export_start == "watermark":
        start = watermark_date(conn) + timedelta(days=1)
    elif export_start == "full":
        start = date.today() - timedelta(days=EXPORT_RETENTION_DAYS)
    else:
        raise ValueError(
            f"export_start must be 'watermark' or 'full', got {export_start!r}"
        )

    earliest_available = date.today() - timedelta(days=EXPORT_RETENTION_DAYS)
    start = max(start, earliest_available)
    end = date.today()

    if start > end:
        print("Already up to date -- nothing to process.")
        return

    known_ids_by_type = {ct: known_title_ids(conn, ct) for ct in content_types}
    session = requests.Session()

    d = start
    while d <= end:
        for content_type in content_types:
            known_ids = known_ids_by_type[content_type]
            if not known_ids:
                continue  # nothing in your titles table of this content_type yet
            result = process_one_file(conn, content_type, d, session, known_ids)
            if result == -1:
                print(
                    f"{content_type} export for {d.isoformat()} not available yet -- stopping here."
                )
                return
            print(f"{d.isoformat()} [{content_type}]: {result} snapshot(s) recorded")
        d += timedelta(days=1)
