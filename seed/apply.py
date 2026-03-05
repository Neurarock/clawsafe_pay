#!/usr/bin/env python3
"""
Apply SQL seed data to a SQLite database.

Usage (via environment variables):
    SEED_DB_PATH=/path/to/db  SEED_SQL_PATH=/path/to/seed.sql  python seed/apply.py

The script is idempotent — tables use CREATE IF NOT EXISTS and rows use
INSERT OR IGNORE, so re-running against an existing DB is safe.
"""
import os
import sqlite3
import sys


def main() -> None:
    db_path = os.environ.get("SEED_DB_PATH", "")
    sql_path = os.environ.get("SEED_SQL_PATH", "")

    if not db_path or not sql_path:
        # Seeding not configured — skip silently
        return

    if not os.path.exists(sql_path):
        print(f"[seed] SQL file not found, skipping: {sql_path}")
        return

    # Ensure parent directory exists (first run in fresh container)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    print(f"[seed] Applying {sql_path} → {db_path} …")
    conn = sqlite3.connect(db_path)
    try:
        with open(sql_path) as f:
            conn.executescript(f.read())
        # Quick sanity check
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        total = 0
        for t in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM [{t}]").fetchone()[0]
            total += count
            print(f"[seed]   {t}: {count} rows")
        print(f"[seed] Done — {len(tables)} tables, {total} rows total.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
