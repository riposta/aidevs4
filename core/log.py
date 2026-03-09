import logging
import sys

# ANSI colors
GREY = "\033[90m"
BLUE = "\033[34m"
CYAN = "\033[36m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
MAGENTA = "\033[35m"
BOLD = "\033[1m"
RESET = "\033[0m"


class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: GREY,
        logging.INFO: BLUE,
        logging.WARNING: YELLOW,
        logging.ERROR: RED,
        logging.CRITICAL: RED + BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        color = self.LEVEL_COLORS.get(record.levelno, RESET)
        # Custom attributes for structured output
        prefix = getattr(record, "prefix", "")
        if prefix:
            prefix = f"{BOLD}{prefix}{RESET} "
        msg = record.getMessage()
        return f"{GREY}{record.name}{RESET} {prefix}{color}{msg}{RESET}"


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"aidevs.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(ColorFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger
