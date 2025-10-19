from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Optional

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

    class Config:
        env_file = ".env"
        case_sensitive = False

    @validator("cache_dir", "db_path", pre=True)
    def _expand_path(cls, value: str | pathlib.Path) -> pathlib.Path:
        path = pathlib.Path(value).expanduser().resolve()
        return path

    def ensure_directories(self) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.debug("Ensured cache directories exist: {}", self.cache_dir)


@lru_cache()
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_directories()
    logger.debug("Configuration loaded: {}", settings.dict())
    return settings


__all__ = ["Settings", "get_settings"]
