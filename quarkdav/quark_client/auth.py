from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from loguru import logger


@dataclass
class AuthResult:
    cookie: Optional[str]
    valid: bool


class QuarkAuthenticator:
    """Placeholder authenticator for Quark Cloud."""

    def __init__(self, cookie: Optional[str]) -> None:
        self.cookie = cookie

    def validate(self) -> AuthResult:
        if not self.cookie:
            logger.warning("No QUARK_COOKIE provided; running in offline mode")
            return AuthResult(cookie=None, valid=False)
        logger.debug("Using provided QUARK_COOKIE for authentication")
        return AuthResult(cookie=self.cookie, valid=True)
