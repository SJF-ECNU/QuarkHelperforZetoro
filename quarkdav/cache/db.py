from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger


@dataclass
class CacheEntry:
    path: str
    is_dir: bool
    size: int
    etag: Optional[str]
    updated_at: datetime


class CacheIndex:
    """SQLite-backed cache index for file metadata."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    path TEXT PRIMARY KEY,
                    is_dir INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    etag TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        logger.debug("Ensured cache database schema at {}", self.db_path)

    def upsert(self, entry: CacheEntry) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO cache(path, is_dir, size, etag, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    is_dir=excluded.is_dir,
                    size=excluded.size,
                    etag=excluded.etag,
                    updated_at=excluded.updated_at
                """,
                (
                    entry.path,
                    1 if entry.is_dir else 0,
                    entry.size,
                    entry.etag,
                    entry.updated_at.isoformat(),
                ),
            )
            conn.commit()
        logger.debug("Upserted cache entry for {}", entry.path)

    def delete(self, path: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM cache WHERE path = ?", (path,))
            conn.commit()
        logger.debug("Deleted cache entry for {}", path)

    def get(self, path: str) -> Optional[CacheEntry]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM cache WHERE path = ?", (path,)).fetchone()
        if not row:
            return None
        return CacheEntry(
            path=row["path"],
            is_dir=bool(row["is_dir"]),
            size=row["size"],
            etag=row["etag"],
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_children(self, prefix: str) -> Iterable[CacheEntry]:
        normalized = prefix.strip("/")
        normalized = normalized if normalized else ""
        base = f"{normalized}/" if normalized else ""
        like_pattern = f"{normalized}" if normalized else "%"
        like_children = f"{base}%" if base else "%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cache WHERE path = ? OR path LIKE ?",
                (normalized, like_children),
            ).fetchall()
        seen = set()
        for row in rows:
            child_path = row["path"]
            if normalized and child_path == normalized:
                continue
            remainder = child_path[len(base) :] if base and child_path.startswith(base) else child_path
            if "/" in remainder or remainder == "":
                continue
            if child_path in seen:
                continue
            seen.add(child_path)
            yield CacheEntry(
                path=child_path,
                is_dir=bool(row["is_dir"]),
                size=row["size"],
                etag=row["etag"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

    def list_subtree(self, path: str) -> Iterable[CacheEntry]:
        normalized = path.strip("/")
        base = f"{normalized}/" if normalized else ""
        like_pattern = f"{base}%"
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM cache WHERE path = ? OR path LIKE ?",
                (normalized, like_pattern),
            ).fetchall()
        for row in rows:
            if row["path"] == normalized:
                continue
            yield CacheEntry(
                path=row["path"],
                is_dir=bool(row["is_dir"]),
                size=row["size"],
                etag=row["etag"],
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )
