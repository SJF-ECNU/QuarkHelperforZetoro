from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from loguru import logger

from .utils import ensure_parent, md5_file


@dataclass
class QuarkFileInfo:
    path: str
    is_dir: bool
    size: int
    etag: str | None


class BaseQuarkClient:
    """Interface for interacting with Quark-compatible storage backends."""

    def ensure_directory(self, relative_path: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def upload_file(self, relative_path: str, source: Path) -> QuarkFileInfo:  # pragma: no cover - interface
        raise NotImplementedError

    def download_file(self, relative_path: str, destination: Path) -> Path:  # pragma: no cover - interface
        raise NotImplementedError

    def delete(self, relative_path: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def move(self, source_path: str, dest_path: str) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def stat(self, relative_path: str) -> QuarkFileInfo | None:  # pragma: no cover - interface
        raise NotImplementedError

    def list_directory(self, relative_path: str = "") -> Iterable[QuarkFileInfo]:  # pragma: no cover - interface
        raise NotImplementedError


class FilesystemQuarkClient(BaseQuarkClient):
    """A filesystem-backed Quark Cloud client used for local development."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        logger.debug("Initialized FilesystemQuarkClient with root {}", root)

    def _resolve(self, relative_path: str | Path) -> Path:
        relative = Path(relative_path.strip("/"))
        return self.root / relative

    def ensure_directory(self, relative_path: str) -> None:
        directory = self._resolve(relative_path)
        directory.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured filesystem directory exists: {}", directory)

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
        logger.debug("Uploaded file to filesystem storage: {}", info)
        return info

    def download_file(self, relative_path: str, destination: Path) -> Path:
        source = self._resolve(relative_path)
        if not source.exists():
            raise FileNotFoundError(relative_path)
        ensure_parent(destination)
        shutil.copy2(source, destination)
        logger.debug("Downloaded file from filesystem storage: {}", relative_path)
        return destination

    def delete(self, relative_path: str) -> None:
        target = self._resolve(relative_path)
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        logger.debug("Deleted filesystem resource: {}", relative_path)

    def move(self, source_path: str, dest_path: str) -> None:
        source = self._resolve(source_path)
        destination = self._resolve(dest_path)
        ensure_parent(destination)
        shutil.move(source, destination)
        logger.debug("Moved filesystem resource from {} to {}", source_path, dest_path)

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
        logger.debug("Listed filesystem directory {} -> {} entries", relative_path, len(entries))
        return entries


class AlistQuarkClient(BaseQuarkClient):
    """Quark client backed by an Alist WebDAV endpoint."""

    def __init__(
        self,
        base_url: str,
        username: Optional[str],
        password: Optional[str],
        timeout: int = 30,
        verify_ssl: bool = True,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required for AlistQuarkClient")
        self.base_url = base_url.rstrip("/") + "/"
        parsed = urlparse(self.base_url)
        self._base_path = parsed.path.rstrip("/")
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        if username or password:
            self.session.auth = (username or "", password or "")
        logger.debug("Initialized AlistQuarkClient with base {}", self.base_url)

    def _encode_path(self, relative_path: str) -> str:
        if not relative_path:
            return ""
        parts = [quote(part) for part in relative_path.strip("/").split("/") if part]
        return "/".join(parts)

    def _url(self, relative_path: str) -> str:
        encoded = self._encode_path(relative_path)
        return urljoin(self.base_url, encoded)

    def _normalize_href(self, href: str) -> str:
        parsed = urlparse(href)
        path = unquote(parsed.path)
        base_path = self._base_path
        if base_path and path.startswith(base_path):
            path = path[len(base_path) :]
        return path.strip("/")

    def _propfind(self, relative_path: str, depth: str) -> List[QuarkFileInfo]:
        url = self._url(relative_path)
        headers = {"Depth": depth}
        body = """<?xml version="1.0" encoding="utf-8"?>
<d:propfind xmlns:d="DAV:">
  <d:prop>
    <d:resourcetype />
    <d:getcontentlength />
    <d:getlastmodified />
    <d:getetag />
  </d:prop>
</d:propfind>
"""
        response = self.session.request(
            "PROPFIND",
            url,
            data=body.encode("utf-8"),
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        if response.status_code == 404:
            return []
        if response.status_code != 207:
            response.raise_for_status()
        entries: list[QuarkFileInfo] = []
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:  # pragma: no cover - defensive
            raise RuntimeError(f"Failed to parse WebDAV response: {exc}") from exc
        ns = {"d": "DAV:"}
        for element in root.findall("d:response", ns):
            href_elem = element.find("d:href", ns)
            propstat = element.find("d:propstat", ns)
            if href_elem is None or propstat is None:
                continue
            prop = propstat.find("d:prop", ns)
            if prop is None:
                continue
            relative = self._normalize_href(href_elem.text or "")
            collection = prop.find("d:resourcetype/d:collection", ns)
            is_dir = collection is not None or (href_elem.text or "").endswith("/")
            size_text = prop.findtext("d:getcontentlength", default="0") or "0"
            try:
                size = int(size_text)
            except ValueError:
                size = 0
            etag = prop.findtext("d:getetag")
            if etag:
                etag = etag.strip('"')
            entries.append(
                QuarkFileInfo(
                    path=relative,
                    is_dir=is_dir,
                    size=size,
                    etag=etag,
                )
            )
        return entries

    def ensure_directory(self, relative_path: str) -> None:
        normalized = relative_path.strip("/")
        if not normalized:
            return
        parts = normalized.split("/")
        for index in range(1, len(parts) + 1):
            sub_path = "/".join(parts[:index])
            url = self._url(sub_path)
            response = self.session.request(
                "MKCOL",
                url,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            if response.status_code in {201, 405}:
                continue
            if response.status_code == 409:
                continue  # parent creation will be retried in loop
            response.raise_for_status()
        logger.debug("Ensured remote directory exists via Alist: {}", normalized)

    def upload_file(self, relative_path: str, source: Path) -> QuarkFileInfo:
        url = self._url(relative_path)
        with source.open("rb") as handle:
            response = self.session.put(
                url,
                data=handle,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
        if response.status_code not in {200, 201, 204}:
            response.raise_for_status()
        info = QuarkFileInfo(
            path=relative_path,
            is_dir=False,
            size=source.stat().st_size,
            etag=md5_file(source),
        )
        logger.debug("Uploaded file to Alist backend: {}", info)
        return info

    def download_file(self, relative_path: str, destination: Path) -> Path:
        url = self._url(relative_path)
        response = self.session.get(
            url,
            stream=True,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        if response.status_code == 404:
            raise FileNotFoundError(relative_path)
        response.raise_for_status()
        ensure_parent(destination)
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
        logger.debug("Downloaded file from Alist backend: {}", relative_path)
        return destination

    def delete(self, relative_path: str) -> None:
        url = self._url(relative_path)
        response = self.session.delete(
            url,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        if response.status_code not in {200, 202, 204, 404}:
            response.raise_for_status()
        logger.debug("Deleted remote resource via Alist: {}", relative_path)

    def move(self, source_path: str, dest_path: str) -> None:
        source_url = self._url(source_path)
        destination_url = self._url(dest_path)
        headers = {"Destination": destination_url}
        response = self.session.request(
            "MOVE",
            source_url,
            headers=headers,
            timeout=self.timeout,
            verify=self.verify_ssl,
        )
        if response.status_code not in {201, 204}:
            response.raise_for_status()
        logger.debug("Moved remote resource via Alist from {} to {}", source_path, dest_path)

    def stat(self, relative_path: str) -> QuarkFileInfo | None:
        entries = self._propfind(relative_path, depth="0")
        return entries[0] if entries else None

    def list_directory(self, relative_path: str = "") -> Iterable[QuarkFileInfo]:
        entries = self._propfind(relative_path, depth="1")
        normalized = relative_path.strip("/")
        result: list[QuarkFileInfo] = []
        for entry in entries:
            if entry.path.strip("/") == normalized:
                continue
            result.append(entry)
        logger.debug(
            "Listed remote directory via Alist {} -> {} entries",
            relative_path,
            len(result),
        )
        return result


__all__ = [
    "BaseQuarkClient",
    "FilesystemQuarkClient",
    "AlistQuarkClient",
    "QuarkFileInfo",
]
