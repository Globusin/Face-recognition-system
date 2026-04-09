#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
monitor.py - Непрерывный мониторинг для системы распознавания лиц

Функционал:
- Получение изображения с камеры
- Распознавание лица
- Открытие замка при успешной аутентификации (замок замокан)
"""

import sys
import time
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import recognize_face_from_camera
from utils.lock_controller import initialize_lock_controller
from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_warning, log_debug


def run_monitoring():
    """
    Запускает непрерывный мониторинг камеры для распознавания лиц
    и управления замком.
    """
    # Загружаем конфигурацию
    config = load_config()
    
    # Инициализируем контроллер замка
    lock_controller = initialize_lock_controller(config)
    
    # Получаем параметры из конфигурации
    detection_interval = config.get('detection_interval', 2)
    door_open_time = config.get('door_open_time', 5)
    
    log_info("=" * 50)
    log_info("Запуск системы непрерывного мониторинга")
    log_info(f"Интервал проверки: {detection_interval} сек.")
    log_info(f"Время открытия двери: {door_open_time} сек.")
    log_info("=" * 50)
    
    # Флаг состояния замка (чтобы не открывать повторно)
    is_door_open = False
    last_success_time = 0
    
    try:
        while True:
            current_time = time.time()
            
            # Проверяем, нужно ли закрыть дверь после открытия
            if is_door_open and (current_time - last_success_time) >= door_open_time:
                log_info("Автоматическое закрытие замка...")
                lock_controller.lock()
                is_door_open = False
                log_info("Замок закрыт")
            
            # Если дверь открыта, пропускаем проверку
            if is_door_open:
                time.sleep(0.5)
                continue
            
            # Попытка распознавания лица
            log_debug("Выполнение проверки распознавания лица...")
            is_authenticated, user_id, distance = recognize_face_from_camera()
            
            if is_authenticated:
                log_info(f"✓ Лицо распознано! User ID: {user_id}, Distance: {distance:.4f}")
                
                # Открываем замок
                log_info("Открытие замка...")
                if lock_controller.unlock():
                    log_info("✓ Замок успешно открыт (замок замокан)")
                    is_door_open = True
                    last_success_time = current_time
                    
                    # Логирование события доступа
                    log_info(f"Доступ предоставлен пользователю {user_id}")
                else:
                    log_error("✗ Ошибка при открытии замка")
            else:
                log_debug("Лицо не распознано или не найдено в базе данных")
            
            # Ждем перед следующей проверкой
            time.sleep(detection_interval)
            
    except KeyboardInterrupt:
        log_info("\nПолучен сигнал прерывания (Ctrl+C)")
        log_info("Остановка мониторинга...")
        
        # Убеждаемся, что замок закрыт при остановке
        if is_door_open:
            log_info("Закрытие замка перед выходом...")
            lock_controller.lock()
        
        log_info("Мониторинг остановлен")
        
    except Exception as e:
        log_error(f"Критическая ошибка в цикле мониторинга: {e}")
        raise


if __name__ == "__main__":
    run_monitoring()
