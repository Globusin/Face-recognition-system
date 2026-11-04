"""
Запуск основного приложения с функциональностью точки доступа
"""
import sys
import atexit
import threading
import ssl
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


def create_hotsopt():
    config = load_config()
    hotspot_config = config.get('hotspot', {})
    ssid = hotspot_config.get('ssid', 'DoorApp')
    password = hotspot_config.get('password', '12345678')
    
    start_hotspot(ssid, password)

def start_monitor(worker):
    del worker
    global monitor_thread
    # Поток создаётся внутри единственного worker, а не до fork
    atexit.register(cleanup)
    monitor_thread = threading.Thread(
        target=run_monitoring,
        args=(monitor_stop_event,),
        name='access-monitor',
        daemon=True,
    )
    monitor_thread.start()


def tls_context(config, factory):
    context = factory()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def server_options():
    root = Path(__file__).resolve().parent.parent
    settings = load_config().get('server', {})
    cert = root / settings.get('cert_file', 'data/security/server.crt')
    key = root / settings.get('key_file', 'data/security/server.key')
    # Ошибка сертификата останавливает запуск, перехода на HTTP нет
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    if not (root / 'Face-Recognition-Vue/dist/index.html').is_file():
        raise RuntimeError('Сначала соберите Vue: npm --prefix Face-Recognition-Vue run build')
    return dict(bind=f'{settings.get("host", "0.0.0.0")}:{int(settings.get("port", 8443))}',
                workers=1, worker_class='gthread', threads=4, timeout=240, graceful_timeout=15,
                certfile=str(cert), keyfile=str(key), ssl_context=tls_context,
                forwarded_allow_ips='', secure_scheme_headers={},
                post_worker_init=start_monitor, worker_exit=lambda server, worker: cleanup(),
                accesslog=None)


def main():
    from gunicorn.app.base import BaseApplication

    options = server_options()

    class HttpsApplication(BaseApplication):
        def load_config(self):
            for name, value in options.items():
                self.cfg.set(name, value)

        def load(self):
            return app

    log_info(f'Запуск HTTPS: {options["bind"]}')
    HttpsApplication().run()

if __name__ == '__main__':
    main()
