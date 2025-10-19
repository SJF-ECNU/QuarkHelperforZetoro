from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from typing import Iterable, Optional

from loguru import logger

from ..cache.db import CacheEntry


NAMESPACE = "DAV:"


def http_date(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt, usegmt=True)


def build_propfind_response(
    base_url: str,
    request_path: str,
    entries: Iterable[CacheEntry],
    depth: str,
) -> str:
    """Build a minimal WebDAV multistatus XML response."""

    responses = []
    normalized_request = request_path.strip("/")
    for entry in entries:
        href = f"{base_url}/{entry.path.strip('/') if entry.path else ''}"
        if entry.path == normalized_request:
            display_name = Path(entry.path).name or Path(request_path).name or ""
        else:
            display_name = Path(entry.path).name
        if display_name:
            display_name_xml = f"<d:displayname>{display_name}</d:displayname>"
        else:
            display_name_xml = ""
        if entry.is_dir:
            resource_type = "<d:resourcetype><d:collection /></d:resourcetype>"
            content_length = ""
        else:
            resource_type = "<d:resourcetype />"
            content_length = f"<d:getcontentlength>{entry.size}</d:getcontentlength>"
        etag_xml = f"<d:getetag>\"{entry.etag}\"</d:getetag>" if entry.etag else ""
        last_mod = http_date(entry.updated_at)
        response_xml = f"""
        <d:response>
            <d:href>{href}</d:href>
            <d:propstat>
                <d:prop>
                    {display_name_xml}
                    {resource_type}
                    {content_length}
                    {etag_xml}
                    <d:getlastmodified>{last_mod}</d:getlastmodified>
                </d:prop>
                <d:status>HTTP/1.1 200 OK</d:status>
            </d:propstat>
        </d:response>
        """
        responses.append(response_xml)
    body = """<?xml version="1.0" encoding="utf-8"?>
    <d:multistatus xmlns:d="DAV:">
    {responses}
    </d:multistatus>
    """.format(responses="".join(responses))
    logger.debug("Built PROPFIND response for {} entries", len(responses))
    return body


def normalize_depth(depth: Optional[str]) -> str:
    if depth is None:
        return "infinity"
    depth = depth.lower()
    if depth in {"0", "1", "infinity"}:
        return depth
    return "infinity"
