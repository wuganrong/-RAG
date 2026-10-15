# logger.py

import logging

def get_logger(name):
    """
    Creates a logger with the specified name.

    Args:
        name (str): The name of the logger.

    Returns:
        Logger: Configured logger instance.
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        # Console handler
        c_handler = logging.StreamHandler()
        c_handler.setLevel(logging.INFO)

        # File handler
        import os

        from __000__common.__001__path import get_file_path

        log_dir = get_file_path("data/logs")
        os.makedirs(log_dir, exist_ok=True)
        f_handler = logging.FileHandler(os.path.join(log_dir, "app.log"), encoding="utf-8")
        f_handler.setLevel(logging.DEBUG)

        # Create formatters and add them to handlers
        c_format = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        f_format = logging.Formatter('%(asctime)s - %(levelname)s - %(name)s - %(message)s')
        c_handler.setFormatter(c_format)
        f_handler.setFormatter(f_format)

        # Add handlers to the logger
        logger.addHandler(c_handler)
        logger.addHandler(f_handler)

    return logger
