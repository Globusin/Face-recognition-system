#!/usr/bin/env python3
"""
Запуск основного приложения с функциональностью точки доступа
"""
import sys
import signal
import atexit
from pathlib import Path

# Добавляем путь к директории src для правильного импорта
sys.path.append(str(Path(__file__).parent))

from app import app, create_wifi_hotspot
from utils.captive_portal import setup_captive_portal

# Список активных процессов для корректного завершения
active_processes = []

def cleanup():
    """Функция очистки при завершении приложения"""
    global active_processes
    for proc in active_processes:
        try:
            proc.terminate()
        except:
            pass

def main():
    # Регистрируем функцию очистки
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: cleanup())
    signal.signal(signal.SIGTERM, lambda s, f: cleanup())

    print("Запуск системы аутентификации с точкой доступа...")
    
    # Создаем точку доступа Wi-Fi
    print("Создание точки доступа...")
    create_wifi_hotspot()
    
    # Настраиваем captive portal
    # print("Настройка captive portal...")
    # setup_captive_portal()
    
    print("Запуск Flask-приложения на порту 5000...")
    print("Подключитесь к точке доступа 'SmartDoor-Auth' с паролем '12345678'")
    print("Откройте браузер и перейдите по любому адресу для аутентификации")
    
    # Запускаем Flask-приложение
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    main()