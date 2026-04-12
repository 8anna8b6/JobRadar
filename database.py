"""
SQLite database — users, multi-select preferences, stats.
"""

import os
import json
import sqlite3
import logging
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
                roles       TEXT,
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
                username   = excluded.username,
                is_active  = 1,
                updated_at = datetime('now')
        """, (user_id, username))
        self.conn.commit()

    def set_preferences(self, user_id: int, seniority_json: str, roles_json: str):
        """seniority_json and roles_json are JSON-encoded lists."""
        self.conn.execute("""
            UPDATE users
            SET seniority = ?, roles = ?, updated_at = datetime('now')
            WHERE user_id = ?
        """, (seniority_json, roles_json, user_id))
        self.conn.commit()

    def set_active(self, user_id: int, active: bool):
        self.conn.execute("""
            UPDATE users SET is_active = ?, updated_at = datetime('now')
            WHERE user_id = ?
        """, (1 if active else 0, user_id))
        self.conn.commit()

    # ── read ──────────────────────────────────────────────────────────────

    def get_preferences(self, user_id: int) -> tuple | None:
        """Returns (seniorities: list, roles: list) or None."""
        row = self.conn.execute(
            "SELECT seniority, roles FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row[0] and row[1]:
            return json.loads(row[0]), json.loads(row[1])
        return None

    def is_active(self, user_id: int) -> bool:
        row = self.conn.execute(
            "SELECT is_active FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        return bool(row and row[0])

    def get_active_users(self) -> list[tuple]:
        """Returns list of (user_id, seniorities: list, roles: list)."""
        rows = self.conn.execute("""
            SELECT user_id, seniority, roles FROM users
            WHERE is_active = 1 AND seniority IS NOT NULL AND roles IS NOT NULL
        """).fetchall()
        return [(uid, json.loads(sen), json.loads(roles)) for uid, sen, roles in rows]

    # ── admin stats ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        total  = self.conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        active = self.conn.execute("SELECT COUNT(*) FROM users WHERE is_active = 1").fetchone()[0]

        # Count individual roles across all users
        all_users = self.conn.execute(
            "SELECT roles FROM users WHERE roles IS NOT NULL"
        ).fetchall()

        role_counts: dict = {}
        sen_counts: dict  = {}

        for (roles_json,) in all_users:
            for role in json.loads(roles_json):
                role_counts[role] = role_counts.get(role, 0) + 1

        all_sen = self.conn.execute(
            "SELECT seniority FROM users WHERE seniority IS NOT NULL"
        ).fetchall()
        for (sen_json,) in all_sen:
            for s in json.loads(sen_json):
                sen_counts[s] = sen_counts.get(s, 0) + 1

        top_roles     = sorted(role_counts.items(), key=lambda x: -x[1])[:5]
        seniority_dist = sorted(sen_counts.items(), key=lambda x: -x[1])

        return {
            "total":          total,
            "active":         active,
            "top_roles":      top_roles,
            "seniority_dist": seniority_dist,
        }
