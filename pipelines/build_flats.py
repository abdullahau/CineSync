"""Rebuild the per-service flat snapshot DBs from cinesync.db.

Each schema file ATTACHes and (re)creates its own standalone flat DB under
data/ -- one per service, so each opens on its own in a single-file SQLite
viewer. Snapshots are denormalized read models: rebuilt wholesale, never
migrated.

Run from the repo root:
    uv run python pipelines/build_flats.py
"""

import os
import sqlite3
from importlib.resources import files

from cinesync.paths import DB_PATH, PROJECT_ROOT

SCHEMA_DIR = files("cinesync").joinpath("schemas")

# Order is irrelevant (each targets its own DB), but keep it service-grouped.
FLAT_SCHEMAS = [
    "flat_tmdb.sql",
    "flat_letterboxd.sql",
    "flat_imdb.sql",
    "flat_wiki.sql",
    "flat_rt.sql",
    "flat_coverage.sql",
]


def build_flats():
    # ATTACH paths inside the schema files are repo-root-relative ('data/...').
    os.chdir(PROJECT_ROOT)
    conn = sqlite3.connect(DB_PATH)
    try:
        for name in FLAT_SCHEMAS:
            sql = SCHEMA_DIR.joinpath(name).read_text()
            conn.executescript(sql)
            print(f"built {name}")
    finally:
        conn.close()


if __name__ == "__main__":
    build_flats()
