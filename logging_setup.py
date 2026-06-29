"""Logging configuration for VolumeMixer.

Installs a rotating file handler under ``%APPDATA%/VolumeMixer/app.log`` (or
``~/.config/VolumeMixer/app.log``) and a stream handler on stderr. Call
:func:`setup` exactly once from :mod:`main` before any other module is
imported and used.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Optional

from config import APP_NAME

_CONFIGURED = False
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _log_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        base = Path(appdata) / APP_NAME
    else:
        base = Path.home() / ".config" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def setup(level: int = logging.INFO) -> Path:
    """Configure the root logger. Returns the path of the log file."""
    global _CONFIGURED
    if _CONFIGURED:
        return _log_dir() / "app.log"

    log_path = _log_dir() / "app.log"

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    file_handler: Optional[logging.Handler] = None
    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
        )
    except OSError:
        file_handler = None
    if file_handler is not None:
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
        root.addHandler(file_handler)

    stream = logging.StreamHandler(stream=sys.stderr)
    stream.setFormatter(formatter)
    stream.setLevel(level)
    root.addHandler(stream)

    _CONFIGURED = True
    logging.getLogger(__name__).info("Logging initialized at %s", log_path)
    return log_path


def install_excepthook() -> None:
    """Route uncaught exceptions through the logging system."""
    logger = logging.getLogger("uncaught")

    def _hook(exc_type: type[BaseException], exc_value: BaseException, exc_tb: Any) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        logger.error(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        try:
            sys.__excepthook__(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _hook
