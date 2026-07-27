import contextvars
import datetime as dt
import json
import logging
from typing import Any

LOG_RECORD_BUILTIN_ATTRS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)

# Context dict to store request metadata for inclusion in logs
log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "log_context", default=None
)


def update_log_context(**fields):
    """Add or update fields in the log context."""
    current = log_context.get() or {}
    log_context.set({**current, **fields})


class HubcastJSONFormatter(logging.Formatter):
    def __init__(self, *, fmt_keys: dict[str, str] | None = None) -> None:
        super().__init__()
        self.fmt_keys = fmt_keys or {}

    def format(self, record: logging.LogRecord) -> str:
        record_dict = record.__dict__

        # fields that are only included
        log_data = {
            "timestamp": dt.datetime.fromtimestamp(record.created, tz=dt.UTC).isoformat(
                timespec="microseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
        }

        # exclude suppressed messages
        if not (record.name == "aiohttp.access" and "message" in self.fmt_keys):
            log_data["message"] = record.getMessage()

        # add exception info
        if record.exc_info:
            log_data["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            log_data["stack_info"] = self.formatStack(record.stack_info)

        # map additional fields via fmt_keys
        for output_key, attr_name in self.fmt_keys.items():
            if output_key in log_data:
                continue  # already populated
            if hasattr(record, attr_name):
                log_data[output_key] = getattr(record, attr_name)

        # add any user-defined extra fields (from logger(..., extra={...}))
        for key, val in record_dict.items():
            if key not in LOG_RECORD_BUILTIN_ATTRS and key not in log_data:
                log_data[key] = val

        return json.dumps(log_data, default=str)


class HubcastConsoleFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        logger = logging.getLogger(record.name)
        show_traceback = logger.isEnabledFor(logging.DEBUG)

        # temporarily suppress traceback if we're not in DEBUG mode
        original_exc_info = record.exc_info
        if not show_traceback:
            record.exc_info = None

        # format the base log line
        try:
            base = super().format(record)
        finally:
            # always restore exc_info after formatting
            record.exc_info = original_exc_info

        # skip extras for aiohttp.access since they provide redundant info
        if record.name == "aiohttp.access":
            return base

        # add any user-defined extra fields
        extras = {
            k: v
            for k, v in record.__dict__.items()
            if k not in LOG_RECORD_BUILTIN_ATTRS
        }

        # format extras

        if extras:
            extra_str = " " + " ".join(f"{k}={v}" for k, v in extras.items())
        else:
            extra_str = ""

        return base + extra_str


class RequestContextFilter(logging.Filter):
    """Adds all fields from log_context to all logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        context_data = log_context.get() or {}
        for key, value in context_data.items():
            setattr(record, key, value)
        return True
