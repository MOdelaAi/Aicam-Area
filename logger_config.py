import logging
from logging.handlers import RotatingFileHandler


class MaxLevelFilter(logging.Filter):
    def __init__(self, level):
        self.level = level
    def filter(self, record):
        return record.levelno < self.level  # ตัวนี้จะผ่านเฉพาะ log ที่ต่ำกว่า ERROR


def setup_logger(name=None):
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    
    if not logger.handlers:
        # === Handler 1: Log ปกติ ===
        info_handler = RotatingFileHandler(
            "app.log", maxBytes=10*1024*1024, backupCount=3
        )
        info_handler.setLevel(logging.INFO)  # log >= INFO
        info_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        info_handler.setFormatter(info_format)
        info_handler.addFilter(MaxLevelFilter(logging.ERROR))
        
        # === Handler 2: Log เฉพาะ ERROR ขึ้นไป ===
        error_handler = RotatingFileHandler(
            "error.log", maxBytes=5*1024*1024, backupCount=2
        )
        error_handler.setLevel(logging.ERROR)  # log >= ERROR
        error_format = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        error_handler.setFormatter(error_format)

        # เพิ่มทั้งสอง handler เข้า logger
        logger.addHandler(info_handler)
        logger.addHandler(error_handler)
        logger.addHandler(console_handler) # It will close the console handler if production is launched

    return logger

