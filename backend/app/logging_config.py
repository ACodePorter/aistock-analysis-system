"""Central logging configuration for the backend service.

The configuration is driven by environment variables so production and
local development can tweak the behaviour without touching code.

Environment variables:
- LOG_LEVEL: root log level (default: INFO)
- LOG_FORMAT: logging format string (default: '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
- LOG_DATE_FORMAT: strftime pattern for timestamps (default: '%Y-%m-%d %H:%M:%S')
- LOG_FILE: if set, enable a rotating file handler at this path
- LOG_FILE_MAX_BYTES: max bytes before rotation (default: 10MB)
- LOG_FILE_BACKUP_COUNT: number of rotated files to keep (default: 5)
"""

from __future__ import annotations

import logging
import logging.config
import os
from pathlib import Path
from typing import Dict, Any

__all__ = ["configure_logging"]

_DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_DEFAULT_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _build_handlers(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Build the handler configuration map based on environment variables."""
    handlers: Dict[str, Dict[str, Any]] = {
        "console": {
            "class": "logging.StreamHandler",
            "level": config["level"],
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        }
    }

    log_file = os.getenv("LOG_FILE")
    if log_file:
        log_path = Path(log_file).expanduser().resolve()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = int(os.getenv("LOG_FILE_MAX_BYTES", 10 * 1024 * 1024))
        backup_count = int(os.getenv("LOG_FILE_BACKUP_COUNT", 5))
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "level": config["level"],
            "formatter": "standard",
            "filename": str(log_path),
            "maxBytes": max_bytes,
            "backupCount": backup_count,
            "encoding": "utf-8",
        }
    return handlers


def configure_logging(force: bool = False) -> None:
    """Configure application-wide logging.

    Args:
        force: if True reconfigure even if called previously.
    """
    if getattr(configure_logging, "_configured", False) and not force:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    fmt = os.getenv("LOG_FORMAT", _DEFAULT_FORMAT)
    datefmt = os.getenv("LOG_DATE_FORMAT", _DEFAULT_DATE_FORMAT)

    base_config: Dict[str, Any] = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "standard": {
                "format": fmt,
                "datefmt": datefmt,
            }
        },
        "handlers": {},
        "root": {
            "level": level,
            "handlers": [],
        },
        "loggers": {
            # Uvicorn access and error loggers are configured separately so they follow the same format.
            "uvicorn": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.error": {"level": level, "handlers": ["console"], "propagate": False},
            "uvicorn.access": {"level": level, "handlers": ["console"], "propagate": False},
        },
    }

    handlers = _build_handlers({"level": level})
    base_config["handlers"] = handlers
    base_config["root"]["handlers"] = list(handlers.keys())

    logging.config.dictConfig(base_config)
    configure_logging._configured = True


configure_logging._configured = False
