"""Журнал доступов и отказов без изображений и embeddings"""

import json
import queue
import threading
import time
from pathlib import Path

from utils.common.logger import log_error
from utils.storage.db_connect import add_audit_record, get_audit_records


class AuditLog:
    """Append-only JSONL с ограничением размера и чтением последних записей"""

    def __init__(self, path, max_bytes=2_000_000):
        self.path = Path(path)
        self.max_bytes = max(1, int(max_bytes))
        self._lock = threading.Lock()

    def append(self, record):
        try:
            line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError) as error:
            log_error(f'Аудит: запись не сериализуется: {error}')
            return
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self._rotate_if_needed()
                with self.path.open('a', encoding='utf-8') as file:
                    file.write(line + '\n')
            except OSError as error:
                # Сбой журнала не должен мешать решению о доступе
                log_error(f'Аудит: не удалось записать решение: {error}')

    def read(self, limit=50, decision=None, kind=None):
        limit = min(max(int(limit), 1), 500)
        records = []
        with self._lock:
            try:
                lines = self.path.read_text(encoding='utf-8').splitlines()
            except OSError:
                return []
        for line in lines:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            if decision and record.get('decision') != decision:
                continue
            if kind and record.get('type', 'session') != kind:
                continue
            records.append(record)
        return list(reversed(records[-limit:]))

    def _rotate_if_needed(self):
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        backup = self.path.with_name(self.path.name + '.1')
        try:
            backup.unlink(missing_ok=True)
            self.path.replace(backup)
        except OSError:
            # Ротация не должна мешать записи нового решения
            pass


class PostgresAudit:
    """Основной журнал в PostgreSQL; запись не блокирует конвейер

    Запись уходит в ограниченную очередь и выполняется отдельным потоком,
    чтобы недоступная БД не задерживала закрытие замка. Ошибки журнала
    логируются и не влияют на решение о доступе.
    """

    def __init__(self, queue_size=1000):
        self._queue = queue.Queue(maxsize=max(1, int(queue_size)))
        self._lock = threading.Lock()
        self._thread = None
        self._pending = 0

    def append(self, record):
        self._ensure_worker()
        with self._lock:
            self._pending += 1
        try:
            self._queue.put_nowait(record)
        except queue.Full:
            with self._lock:
                self._pending -= 1
            log_error('Аудит: очередь переполнена, запись потеряна')

    def read(self, limit=50, decision=None, kind=None):
        # Ошибку чтения обрабатывает API: пустой список скрыл бы сбой БД
        return get_audit_records(limit=limit, decision=decision, kind=kind)

    def flush(self, timeout=2.0):
        """Ждёт записи очереди не дольше таймаута; нужен для тестов и остановки"""
        deadline = time.monotonic() + timeout
        while True:
            with self._lock:
                if self._pending <= 0:
                    return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.01)

    def _ensure_worker(self):
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._run, name='audit-writer', daemon=True,
            )
            self._thread.start()

    def _run(self):
        while True:
            record = self._queue.get()
            try:
                add_audit_record(record)
            except Exception as error:
                log_error(f'Аудит: не удалось записать в БД: {error}')
            finally:
                with self._lock:
                    self._pending -= 1
                self._queue.task_done()
