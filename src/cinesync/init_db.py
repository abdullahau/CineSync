"""
Phase 0: initialize the CineSync SQLite database from schema.sql.

Run once:
    python src/init_db.py

Creates data/cinesync.db. Will NOT overwrite an existing db -- delete
data/cinesync.db yourself first if you want a clean rebuild (e.g.
after editing schema.sql).
"""

import sqlite3
from importlib.resources import files
from cinesync.paths import DATA_DIR

DB_PATH = DATA_DIR / "cinesync.db"
SCHEMA_PATH = files("cinesync").joinpath("schema.sql")


def init_db():
    if DB_PATH.exists():
        print(f"{DB_PATH} already exists. Delete it first if you want a fresh start.")
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    with open(SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Created {DB_PATH} with tables defined in {SCHEMA_PATH.name}")


if __name__ == "__main__":
    init_db()
