"""Logging setup with console output for reasoning steps."""

import logging
import sys
from typing import Optional

from .config import LoggingConfig


# Custom log levels for agent reasoning
REASONING = 25  # Between INFO and WARNING
logging.addLevelName(REASONING, "REASONING")


class ColoredFormatter(logging.Formatter):
    """Formatter that adds colors to console output."""

    COLORS = {
        "DEBUG": "\033[36m",      # Cyan
        "INFO": "\033[32m",       # Green
        "REASONING": "\033[35m",  # Magenta
        "WARNING": "\033[33m",    # Yellow
        "ERROR": "\033[31m",      # Red
        "CRITICAL": "\033[41m",   # Red background
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


def setup_logging(config: Optional[LoggingConfig] = None) -> logging.Logger:
    """
    Set up logging with console output.

    Args:
        config: Logging configuration. Uses defaults if None.

    Returns:
        Configured logger instance.
    """
    if config is None:
        config = LoggingConfig()

    # Create logger
    logger = logging.getLogger("sre_agent")
    logger.setLevel(getattr(logging, config.level.upper(), logging.INFO))

    # Remove existing handlers
    logger.handlers = []

    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColoredFormatter(config.format))
    logger.addHandler(console_handler)

    # Add reasoning method to logger
    def reasoning(self, message: str, *args, **kwargs):
        """Log agent reasoning steps."""
        if self.isEnabledFor(REASONING):
            self._log(REASONING, message, args, **kwargs)

    logging.Logger.reasoning = reasoning

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Get a logger instance."""
    if name:
        return logging.getLogger(f"sre_agent.{name}")
    return logging.getLogger("sre_agent")


def log_step(logger: logging.Logger, step: str, details: Optional[str] = None) -> None:
    """Log a major step in the agent's process."""
    separator = "=" * 60
    logger.info(separator)
    logger.info(f"STEP: {step}")
    if details:
        logger.info(f"Details: {details}")
    logger.info(separator)


def log_reasoning(logger: logging.Logger, thought: str) -> None:
    """Log agent reasoning/thought process."""
    logger.log(REASONING, f"🤔 {thought}")


def log_action(logger: logging.Logger, action: str, result: Optional[str] = None) -> None:
    """Log an action being taken."""
    logger.info(f"🔧 Action: {action}")
    if result:
        logger.info(f"   Result: {result}")


def log_success(logger: logging.Logger, message: str) -> None:
    """Log a success message."""
    logger.info(f"✅ {message}")


def log_error(logger: logging.Logger, message: str) -> None:
    """Log an error message."""
    logger.error(f"❌ {message}")


def log_warning(logger: logging.Logger, message: str) -> None:
    """Log a warning message."""
    logger.warning(f"⚠️  {message}")
