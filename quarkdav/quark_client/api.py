from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from loguru import logger

from .utils import ensure_parent, md5_file


@dataclass
class QuarkFileInfo:
    path: str
    is_dir: bool
    size: int
    etag: str | None


class QuarkClient:
    """A lightweight filesystem-backed Quark Cloud client."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        logger.debug("Initialized QuarkClient with root {}", root)

    def _resolve(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path.strip("/"))
        return self.root / relative

    def ensure_directory(self, relative_path: str) -> Path:
        directory = self._resolve(relative_path)
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured remote directory exists: {}", directory)
        return directory

    def upload_file(self, relative_path: str, source: Path) -> QuarkFileInfo:
        destination = self._resolve(relative_path)
        ensure_parent(destination)
        shutil.copy2(source, destination)
        etag = md5_file(destination)
        info = QuarkFileInfo(
            path=relative_path,
            is_dir=False,
            size=destination.stat().st_size,
            etag=etag,
        )
        logger.debug("Uploaded file to remote storage: {}", info)
        return info

    def download_file(self, relative_path: str, destination: Path) -> Path:
        source = self._resolve(relative_path)
        if not source.exists():
            raise FileNotFoundError(relative_path)
        ensure_parent(destination)
        shutil.copy2(source, destination)
        logger.debug("Downloaded file from remote storage: {}", relative_path)
        return destination

    def delete(self, relative_path: str) -> None:
        target = self._resolve(relative_path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        logger.debug("Deleted remote resource: {}", relative_path)

    def move(self, source_path: str, dest_path: str) -> None:
        source = self._resolve(source_path)
        destination = self._resolve(dest_path)
        ensure_parent(destination)
        shutil.move(source, destination)
        logger.debug("Moved remote resource from {} to {}", source_path, dest_path)

    def stat(self, relative_path: str) -> QuarkFileInfo | None:
        target = self._resolve(relative_path)
        if not target.exists():
            return None
        if target.is_dir():
            return QuarkFileInfo(
                path=relative_path,
                is_dir=True,
                size=0,
                etag=None,
            )
        return QuarkFileInfo(
            path=relative_path,
            is_dir=False,
            size=target.stat().st_size,
            etag=md5_file(target),
        )

    def list_directory(self, relative_path: str = "") -> Iterable[QuarkFileInfo]:
        directory = self._resolve(relative_path)
        if not directory.exists():
            return []
        entries: list[QuarkFileInfo] = []
        for item in directory.iterdir():
            is_dir = item.is_dir()
            etag = None if is_dir else md5_file(item)
            entries.append(
                QuarkFileInfo(
                    path=str(Path(relative_path) / item.name).lstrip("./"),
                    is_dir=is_dir,
                    size=item.stat().st_size,
                    etag=etag,
                )
            )
        logger.debug("Listed directory {} -> {} entries", relative_path, len(entries))
        return entries
