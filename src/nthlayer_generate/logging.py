import logging
import sys
from typing import Any

import structlog


def configure_logging(level: int | str = logging.INFO) -> None:
    """Route structlog through stdlib logging to stderr, human-readable.

    The CLI calls this at startup (demo.main) so that stdout carries only a
    command's output (opensrm-iiay). The line format matches what users saw
    before, when structlog's default logger printed to stdout: a console line
    with the message's %-style arguments filled in. Colour only on a terminal.
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
                colors=sys.stderr.isatty(),
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
