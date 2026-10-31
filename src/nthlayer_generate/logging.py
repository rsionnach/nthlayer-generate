import logging
import os
import sys
from typing import Any

import structlog


def _colour_on_stderr() -> bool:
    """Colour only for a live terminal, and never when NO_COLOR is set.

    sys.stderr is None when fd 2 is closed (``2>&-``), and isatty() raises on a
    closed stream; either must mean "no colour", not a crash before the
    command prints its output. NO_COLOR follows https://no-color.org: present
    and not empty disables colour. Passing colors= to ConsoleRenderer
    overrides structlog's own NO_COLOR handling, so it is checked here.
    """
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stderr is not None and sys.stderr.isatty())
    except ValueError:
        return False


def configure_logging(level: int | str = logging.INFO) -> None:
    """Route structlog through stdlib logging to stderr, human-readable.

    The CLI calls this at startup (demo.main) so that stdout carries only a
    command's output (opensrm-iiay). The line format matches what users saw
    before, when structlog's default logger printed to stdout: a console line
    with the message's %-style arguments filled in. Colour only on a terminal
    (see _colour_on_stderr).
    Fewer lines appear: the CLI passes WARNING (INFO with -v), where the
    unconfigured default printed DEBUG.
    """

    timestamper = structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.add_log_level,
            timestamper,
            structlog.processors.StackInfoRenderer(),
            # No format_exc_info: ConsoleRenderer formats exc_info itself, and
            # warns on every exception log when a processor already has.
            # plain_traceback, not structlog's rich default: that one prints
            # local variables (which can hold API keys) and colour codes even
            # when stderr is not a terminal.
            structlog.dev.ConsoleRenderer(
                colors=_colour_on_stderr(),
                exception_formatter=structlog.dev.plain_traceback,
            ),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)


def bind_context(**kwargs: Any) -> structlog.stdlib.BoundLogger:
    """Bind contextual fields for downstream logs."""

    logger = structlog.get_logger()
    return logger.bind(**kwargs)
