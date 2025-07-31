"""

This module implements a logger to be used within this package
"""

import logging
import os
import time


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    if os.getenv("LOG_LEVEL") == "DEBUG":
        format = "%(asctime)s | %(threadName)s | %(levelname)s | %(message)s | (%(filename)s:%(lineno)d)"
    else:
        format = "%(asctime)s | %(threadName)s | %(levelname)s | %(message)s"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def configure_logger(logger_name):
    # Create logger and define INFO as the log level
    logger = logging.getLogger(f"{logger_name}{time.time_ns()}")
    log_level = os.environ.get("LOG_LEVEL", logging.INFO)
    logger.setLevel(log_level)
    # logger.propagate = False

    # Create our stream handler and apply the formatting
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(CustomFormatter())

    # Add the stream handler to the logger
    logger.addHandler(stream_handler)

    return logger
