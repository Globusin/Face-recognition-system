"""Согласование калибровки и операций распознавания в одном процессе"""

import threading
from contextlib import contextmanager


class MaintenanceMode:
    def __init__(self):
        self.lock = threading.RLock()
        self.requested = threading.Event()
        self.door_open = threading.Event()
        self.stereo_measuring = threading.Event()

    def begin(self):
        self.requested.set()
        if not self.lock.acquire(timeout=20):
            self.requested.clear()
            raise RuntimeError('Текущая попытка ещё не завершена, повторите позже')
        try:
            if self.door_open.is_set():
                self.requested.clear()
                raise RuntimeError('Дождитесь закрытия замка')
        finally:
            self.lock.release()

    def end(self):
        with self.lock:
            self.requested.clear()

    @contextmanager
    def recognition(self):
        with self.lock:
            if self.requested.is_set():
                raise RuntimeError('Распознавание приостановлено для калибровки')
            yield


maintenance = MaintenanceMode()
