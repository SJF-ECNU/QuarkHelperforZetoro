from __future__ import annotations

import asyncio
import base64
from html import escape
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
    for required in ("zotero", "zotero/storage"):
        resource_manager.ensure_directory(required)

    auth = BasicAuthMiddleware(settings.webdav_user, settings.webdav_password)

    @web.middleware
    async def request_logger(request: web.Request, handler):
        path = request.path_qs or "/"
        logger.debug(">> {} {}", request.method, path)
        try:
            response = await handler(request)
        except web.HTTPException as exc:
            logger.debug("<< {} {} -> {}", request.method, path, exc.status)
            raise
        except Exception:
            logger.exception("!! {} {} failed", request.method, path)
            raise
        logger.debug("<< {} {} -> {}", request.method, path, response.status)
        return response

    app = web.Application(middlewares=[request_logger, auth.middleware])

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
        payload = body.encode("utf-8")
        headers = {
            "Content-Length": str(len(payload)),
            "DAV": "1",
        }
        resp = web.Response(
            status=207,
            body=payload,
            content_type="application/xml",
            headers=headers,
        )
        resp.charset = "utf-8"
        return resp

    async def handle_options(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("OPTIONS {}", path or "/")
        allowed = "OPTIONS, PROPFIND, MKCOL, PUT, GET, HEAD, DELETE, MOVE"
        headers = {
            "Allow": allowed,
            "DAV": "1",
            "MS-Author-Via": "DAV",
            "Content-Length": "0",
        }
        return web.Response(status=200, headers=headers)

    async def handle_mkcol(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("MKCOL {}", path or "/")
        existing = resource_manager.stat(path)
        if existing:
            allowed = ["OPTIONS", "PROPFIND", "GET", "HEAD", "PUT", "DELETE", "MOVE"]
            raise web.HTTPMethodNotAllowed("MKCOL", allowed)
        parent_path = "/".join(filter(None, path.strip("/").split("/")[:-1]))
        if parent_path and not resource_manager.stat(parent_path):
            raise web.HTTPConflict(text="Parent collection does not exist")
        resource_manager.ensure_directory(path)
        return web.Response(status=201, headers={"Content-Length": "0"})

    async def handle_put(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("PUT {}", path or "/")
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
            "Content-Length": "0",
            "Location": f"/{path.strip('/')}",
        }
        return web.Response(status=201, headers=headers)

    async def handle_get(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("GET {}", path or "/")
        metadata = resource_manager.stat(path)
        normalized = path.strip("/")
        is_directory_request = (
            (metadata is not None and metadata.is_dir)
            or path.endswith("/")
            or path == ""
        )
        if is_directory_request:
            if metadata is None:
                resource_manager.ensure_directory(path)
                metadata = resource_manager.stat(path)
            entries = resource_manager.list_directory(path, depth="1")
            prefix = f"{normalized}/" if normalized else ""
            listing = []
            for entry in entries:
                name = entry.path[len(prefix) :] if prefix and entry.path.startswith(prefix) else entry.path
                if not name:
                    continue
                display = name + ("/" if entry.is_dir else "")
                href = escape(display)
                listing.append(f'<li><a href="{href}">{escape(display)}</a></li>')
            if not listing:
                listing.append("<li><em>Empty directory</em></li>")
            body = (
                "<html><body>"
                f"<h1>Index of /{escape(normalized)}</h1>"
                "<ul>"
                + "".join(listing)
                + "</ul>"
                "</body></html>"
            )
            resp = web.Response(
                status=200,
                text=body,
                content_type="text/html",
            )
            resp.charset = "utf-8"
            return resp
        try:
            file_path = resource_manager.get_file(path)
        except FileNotFoundError:
            raise web.HTTPNotFound()
        except IsADirectoryError:
            raise web.HTTPFound(location=f"/{normalized}/")
        if not file_path.exists():
            raise web.HTTPNotFound()
        headers = {
            "Content-Length": str(file_path.stat().st_size),
            "ETag": f'"{resource_manager.stat(path).etag}"' if resource_manager.stat(path) else "",
        }
        return web.FileResponse(file_path, headers=headers)

    async def handle_head(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("HEAD {}", path or "/")
        metadata = resource_manager.stat(path)
        if not metadata:
            raise web.HTTPNotFound()
        headers = {
            "Content-Length": "0",
        }
        if metadata.is_dir:
            headers.update(
                {
                    "Allow": "OPTIONS, PROPFIND, MKCOL, PUT, GET, HEAD, DELETE, MOVE",
                    "DAV": "1",
                }
            )
            return web.Response(status=200, headers=headers)
        headers = {
            "Content-Length": str(metadata.size),
            "ETag": f'"{metadata.etag}"' if metadata.etag else "",
            "Last-Modified": metadata.updated_at.strftime("%a, %d %b %Y %H:%M:%S GMT"),
        }
        return web.Response(status=200, headers=headers)

    async def handle_delete(request: web.Request) -> web.StreamResponse:
        path = request.match_info.get("path", "")
        logger.debug("DELETE {}", path or "/")
        resource_manager.delete(path)
        return web.Response(status=204, headers={"Content-Length": "0"})

    async def handle_move(request: web.Request) -> web.StreamResponse:
        source = request.match_info.get("path", "")
        logger.debug("MOVE {} -> {}", source or "/", request.headers.get("Destination"))
        destination = request.headers.get("Destination")
        if not destination:
            raise web.HTTPBadRequest(text="Missing Destination header")
        dest_path = destination.split(request.scheme + "://" + request.host, 1)[-1]
        dest_path = dest_path.lstrip("/")
        resource_manager.move(source, dest_path)
        return web.Response(status=201, headers={"Content-Length": "0"})

    app.router.add_route("OPTIONS", "/{path:.*}", handle_options)
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
    bind_hosts = [settings.host]
    if settings.host in ("0.0.0.0", "127.0.0.1", ""):
        bind_hosts = ["0.0.0.0", "::"]
    elif settings.host == "localhost":
        bind_hosts = ["127.0.0.1", "::1"]
    sites: list[web.TCPSite] = []
    for host in dict.fromkeys(bind_hosts):  # preserve order, drop duplicates
        try:
            site = web.TCPSite(
                runner, host=host, port=settings.port, ssl_context=ssl_context
            )
            await site.start()
            sites.append(site)
            logger.info("Serving QuarkDAV on {}://{}:{}", scheme, host, settings.port)
        except OSError as exc:
            logger.warning("Failed to bind {}:{} ({})", host, settings.port, exc)
    if not sites:
        await runner.cleanup()
        raise RuntimeError("Unable to bind any network interfaces")
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:  # pragma: no cover - graceful shutdown
        logger.info("QuarkDAV server shutdown requested")
    finally:
        await runner.cleanup()


__all__ = ["create_app", "run_server"]
