from __future__ import annotations

from .api import AlistQuarkClient, BaseQuarkClient, FilesystemQuarkClient


def build_client(settings) -> BaseQuarkClient:
    """Build a Quark client implementation based on configuration."""

    backend = (getattr(settings, "quark_backend", "filesystem") or "filesystem").lower()
    if backend == "filesystem":
        return FilesystemQuarkClient(settings.cache_dir)
    if backend in {"alist", "webdav"}:
        if not getattr(settings, "alist_base_url", None):
            raise ValueError("ALIST_BASE_URL must be configured for the Alist backend")
        return AlistQuarkClient(
            base_url=str(settings.alist_base_url),
            username=getattr(settings, "alist_username", None),
            password=getattr(settings, "alist_password", None),
            timeout=getattr(settings, "alist_timeout", 30),
            verify_ssl=getattr(settings, "alist_verify_ssl", True),
        )
    raise ValueError(f"Unsupported quark backend: {backend}")


__all__ = [
    "AlistQuarkClient",
    "BaseQuarkClient",
    "FilesystemQuarkClient",
    "build_client",
]
