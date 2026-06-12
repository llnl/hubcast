import logging


class HubcastError(Exception):
    """
    Exception that stores context for future logging.
    """

    def __init__(self, message: str, log_level: str = "ERROR", **context):
        super().__init__(message)
        self.log_level = log_level.upper()
        self.context = context

    def log(self, logger: logging.Logger, **extra_context) -> None:
        """Log this exception with its context and any extra info."""
        level = getattr(logging, self.log_level)
        # Only include traceback for ERROR level and above
        exc_info = self.log_level in ("ERROR", "CRITICAL")
        logger.log(
            level, str(self), extra={**self.context, **extra_context}, exc_info=exc_info
        )
