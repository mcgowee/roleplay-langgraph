"""SQLite helpers for users, adventures, save slots, and game content."""

import json
import logging
import os
import sqlite3

from config import DATABASE_PATH, GAMES_DIR

logger = logging.getLogger(__name__)


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

            CREATE TABLE IF NOT EXISTS game_content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                genre TEXT DEFAULT '',
                game_json TEXT NOT NULL,
                source_id INTEGER REFERENCES game_content(id),
                original_author_id INTEGER REFERENCES users(id),
                is_public BOOLEAN DEFAULT 0,
                is_global BOOLEAN DEFAULT 0,
                play_count INTEGER DEFAULT 0,
                catalog_file_stem TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
        cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(adventures)").fetchall()
        }
        if "game_content_id" in cols:
            pass  # already migrated
        elif cols:
            conn.execute(
                "ALTER TABLE adventures ADD COLUMN game_content_id INTEGER REFERENCES game_content(id)"
            )
        gc_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(game_content)").fetchall()
        }
        if gc_cols and "catalog_file_stem" not in gc_cols:
            conn.execute(
                "ALTER TABLE game_content ADD COLUMN catalog_file_stem TEXT"
            )
        conn.commit()
        backfill_catalog_file_stems(conn, str(GAMES_DIR))
    finally:
        conn.close()


def backfill_catalog_file_stems(conn: sqlite3.Connection, games_dir: str) -> None:
    """Set catalog_file_stem for global catalog rows from on-disk JSON filenames."""
    if not os.path.isdir(games_dir):
        return
    for name in os.listdir(games_dir):
        if not name.endswith(".json"):
            continue
        stem = name[: -len(".json")]
        path = os.path.join(games_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        title = (data.get("title") or stem).strip()
        if not title:
            continue
        conn.execute(
            """
            UPDATE game_content
            SET catalog_file_stem = ?
            WHERE is_global = 1 AND title = ?
              AND (catalog_file_stem IS NULL OR catalog_file_stem = '')
            """,
            (stem, title),
        )
    conn.commit()


def seed_global_games(games_dir: str) -> None:
    """Insert catalog games from JSON files when no global rows exist."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM game_content WHERE is_global = 1"
        ).fetchone()
        if row and row["c"] > 0:
            return

        count = 0
        if not os.path.isdir(games_dir):
            logger.warning("seed_global_games: games_dir missing: %s", games_dir)
            return

        for name in sorted(os.listdir(games_dir)):
            if not name.endswith(".json"):
                continue
            path = os.path.join(games_dir, name)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as e:
                logger.error("seed_global_games: skip %s: %s", name, e)
                continue

            title = data.get("title") or name.replace(".json", "")
            description = data.get("description", "") or ""
            genre = data.get("genre", "") or ""
            blob = json.dumps(data, ensure_ascii=False)

            stem = name[: -len(".json")]
            conn.execute(
                """
                INSERT INTO game_content (
                    user_id, title, description, genre, game_json,
                    source_id, original_author_id, is_public, is_global, play_count,
                    catalog_file_stem
                )
                VALUES (NULL, ?, ?, ?, ?, NULL, NULL, 1, 1, 0, ?)
                """,
                (title, description, genre, blob, stem),
            )
            count += 1

        conn.commit()
        logger.info("Seeded %d global game(s) from %s", count, games_dir)
    finally:
        conn.close()
