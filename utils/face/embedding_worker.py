"""Долгоживущий процесс dlib: камеры, БД и замок остаются в Monitor."""

import multiprocessing
import time

from utils.common.logger import log_info, log_warning
from utils.common.timing import measure_time


def _embedding_process(connection):
    try:
        # Модель загружается один раз в отдельном интерпретаторе.
        from utils.face.recognition import get_embeddings_from_frame
        connection.send(('ready', None))
        while True:
            job = connection.recv()
            if job is None:
                return
            frame, face_box = job
            try:
                result = get_embeddings_from_frame(frame, face_box)
                connection.send(('result', result))
            except Exception as error:
                connection.send(('error', f'{type(error).__name__}: {error}'))
    except (EOFError, BrokenPipeError):
        pass
    finally:
        connection.close()


class EmbeddingWorker:
    """Один потребитель, не более одного задания; отменённый ответ отбрасывается."""

    def __init__(self):
        # Нельзя fork из потока Gunicorn с уже открытыми камерами/блокировками.
        self.context = multiprocessing.get_context('spawn')
        self.process = None
        self.connection = None
        self.pending_since = None

    def start(self, check=None):
        if self.process is not None and self.process.is_alive():
            return
        self.close()
        parent, child = self.context.Pipe()
        process = self.context.Process(
            target=_embedding_process, args=(child,), name='FaceEmbedding', daemon=True,
        )
        self.connection = parent
        try:
            process.start()
            self.process = process
        except BaseException:
            parent.close()
            self.connection = None
            raise
        finally:
            child.close()
        try:
            status, _ = self._receive(time.monotonic() + 30.0, check)
            if status != 'ready':
                raise RuntimeError('Процесс dlib не подтвердил готовность')
        except BaseException:
            self.close()
            raise
        log_info(f'Процесс dlib готов: PID {process.pid}')

    def _receive(self, deadline, check):
        while True:
            if check is not None:
                check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Истекло время ожидания процесса dlib')
            if self.connection.poll(min(0.05, remaining)):
                return self.connection.recv()
            if not self.process.is_alive():
                raise RuntimeError('Процесс dlib завершился')

    def compute(self, frame, face_box, check):
        """Проверяет отмену, пока дочерний процесс вычисляет эмбеддинг."""
        with measure_time('Проверка и запуск процесса dlib'):
            self.start(check)
        try:
            # Если прошлую сессию отменили, её результат не попадёт в новую.
            if self.pending_since is not None:
                with measure_time('Ожидание результата прошлой сессии'):
                    self._receive(self.pending_since + 10.0, check)
                self.pending_since = None
            check()
            with measure_time('Формирование эмбеддингов (процесс dlib)'):
                self.pending_since = time.monotonic()
                self.connection.send((frame, face_box))
                status, result = self._receive(self.pending_since + 10.0, check)
                self.pending_since = None
            check()
            if status != 'result':
                raise RuntimeError(f'Ошибка процесса dlib: {result}')
            return result
        except (EOFError, OSError, RuntimeError) as error:
            # ObservationRejected тоже наследуется от RuntimeError.
            # При отмене сессии оставляем работающий процесс: старый ответ
            # будет отброшен перед следующим заданием.
            from utils.face.face_observations import ObservationRejected
            if not isinstance(error, ObservationRejected):
                log_warning(f'Процесс dlib: {error}')
                self.close()
            raise

    def close(self):
        process, connection = self.process, self.connection
        self.process = self.connection = self.pending_since = None
        if connection is not None:
            connection.close()
        if process is not None:
            process.join(timeout=0.2)
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)
            if process.is_alive():
                process.kill()
                process.join(timeout=1.0)
            if not process.is_alive():
                process.close()
