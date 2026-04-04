"""SQLite helpers for users, adventures, and save slots."""

import sqlite3

from config import DATABASE_PATH


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DATABASE_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS adventures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                game_file TEXT NOT NULL,
                name TEXT NOT NULL,
                session_id TEXT,
                active_slot INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_played TEXT
            );

            CREATE TABLE IF NOT EXISTS save_slots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                adventure_id INTEGER NOT NULL REFERENCES adventures(id),
                slot INTEGER NOT NULL,
                data TEXT NOT NULL,
                saved_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(adventure_id, slot)
            );
            """
        )
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(adventures)").fetchall()
        }
        if cols and "active_slot" not in cols:
            conn.execute(
                "ALTER TABLE adventures ADD COLUMN active_slot INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()
    finally:
        conn.close()
