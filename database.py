"""
SQLite database — users, preferences, stats.
"""

import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(os.getenv("DB_PATH", str(Path(__file__).parent / "bot_data.db")))


class Database:
    def __init__(self):
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                seniority   TEXT,
                keyword     TEXT,
                is_active   INTEGER DEFAULT 1,
                joined_at   TEXT DEFAULT (datetime('now')),
                updated_at  TEXT DEFAULT (datetime('now'))
            );
        """)
        self.conn.commit()

    # ── write ─────────────────────────────────────────────────────────────

    def upsert_user(self, user_id: int, username: str):
        self.conn.execute("""
            INSERT INTO users (user_id, username)
            VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                is_active = 1,
                updated_at = datetime('now')
        """, (user_id, username))
        self.conn.commit()

    def set_preferences(self, user_id: int, seniority: str, keyword: str):
        self.conn.execute("""
            UPDATE users
            SET seniority = ?, keyword = ?, updated_at = datetime('now')
            WHERE user_id = ?
        """, (seniority, keyword, user_id))
        self.conn.commit()

    def set_active(self, user_id: int, active: bool):
        self.conn.execute("""
            UPDATE users SET is_active = ?, updated_at = datetime('now')
            WHERE user_id = ?
        """, (1 if active else 0, user_id))
        self.conn.commit()

    # ── read ──────────────────────────────────────────────────────────────

    def get_preferences(self, user_id: int) -> tuple | None:
        row = self.conn.execute(
            "SELECT seniority, keyword FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row[0] and row[1]:
            return row
        return None

    def is_active(self, user_id: int) -> bool:
        row = self.conn.execute(
            "SELECT is_active FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row[0])

    def get_active_users(self) -> list[tuple]:
        """Returns list of (user_id, seniority, keyword) for active users with prefs."""
        return self.conn.execute("""
            SELECT user_id, seniority, keyword FROM users
            WHERE is_active = 1 AND seniority IS NOT NULL AND keyword IS NOT NULL
        """).fetchall()

    # ── admin stats ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        total = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = self.conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]

        top_keywords = self.conn.execute("""
            SELECT keyword, COUNT(*) as cnt FROM users
            WHERE keyword IS NOT NULL
            GROUP BY LOWER(keyword)
            ORDER BY cnt DESC
            LIMIT 5
        """).fetchall()

        seniority_dist = self.conn.execute("""
            SELECT seniority, COUNT(*) as cnt FROM users
            WHERE seniority IS NOT NULL
            GROUP BY seniority
            ORDER BY cnt DESC
        """).fetchall()

        return {
            "total": total,
            "active": active,
            "top_keywords": top_keywords,
            "seniority_dist": seniority_dist,
        }
