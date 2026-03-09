import logging
import time
from typing import Optional

from utils.logger import log_info, log_error

class LockController:
    """Класс для управления механическим замком"""
    
    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.is_locked = True
        self.logger = logging.getLogger(__name__)
        
    def unlock(self) -> bool:
        """Открывает замок"""
        try:
            # Здесь будет реализация открытия замка
            log_info("Отправка команды на открытие замка...", logger=self.logger)
            
            # Заглушка
            time.sleep(0.1)
            
            self.is_locked = False
            log_info("Замок успешно открыт", logger=self.logger)
            return True
            
        except Exception as e:
            log_error(f"Ошибка при открытии замка: {e}", logger=self.logger)
            return False
    
    def lock(self) -> bool:
        """
        Закрывает замок

        Returns:
            bool: True если замок закрыт, иначе False
        """
        try:
            # Здесь будет реализация закрытия замка
            log_info("Отправка команды на закрытие замка...", logger=self.logger)
            
            # Заглушка
            time.sleep(0.1)
            
            self.is_locked = True
            log_info("Замок успешно закрыт", logger=self.logger)
            return True
            
        except Exception as e:
            log_error(f"Ошибка при закрытии замка: {e}", logger=self.logger)
            return False
    
    def is_unlocked(self) -> bool:
        """
        Проверяет, открыт ли замок
        
        Returns:
            bool: True если замок открыт, иначе False
        """
        return not self.is_locked


def initialize_lock_controller(config: Optional[dict] = None) -> LockController:
    """
    Инициализирует контроллер замка с заданной конфигурацией
    
    Args:
        config: Конфигурация для контроллера замка
        
    Returns:
        LockController: Экземпляр контроллера замка
    """
    return LockController(config)


if __name__ == "__main__":
    # Тестирование функционала замка
    lock = LockController()
    
    print(f"Замок изначально закрыт: {lock.is_locked}")
    
    if lock.unlock():
        print("Замок успешно открыт")
    
    if lock.lock():
        print("Замок успешно закрыт")
