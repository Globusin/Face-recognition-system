"""
Запуск основного приложения с функциональностью точки доступа
"""
import sys
import signal
import atexit
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.app import app
from utils.hotspot import start_hotspot
from utils.config_loader import load_config
from utils.logger import log_info, log_error

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

def create_hotsopt():
    config = load_config()
    hotspot_config = config.get('hotspot', {})
    ssid = hotspot_config.get('ssid', 'DoorApp')
    password = hotspot_config.get('password', '12345678')
    
    # start_hotspot(ssid, password)

def main():
    # Регистрируем функцию очистки
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, lambda s, f: cleanup())
    signal.signal(signal.SIGTERM, lambda s, f: cleanup())

    # Создаем точку доступа Wi-Fi
    log_info("Запуск точки доступа Wi-Fi")
    create_hotsopt()
    
    # Запускаем Flask-приложение
    log_info("Запуск Flask-приложения")
    app.run(host='0.0.0.0', port=5000, debug=False)

if __name__ == '__main__':
    main()
