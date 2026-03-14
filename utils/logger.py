import logging
import sys
from datetime import datetime
from pathlib import Path

# Настройка глобального логирования
def setup_logger(name=__name__, level=logging.INFO, log_file=None):
    """
    Создает и настраивает логгер с заданными параметрами
    
    Args:
        name (str): Имя логгера
        level: Уровень логирования
        log_file (str): Путь к файлу лога (опционально)
        
    Returns:
        logging.Logger: Настроенный логгер
    """
    logger = logging.getLogger(name)
    
    # Избегаем дублирования хендлеров
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # Формат сообщений
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Хендлер для вывода в консоль
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Хендлер для записи в файл (если указан путь)
    if log_file:
        # Создаем директорию для логов, если её нет
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def log_info(message, logger=None, name=__name__):
    """
    Логирует информационное сообщение
    
    Args:
        message (str): Сообщение для логирования
        logger: Экземпляр логгера (опционально)
        name (str): Имя логгера, если logger не передан
    """
    if logger is None:
        logger = setup_logger(name=name)
    logger.info(message)


def log_warning(message, logger=None, name=__name__):
    """
    Логирует предупреждение
    
    Args:
        message (str): Сообщение для логирования
        logger: Экземпляр логгера (опционально)
        name (str): Имя логгера, если logger не передан
    """
    if logger is None:
        logger = setup_logger(name=name)
    logger.warning(message)


def log_error(message, logger=None, name=__name__):
    """
    Логирует ошибку
    
    Args:
        message (str): Сообщение для логирования
        logger: Экземпляр логгера (опционально)
        name (str): Имя логгера, если logger не передан
    """
    if logger is None:
        logger = setup_logger(name=name)
    logger.error(message)


def log_debug(message, logger=None, name=__name__):
    """
    Логирует отладочное сообщение
    
    Args:
        message (str): Сообщение для логирования
        logger: Экземпляр логгера (опционально)
        name (str): Имя логгера, если logger не передан
    """
    if logger is None:
        logger = setup_logger(name=name)
    logger.debug(message)


def log_critical(message, logger=None, name=__name__):
    """
    Логирует критическую ошибку
    
    Args:
        message (str): Сообщение для логирования
        logger: Экземпляр логгера (опционально)
        name (str): Имя логгера, если logger не передан
    """
    if logger is None:
        logger = setup_logger(name=name)
    logger.critical(message)