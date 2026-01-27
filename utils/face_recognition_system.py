import logging
import time
from typing import Optional, Tuple
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import recognize_face_from_camera
from utils.lock_controller import initialize_lock_controller, LockController
from utils.config_loader import load_config


class FaceRecognitionSystem:
    """Основной класс системы распознавания лиц с управлением замком"""
    
    def __init__(self, config_path: Optional[str] = None):
        self.config = load_config()
        self.lock_controller = initialize_lock_controller(self.config.get('lock', {}))
        self.logger = logging.getLogger(__name__)
        self.running = False
        
        # Настройка логирования
        logging.basicConfig(
            level=self.config.get('logging', {}).get('level', 'INFO'),
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    
    def authenticate_user(self) -> Tuple[bool, Optional[int], Optional[float]]:
        """Аутентифицирует пользователя по лицу"""

        self.logger.info("Начало процесса аутентификации пользователя")
        
        try:
            is_recognized, user_id, distance = recognize_face_from_camera()
            
            if is_recognized:
                self.logger.info(f"Пользователь распознан: ID {user_id}, расстояние {distance:.4f}")
                return True, user_id, distance
            else:
                self.logger.info("Пользователь не распознан или лицо не обнаружено")
                return False, None, None
                
        except Exception as e:
            self.logger.error(f"Ошибка при аутентификации пользователя: {e}")
            return False, None, None
    
    def process_authentication(self) -> bool:
        """Запускает аутентификацию и открывает замок при успехе"""

        is_authenticated, user_id, distance = self.authenticate_user()
        
        if is_authenticated:
            self.logger.info(f"Пользователь распознан, id вектора: {user_id}")
            
            if self.lock_controller.unlock():
                self.logger.info("Замок успешно открыт")
                
                door_open_time = self.config.get('door_open_time', 5)
                time.sleep(door_open_time)
                
                if self.lock_controller.lock():
                    self.logger.info("Замок успешно закрыт")
                    return True
                else:
                    self.logger.error("Ошибка при закрытии замка")
                    return False
            else:
                self.logger.error("Ошибка при открытии замка")
                return False
        else:
            self.logger.warning("Аутентификация не удалась, замок остается закрытым")
            return False
    
    def start_infinity_monitoring(self):
        """Запускает непрерывный режим мониторинга для распознавания лиц"""

        self.logger.info("Запуск непрерывного режима мониторинга")
        self.running = True
        
        detection_interval = self.config.get('detection_interval', 2)
        
        try:
            while self.running:
                self.process_authentication()
                time.sleep(detection_interval)
                
        except KeyboardInterrupt:
            self.logger.info("Остановка непрерывного режима мониторинга по запросу пользователя")
        except Exception as e:
            self.logger.error(f"Ошибка в непрерывном режиме мониторинга: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """Останавливает систему"""
        self.logger.info("Остановка системы распознавания лиц")
        self.running = False
        
        if not self.lock_controller.is_locked:
            if self.lock_controller.lock():
                self.logger.info("Замок закрыт при завершении работы системы")
            else:
                self.logger.error("Не удалось закрыть замок при завершении работы системы")
    
    def test_mode(self):
        """Режим тестирования системы"""
        self.logger.info("Запуск тестового режима")
        
        print("Тестирование системы распознавания лиц")
        
        is_authenticated, user_id, distance = self.authenticate_user()
        
        if is_authenticated:
            print(f"Пользователь аутентифицирован: ID {user_id}, уверенность {1-distance:.2%}")
            print("Тест открытия замка")
            
            if self.lock_controller.unlock():
                print("Замок успешно открыт")
                time.sleep(2)
                
                if self.lock_controller.lock():
                    print("Замок успешно закрыт")
                    print("Тестирование завершено успешно")
                    return True
                else:
                    print("Ошибка при закрытии замка")
                    return False
            else:
                print("Ошибка при открытии замка")
                return False
        else:
            print("Пользователь не распознан")
            return True


def initialize_face_recognition_system(config_path: Optional[str] = None) -> FaceRecognitionSystem:
    """
    Инициализирует систему распознавания лиц
    
    Args:
        config_path: Путь к конфигурационному файлу (опционально)
        
    Returns:
        FaceRecognitionSystem: Экземпляр системы распознавания лиц
    """
    return FaceRecognitionSystem(config_path)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Система распознавания лиц с управлением замком')
    parser.add_argument('--mode', choices=['test', 'continuous'], default='test', help='Режим работы: test (тестовый) или continuous (непрерывный мониторинг)')
    
    args = parser.parse_args()
    
    system = initialize_face_recognition_system()
    
    if args.mode == 'test':
        system.test_mode()
    elif args.mode == 'continuous':
        print("Запуск непрерывного режима мониторинга. Нажмите Ctrl+C для остановки.")
        system.start_infinity_monitoring()