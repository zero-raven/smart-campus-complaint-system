"""Application logging configuration."""

from __future__ import annotations

import logging
import sys

from backend.core.config import get_settings

_CONFIGURED = False


def configure_logging() -> None:
    """Install a single stdout/stderr logging configuration.

    Idempotent: safe to call from both the app factory and test fixtures.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    settings = get_settings()
    level = logging.DEBUG if settings.debug else logging.INFO

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream = logging.StreamHandler(sys.stdout)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    # Third-party noise reduction
    logging.getLogger("pymongo").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)
