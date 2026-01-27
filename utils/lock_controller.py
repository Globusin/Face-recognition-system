import logging
import time
from typing import Optional

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
            self.logger.info("Отправка команды на открытие замка...")
            
            # Заглушка
            time.sleep(0.1)
            
            self.is_locked = False
            self.logger.info("Замок успешно открыт")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при открытии замка: {e}")
            return False
    
    def lock(self) -> bool:
        """
        Закрывает замок

        Returns:
            bool: True если замок закрыт, иначе False
        """
        try:
            # Здесь будет реализация закрытия замка
            self.logger.info("Отправка команды на закрытие замка...")
            
            # Заглушка
            time.sleep(0.1)
            
            self.is_locked = True
            self.logger.info("Замок успешно закрыт")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии замка: {e}")
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