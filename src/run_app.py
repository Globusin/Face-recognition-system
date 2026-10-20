"""
Запуск основного приложения с функциональностью точки доступа
"""
import sys
import signal
import atexit
import threading
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from src.app import app
from utils.hotspot import start_hotspot
from utils.config_loader import load_config
from utils.logger import log_info, log_error
from utils.camera_manager import stop_camera_manager
from src.monitor import run_monitoring

monitor_stop_event = threading.Event()
monitor_thread = None
cleanup_started = False

def cleanup():
    """Останавливает монитор и освобождает камеры"""
    global cleanup_started
    if cleanup_started:
        return
    cleanup_started = True

    monitor_stop_event.set()
    stop_camera_manager()

    if monitor_thread and monitor_thread.is_alive():
        monitor_thread.join(timeout=3)


def handle_signal(signum, frame):
    del signum, frame
    cleanup()
    raise SystemExit(0)

def create_hotsopt():
    config = load_config()
    hotspot_config = config.get('hotspot', {})
    ssid = hotspot_config.get('ssid', 'DoorApp')
    password = hotspot_config.get('password', '12345678')
    
    start_hotspot(ssid, password)

def main():
    global monitor_thread

    # Регистрируем функцию очистки
    atexit.register(cleanup)
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    # Создаем точку доступа Wi-Fi
    log_info("Запуск точки доступа Wi-Fi")
    # create_hotsopt()
    
    # Монитор и Flask работают в одном процессе и используют общий CameraManager
    monitor_thread = threading.Thread(
        target=run_monitoring,
        args=(monitor_stop_event,),
        name='access-monitor',
        daemon=True,
    )
    monitor_thread.start()

    # Запускаем Flask-приложение
    log_info("Запуск Flask-приложения")
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)

if __name__ == '__main__':
    main()
