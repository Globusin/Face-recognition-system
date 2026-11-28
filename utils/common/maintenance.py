"""Согласование калибровки и операций распознавания в одном процессе"""

import threading
from contextlib import contextmanager


class MaintenanceMode:
    def __init__(self):
        self.lock = threading.RLock()
        self.requested = threading.Event()
        self.door_open = threading.Event()
        self.stereo_measuring = threading.Event()
        self.timing_measuring = threading.Event()
        self.challenge_running = threading.Event()
        self.display = None

    def begin(self):
        if self.challenge_running.is_set():
            raise RuntimeError('Сначала завершите проверку заданиями')
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
            if self.challenge_running.is_set():
                raise RuntimeError('Сначала завершите проверку заданиями')
            self.requested.clear()

    @contextmanager
    def recognition(self):
        if self.requested.is_set():
            raise RuntimeError('Распознавание приостановлено для обслуживания')
        with self.lock:
            if self.requested.is_set():
                raise RuntimeError('Распознавание приостановлено для калибровки')
            yield


maintenance = MaintenanceMode()
