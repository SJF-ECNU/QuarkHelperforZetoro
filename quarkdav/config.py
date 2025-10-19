from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Optional

from ssl import SSLContext, PROTOCOL_TLS_SERVER

from loguru import logger
from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or a .env file."""

    webdav_user: str = Field("zotero", env="WEBDAV_USER")
    webdav_password: str = Field("secret", env="WEBDAV_PASSWORD")
    port: int = Field(5212, env="PORT")
    host: str = Field("0.0.0.0", env="HOST")

    cache_dir: pathlib.Path = Field(pathlib.Path("cache/storage"), env="CACHE_DIR")
    db_path: pathlib.Path = Field(pathlib.Path("cache/index.db"), env="DB_PATH")
    quark_cookie: Optional[str] = Field(None, env="QUARK_COOKIE")
    ssl_cert_file: Optional[pathlib.Path] = Field(None, env="SSL_CERT_FILE")
    ssl_key_file: Optional[pathlib.Path] = Field(None, env="SSL_KEY_FILE")

    class Config:
        env_file = ".env"
        case_sensitive = False

    @validator("cache_dir", "db_path", "ssl_cert_file", "ssl_key_file", pre=True)
    def _expand_path(cls, value: str | pathlib.Path) -> Optional[pathlib.Path]:
        if value in (None, "", False):
            return None
        path = pathlib.Path(value).expanduser().resolve()
        return path

    def ensure_directories(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured cache directories exist: {}", self.cache_dir)
        if bool(self.ssl_cert_file) ^ bool(self.ssl_key_file):
            raise ValueError("SSL_CERT_FILE and SSL_KEY_FILE must both be provided")
        if self.ssl_cert_file and not self.ssl_cert_file.exists():
            raise FileNotFoundError(f"SSL certificate file not found: {self.ssl_cert_file}")
        if self.ssl_key_file and not self.ssl_key_file.exists():
            raise FileNotFoundError(f"SSL key file not found: {self.ssl_key_file}")

    def build_ssl_context(self) -> Optional[SSLContext]:
        if self.ssl_cert_file and self.ssl_key_file:
            context = SSLContext(PROTOCOL_TLS_SERVER)
            context.load_cert_chain(
                certfile=str(self.ssl_cert_file), keyfile=str(self.ssl_key_file)
            )
            return context
        if self.ssl_cert_file or self.ssl_key_file:
            logger.warning(
                "Both SSL_CERT_FILE and SSL_KEY_FILE must be provided for TLS; continuing without TLS"
            )
        return None


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    logger.debug("Configuration loaded: {}", settings.dict())
    return settings


__all__ = ["Settings", "get_settings"]
