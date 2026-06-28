"""Enterprise logging configuration.

Two complementary log streams exist in the system:

* **Application logs** (this module) — rotating text files plus console output,
  capturing technical events and tracebacks for support/debugging. Stored
  locally under ``%LOCALAPPDATA%``.
* **System logs** (:mod:`eqms.data.logs_store`) — a structured business audit
  trail (who did what, when) persisted to ``SystemLogs.xlsx`` on SharePoint.

Call :func:`configure_logging` exactly once at application start-up.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from .. import config

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def configure_logging(level: int = logging.INFO) -> logging.Logger:
    """Initialise root logging handlers. Idempotent.

    Parameters
    ----------
    level:
        Minimum level for the root logger. Defaults to ``INFO``; set ``DEBUG``
        when troubleshooting (the Admin Center exposes this at runtime).

    Returns
    -------
    logging.Logger
        The configured application root logger (``"eqms"``).
    """
    global _configured

    app_logger = logging.getLogger("eqms")
    if _configured:
        app_logger.setLevel(level)
        return app_logger

    config.ensure_directories()
    log_file: Path = config.LOG_DIR / "eqms.log"

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Rotating file handler: 2 MB per file, keep 10 historical files.
    file_handler = logging.handlers.RotatingFileHandler(
        log_file, maxBytes=2 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    app_logger.setLevel(logging.DEBUG)
    app_logger.addHandler(file_handler)

    # Console handler — only when a real stdout exists. A windowed PyInstaller
    # build (console=False) sets sys.stdout/sys.stderr to None; attaching a
    # StreamHandler to None makes every log emit raise internally, so we skip it.
    if sys.stdout is not None:
        console_handler = logging.StreamHandler(stream=sys.stdout)
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)
        app_logger.addHandler(console_handler)

    app_logger.propagate = False

    # Quieten chatty third-party libraries.
    for noisy in ("urllib3", "msal", "office365", "matplotlib", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    app_logger.info("Logging initialised. Log file: %s", log_file)
    return app_logger


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child logger, e.g. ``get_logger(__name__)``.

    All application modules should obtain their logger through this helper so
    everything sits under the ``eqms`` hierarchy and shares the configured
    handlers.
    """
    if not name.startswith("eqms"):
        name = f"eqms.{name}"
    return logging.getLogger(name)
