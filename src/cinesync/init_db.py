import sqlite3
from cinesync.paths import DB_SCHEMA_PATH, DB_PATH


def init_db():
    if DB_PATH.exists():
        print(f"{DB_PATH} already exists. Delete it first if you want a fresh start.")
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    with open(DB_SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()
    conn.close()
    print(f"Created {DB_PATH} with tables defined in {DB_SCHEMA_PATH.name}")


if __name__ == "__main__":
    init_db()
