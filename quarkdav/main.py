from __future__ import annotations

import asyncio
from loguru import logger

from .config import get_settings
from .webdav.server import run_server


def main() -> None:
    settings = get_settings()
    try:
        asyncio.run(run_server(settings))
    except KeyboardInterrupt:
        logger.info("QuarkDAV terminated by user")


if __name__ == "__main__":
    main()
