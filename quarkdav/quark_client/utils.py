from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import BinaryIO


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def md5_hash(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def md5_file(path: Path | str, chunk_size: int = 1024 * 1024) -> str:
    file_path = Path(path)
    digest = hashlib.md5()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def buffered_reader(data: bytes | BinaryIO) -> BinaryIO:
    if isinstance(data, (bytes, bytearray)):
        return io.BytesIO(data)
    return data
