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
import sys
import platform

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

        # Strategy for file handler to avoid Windows rename contention during rotation.
        # Options (via LOG_FILE_STRATEGY):
        # - concurrent: use ConcurrentRotatingFileHandler if available
        # - pid: append current PID to filename and use RotatingFileHandler
        # - rotate: plain RotatingFileHandler (delay=True)
        # - single: simple FileHandler without rotation
        strategy_env = os.getenv("LOG_FILE_STRATEGY", "").strip().lower()
        is_windows = os.name == "nt" or platform.system().lower().startswith("win")

        # Try import concurrent-log-handler only when needed
        concurrent_available = False
        try:
            import concurrent_log_handler  # type: ignore
            concurrent_available = True
        except Exception:
            concurrent_available = False

        # Default strategy: on Windows prefer concurrent if available, otherwise pid; on others use rotate
        if not strategy_env:
            if is_windows:
                strategy = "concurrent" if concurrent_available else "pid"
            else:
                strategy = "rotate"
        else:
            strategy = strategy_env

        filename_final = str(log_path)
        if strategy == "concurrent" and not concurrent_available:
            # Fallback if user requested concurrent but package missing
            strategy = "pid" if is_windows else "rotate"

        if strategy == "concurrent":
            handlers["file"] = {
                "class": "concurrent_log_handler.ConcurrentRotatingFileHandler",
                "level": config["level"],
                "formatter": "standard",
                "filename": filename_final,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
            }
        elif strategy == "pid":
            # Append .{pid} before suffix to avoid cross-process rename conflicts
            p = log_path
            if p.suffix:
                filename_final = str(p.with_name(f"{p.stem}.{os.getpid()}{p.suffix}"))
            else:
                filename_final = f"{str(p)}.{os.getpid()}"
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": config["level"],
                "formatter": "standard",
                "filename": filename_final,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
                "delay": True,
            }
        elif strategy == "single":
            handlers["file"] = {
                "class": "logging.FileHandler",
                "level": config["level"],
                "formatter": "standard",
                "filename": filename_final,
                "encoding": "utf-8",
                "delay": True,
            }
        else:  # "rotate"
            handlers["file"] = {
                "class": "logging.handlers.RotatingFileHandler",
                "level": config["level"],
                "formatter": "standard",
                "filename": filename_final,
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
                "delay": True,
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
            # Make httpx client logs consistent
            "httpx": {"level": os.getenv("HTTPX_LOG_LEVEL", level), "handlers": ["console"], "propagate": False},
        },
    }

    handlers = _build_handlers({"level": level})
    base_config["handlers"] = handlers
    base_config["root"]["handlers"] = list(handlers.keys())

    # If file handler exists, also attach it to uvicorn/httpx so access logs land in file too
    if "file" in handlers:
        for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx"):
            if name in base_config["loggers"]:
                # ensure both console and file
                base_config["loggers"][name]["handlers"] = [h for h in {"console", "file"}]

    logging.config.dictConfig(base_config)
    configure_logging._configured = True


configure_logging._configured = False
