"""Logging setup. Every entry point calls `configure_logging()` once at startup."""

import logging
import os
import sys

HANDLER_NAME = "cfpb"
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
ENV_VAR = "CFPB_LOG_LEVEL"


def configure_logging(level: str | None = None) -> None:
    """Configure the root logger to write to stderr.

    Level precedence: `level` argument, then $CFPB_LOG_LEVEL, then INFO.
    Safe to call more than once: the handler is replaced, not duplicated.
    """
    name = (level or os.environ.get(ENV_VAR) or "INFO").upper()
    numeric = logging.getLevelNamesMapping().get(name)
    if numeric is None:
        raise ValueError(f"Unknown log level {name!r} (from argument or ${ENV_VAR})")

    root = logging.getLogger()
    for existing in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(existing)

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    root.addHandler(handler)
    root.setLevel(numeric)
