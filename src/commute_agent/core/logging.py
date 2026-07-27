"""Structured logging setup using stdlib logging + Rich for local dev."""

import logging
import sys

from rich.logging import RichHandler

from commute_agent.core.config import get_settings

_configured = False


def setup_logging() -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    handler = RichHandler(
        rich_tracebacks=True,
        show_path=True,
        markup=True,
    )

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[handler],
        force=True,
    )

    # Quieten noisy third-party loggers
    for noisy in ("httpx", "chromadb", "urllib3", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
