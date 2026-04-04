import logging
import os
from datetime import datetime
from config import LOGS_DIR, LOG_LEVEL

log_levels = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}


def get_logger(name: str = "roleplay_rpg"):
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    level = log_levels.get(LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    log_file = LOGS_DIR / f"game_{datetime.now().strftime('%Y%m%d')}.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    )

    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    if level == logging.DEBUG:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    return logger
