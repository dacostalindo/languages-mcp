"""SQLite store: cached page analyses and searches, and the agent's ratings of exercises."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

PAGE_TTL = 7 * 86400
SEARCH_TTL = 2 * 86400


def db_path() -> Path:
    p = Path(os.environ.get("DATA_DIR") or Path.home() / ".dutch-exercises").expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p / "store.db"


class Store:
    def __init__(self, path: Path | str | None = None):
        self.path = str(path or db_path())
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS pages (url TEXT PRIMARY KEY, at REAL, data TEXT);
            CREATE TABLE IF NOT EXISTS searches (query TEXT PRIMARY KEY, at REAL, data TEXT);
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY, url TEXT, rating INTEGER, level TEXT, theme TEXT, note TEXT, at REAL);
            CREATE INDEX IF NOT EXISTS ratings_url ON ratings(url);
        """)

    def _get(self, table: str, key_col: str, key: str, ttl: int):
        with self._lock:
            row = self._db.execute(f"SELECT at, data FROM {table} WHERE {key_col}=?", (key,)).fetchone()
        if row and time.time() - row[0] < ttl:
            return json.loads(row[1])
        return None

    def _put(self, table: str, key_col: str, key: str, data) -> None:
        with self._lock, self._db:
            self._db.execute(f"INSERT OR REPLACE INTO {table}({key_col}, at, data) VALUES (?,?,?)",
                             (key, time.time(), json.dumps(data)))

    def get_page(self, url: str):
        return self._get("pages", "url", url, PAGE_TTL)

    def put_page(self, url: str, data: dict) -> None:
        self._put("pages", "url", url, data)

    def get_search(self, query: str):
        return self._get("searches", "query", query, SEARCH_TTL)

    def put_search(self, query: str, data: list) -> None:
        self._put("searches", "query", query, data)

    def rate(self, url: str, rating: int, level: str = "", theme: str = "", note: str = "") -> None:
        with self._lock, self._db:
            self._db.execute("INSERT INTO ratings(url, rating, level, theme, note, at) VALUES (?,?,?,?,?,?)",
                             (url, rating, level, theme, note, time.time()))

    def rating_of(self, url: str) -> tuple[float, int] | None:
        with self._lock:
            row = self._db.execute("SELECT AVG(rating), COUNT(*) FROM ratings WHERE url=?", (url,)).fetchone()
        return (row[0], row[1]) if row and row[1] else None

    def domain_rating(self, host: str) -> tuple[float, int] | None:
        like = f"%://{host}/%"
        like_www = f"%://www.{host}/%"
        with self._lock:
            row = self._db.execute("SELECT AVG(rating), COUNT(*) FROM ratings WHERE url LIKE ? OR url LIKE ?",
                                   (like, like_www)).fetchone()
        return (row[0], row[1]) if row and row[1] else None

    def ratings(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT url, rating, level, theme, note, at FROM ratings ORDER BY at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(zip(("url", "rating", "level", "theme", "note", "at"), r)) for r in rows]
