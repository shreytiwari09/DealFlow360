"""Logging setup.

SECURITY_SPEC.md non-negotiable: never log passwords, OTPs, tokens, or DB
credentials. Keep the format simple - structured logging is not a Phase 1
requirement.
"""

import logging

from app.core.config import settings


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # asyncpg/SQLAlchemy INFO chatter drowns out application logs in dev.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )
