from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ssl import SSLContext

from aiohttp import web
from loguru import logger

from ..cache.db import CacheIndex, CacheEntry
from ..config import Settings
from ..quark_client.api import QuarkClient
from .compat_zotero import build_propfind_response, normalize_depth
from .resource import ResourceManager


class BasicAuthMiddleware:
    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password

    @staticmethod
    def _parse_auth(header: str) -> tuple[str, str]:
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic":
            raise ValueError("Unsupported auth scheme")
        decoded = base64.b64decode(encoded).decode()
        user, _, password = decoded.partition(":")
        return user, password

    @web.middleware
    async def middleware(self, request: web.Request, handler):
        header = request.headers.get("Authorization")
        if not header:
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="QuarkDAV"'})
        try:
            user, password = self._parse_auth(header)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to parse auth header: {}", exc)
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="QuarkDAV"'})
        if user != self.username or password != self.password:
            raise web.HTTPUnauthorized(headers={"WWW-Authenticate": 'Basic realm="QuarkDAV"'})
        return await handler(request)


def create_app(settings: Settings) -> web.Application:
    cache = CacheIndex(settings.db_path)
    quark_root = settings.cache_dir
    client = QuarkClient(quark_root)
    resource_manager = ResourceManager(cache, client, settings.cache_dir)

    auth = BasicAuthMiddleware(settings.webdav_user, settings.webdav_password)

    app = web.Application(middlewares=[auth.middleware])

    async def handle_propfind(request: web.Request) -> web.StreamResponse:
        depth = normalize_depth(request.headers.get("Depth"))
        path = request.match_info.get("path", "")
        resources = []
        normalized_depth = depth
        if path:
            stat = resource_manager.stat(path)
            if stat:
                resources.append(CacheEntry(**stat.__dict__))
        else:
            resources.append(
                CacheEntry(
                    path="",
                    is_dir=True,
                    size=0,
                    etag=None,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        entries = resource_manager.list_directory(path, depth=normalized_depth)
        for entry in entries:
            resources.append(CacheEntry(**entry.__dict__))
        base_url = f"{request.scheme}://{request.host}".rstrip("/")
        body = build_propfind_response(base_url, path, resources, depth)
        return web.Response(status=207, text=body, content_type="application/xml")

    async def handle_mkcol(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        resource_manager.ensure_directory(path)
        return web.Response(status=201)

    async def handle_put(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        tmp_path = Path(settings.cache_dir) / ".upload" / Path(path).name
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("wb") as handle:
            while True:
                chunk = await request.content.readany()
                if not chunk:
                    break
                handle.write(chunk)
        metadata = resource_manager.put_file(path, tmp_path)
        tmp_path.unlink(missing_ok=True)
        headers = {
            "ETag": f'"{metadata.etag}"' if metadata.etag else "",
            "Content-Length": str(metadata.size),
        }
        return web.Response(status=201, headers=headers)

    async def handle_get(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        try:
            file_path = resource_manager.get_file(path)
        except FileNotFoundError:
            raise web.HTTPNotFound()
        if not file_path.exists():
            raise web.HTTPNotFound()
        headers = {
            "Content-Length": str(file_path.stat().st_size),
            "ETag": f'"{resource_manager.stat(path).etag}"' if resource_manager.stat(path) else "",
        }
        return web.FileResponse(file_path, headers=headers)

    async def handle_head(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        metadata = resource_manager.stat(path)
        if not metadata or metadata.is_dir:
            raise web.HTTPNotFound()
        headers = {
            "Content-Length": str(metadata.size),
            "ETag": f'"{metadata.etag}"' if metadata.etag else "",
            "Last-Modified": metadata.updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        return web.Response(status=200, headers=headers)

    async def handle_delete(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        resource_manager.delete(path)
        return web.Response(status=204)

    async def handle_move(request: web.Request) -> web.StreamResponse:
        source = request.match_info.get("path", "")
        destination = request.headers.get("Destination")
        if not destination:
            raise web.HTTPBadRequest(text="Missing Destination header")
        dest_path = destination.split(request.scheme + "://" + request.host, 1)[-1]
        dest_path = dest_path.lstrip("/")
        resource_manager.move(source, dest_path)
        return web.Response(status=201)

    app.router.add_route("PROPFIND", "/{path:.*}", handle_propfind)
    app.router.add_route("MKCOL", "/{path:.*}", handle_mkcol)
    app.router.add_route("PUT", "/{path:.*}", handle_put)
    app.router.add_route("GET", "/{path:.*}", handle_get)
    app.router.add_route("HEAD", "/{path:.*}", handle_head)
    app.router.add_route("DELETE", "/{path:.*}", handle_delete)
    app.router.add_route("MOVE", "/{path:.*}", handle_move)

    return app


async def run_server(settings: Optional[Settings] = None) -> None:
    settings = settings or Settings()
    app = create_app(settings)
    runner = web.AppRunner(app)
    await runner.setup()
    ssl_context: Optional[SSLContext] = None
    try:
        ssl_context = settings.build_ssl_context()
    except Exception as exc:
        logger.error("Failed to configure TLS: {}", exc)
        await runner.cleanup()
        raise
    scheme = "https" if ssl_context else "http"
    site = web.TCPSite(
        runner, host=settings.host, port=settings.port, ssl_context=ssl_context
    )
    logger.info(
        "Starting QuarkDAV server on {}://{}:{}",
        scheme,
        settings.host,
        settings.port,
    )
    await site.start()
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover - graceful shutdown
        logger.info("QuarkDAV server shutdown requested")
    finally:
        await runner.cleanup()


__all__ = ["create_app", "run_server"]
