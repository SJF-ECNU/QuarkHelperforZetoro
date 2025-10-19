from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from ..cache.db import CacheEntry, CacheIndex
from ..quark_client.api import QuarkClient
from ..quark_client.utils import ensure_parent, md5_file


@dataclass
class ResourceMetadata:
    path: str
    is_dir: bool
    size: int
    etag: str | None
    updated_at: datetime


class ResourceManager:
    """Bridges WebDAV operations with the cache and Quark client."""

    def __init__(self, cache: CacheIndex, client: QuarkClient, cache_root: Path) -> None:
        self.cache = cache
        self.client = client
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        try:
            client_root = self.client.root
        except AttributeError:  # pragma: no cover - defensive for alternate clients
            client_root = None
        self._roots_collide = (
            client_root is not None
            and Path(client_root).resolve() == self.cache_root.resolve()
        )

    def _normalize(self, path: str) -> str:
        return path.strip("/")

    def _cache_path(self, relative_path: str) -> Path:
        return self.cache_root / relative_path

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def ensure_directory(self, path: str) -> ResourceMetadata:
        normalized = self._normalize(path)
        self.client.ensure_directory(normalized)
        directory = self._cache_path(normalized)
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Created directory {}", normalized or "/")
        metadata = ResourceMetadata(
            path=normalized,
            is_dir=True,
            size=0,
            etag=None,
            updated_at=self._now(),
        )
        self.cache.upsert(CacheEntry(**metadata.__dict__))
        return metadata

    def put_file(self, path: str, data_path: Path) -> ResourceMetadata:
        normalized = self._normalize(path)
        cache_path = self._cache_path(normalized)
        ensure_parent(cache_path)
        shutil.copy2(data_path, cache_path)
        if not self._roots_collide:
            self.client.upload_file(normalized, cache_path)
        etag = md5_file(cache_path)
        metadata = ResourceMetadata(
            path=normalized,
            is_dir=False,
            size=cache_path.stat().st_size,
            etag=etag,
            updated_at=self._now(),
        )
        self.cache.upsert(CacheEntry(**metadata.__dict__))
        return metadata

    def get_file(self, path: str) -> Path:
        normalized = self._normalize(path)
        cache_path = self._cache_path(normalized)
        if cache_path.exists():
            if cache_path.is_dir():
                raise IsADirectoryError(f"{cache_path} is a directory")
            return cache_path
        ensure_parent(cache_path)
        self.client.download_file(normalized, cache_path)
        self.cache.upsert(
            CacheEntry(
                path=normalized,
                is_dir=False,
                size=cache_path.stat().st_size,
                etag=md5_file(cache_path),
                updated_at=self._now(),
            )
        )
        return cache_path

    def delete(self, path: str) -> None:
        normalized = self._normalize(path)
        cache_path = self._cache_path(normalized)
        if cache_path.is_dir() and cache_path.exists():
            shutil.rmtree(cache_path)
        elif cache_path.exists():
            cache_path.unlink()
        self.client.delete(normalized)
        self.cache.delete(normalized)
        logger.debug("Deleted resource {}", normalized)

    def move(self, source: str, dest: str) -> None:
        norm_source = self._normalize(source)
        norm_dest = self._normalize(dest)
        src_cache = self._cache_path(norm_source)
        dst_cache = self._cache_path(norm_dest)
        if src_cache.exists():
            ensure_parent(dst_cache)
            shutil.move(src_cache, dst_cache)
        if not self._roots_collide:
            self.client.move(norm_source, norm_dest)
        entry = self.cache.get(norm_source)
        if entry:
            self.cache.delete(norm_source)
            self.cache.upsert(
                CacheEntry(
                    path=norm_dest,
                    is_dir=entry.is_dir,
                    size=entry.size,
                    etag=entry.etag,
                    updated_at=self._now(),
                )
            )
        logger.debug("Moved resource from {} to {}", norm_source, norm_dest)

    def stat(self, path: str) -> ResourceMetadata | None:
        normalized = self._normalize(path)
        entry = self.cache.get(normalized)
        if entry:
            return ResourceMetadata(
                path=entry.path,
                is_dir=entry.is_dir,
                size=entry.size,
                etag=entry.etag,
                updated_at=entry.updated_at,
            )
        cache_path = self._cache_path(normalized)
        if cache_path.exists():
            metadata = ResourceMetadata(
                path=normalized,
                is_dir=cache_path.is_dir(),
                size=0 if cache_path.is_dir() else cache_path.stat().st_size,
                etag=None if cache_path.is_dir() else md5_file(cache_path),
                updated_at=self._now(),
            )
            self.cache.upsert(CacheEntry(**metadata.__dict__))
            return metadata
        remote_info = self.client.stat(normalized)
        if remote_info:
            metadata = ResourceMetadata(
                path=remote_info.path,
                is_dir=remote_info.is_dir,
                size=remote_info.size,
                etag=remote_info.etag,
                updated_at=self._now(),
            )
            self.cache.upsert(CacheEntry(**metadata.__dict__))
            return metadata
        return None

    def list_directory(self, path: str, depth: str = "infinity") -> list[ResourceMetadata]:
        normalized = self._normalize(path)
        entries: list[ResourceMetadata] = []
        if depth == "0":
            return entries

        if depth == "1":
            iterator = self.cache.list_children(normalized)
        else:
            iterator = self.cache.list_subtree(normalized)

        for entry in iterator:
            entries.append(
                ResourceMetadata(
                    path=entry.path,
                    is_dir=entry.is_dir,
                    size=entry.size,
                    etag=entry.etag,
                    updated_at=entry.updated_at,
                )
            )

        if not entries and depth != "0":
            remote_entries = (
                self._gather_remote_subtree(normalized)
                if depth == "infinity"
                else self.client.list_directory(normalized)
            )
            for remote in remote_entries:
                metadata = ResourceMetadata(
                    path=remote.path,
                    is_dir=remote.is_dir,
                    size=remote.size,
                    etag=remote.etag,
                    updated_at=self._now(),
                )
                self.cache.upsert(CacheEntry(**metadata.__dict__))
                entries.append(metadata)
        return entries

    def _gather_remote_subtree(self, path: str) -> list:
        results = []
        queue = [path.strip("/")]
        while queue:
            current = queue.pop(0)
            for entry in self.client.list_directory(current):
                results.append(entry)
                if entry.is_dir:
                    queue.append(entry.path)
        return results
