"""Свежие наблюдения лица для одной попытки аутентификации"""

import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from utils.capture.camera_manager import CameraUnavailableError
from utils.capture.face_detection_preview import face_detection_preview
from utils.capture.frame_pairing import CameraFrame, FramePair
from utils.capture.video_capture import detect_faces
from utils.capture.camera_manager import CameraManager
from utils.common.logger import log_debug, log_warning


CAPTURE_POLL_SECONDS = 0.1


class ObservationRejected(RuntimeError):
    """Причина безопасного завершения текущего трека"""


@dataclass
class FaceObservation:
    primary: CameraFrame
    face_box: tuple
    track_id: str
    pair: Optional[FramePair] = None


def box_overlap(first, second):
    """Возвращает IoU двух прямоугольников (x, y, width, height)"""
    x1, y1, width1, height1 = first
    x2, y2, width2, height2 = second
    intersection_width = max(0, min(x1 + width1, x2 + width2) - max(x1, x2))
    intersection_height = max(0, min(y1 + height1, y2 + height2) - max(y1, y2))
    intersection = intersection_width * intersection_height
    union = width1 * height1 + width2 * height2 - intersection
    return intersection / union if union > 0 else 0.0


class FaceObservationSource:
    """Переиспользует захват CameraManager, не создавая рабочих потоков

    Хранит только последнее наблюдение и номера уже просмотренных кадров
    Полная детекция на каждом выбранном кадре нужна для отказа при нескольких
    лицах; найденный ROI затем используется распознаванием без новой детекции
    """

    def __init__(self, manager:CameraManager, stop_event, cancel_event, settings=None, *,
                 detector=detect_faces, clock=time.monotonic):
        settings = settings or {}
        self.manager = manager
        self.stop_event = stop_event
        self.cancel_event = cancel_event
        self.detector = detector
        self.clock = clock
        self.max_age = float(settings.get('max_frame_age_seconds', 0.5))
        self.max_gap = float(settings.get('max_track_gap_seconds', 2.0))
        self.wait_timeout = float(settings.get('frame_wait_seconds', 1.0))
        self.min_overlap = float(settings.get('min_track_overlap', 0.25))
        for value in (self.max_age, self.max_gap, self.wait_timeout):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Интервалы наблюдений должны быть положительными')
        if not math.isfinite(self.min_overlap) or not 0 < self.min_overlap <= 1:
            raise ValueError('Порог перекрытия должен быть в диапазоне (0, 1]')
        self.last_sequence = 0
        self.last_secondary_sequence = 0
        self.last_pair = 0
        self.current = None
        self.started_at = self.clock()
        self.closed = threading.Event()

    def check_cancelled(self, deadline=None):
        if self.stop_event.is_set() or self.closed.is_set():
            raise ObservationRejected('stopped')
        if self.cancel_event.is_set():
            raise ObservationRejected('maintenance')
        if deadline is not None and self.clock() >= deadline:
            raise ObservationRejected('timeout')

    def _fresh(self, frame):
        age = self.clock() - frame.timestamp_ns / 1e9
        return 0 <= age <= self.max_age

    def _read(self, deadline=None, *, wait_deadline=None):
        if wait_deadline is None:
            wait_deadline = self.clock() + self.wait_timeout
        if deadline is not None:
            wait_deadline = min(wait_deadline, deadline)
        while self.clock() < wait_deadline:
            self.check_cancelled(deadline)
            # Короткое ожидание позволяет быстро замечать остановку и обслуживание
            timeout = min(CAPTURE_POLL_SECONDS, max(0, wait_deadline - self.clock()))
            pair = None
            if self.manager.dual_mode:
                pair = self.manager.get_pair(self.last_pair, timeout, latest=True)
                if pair is None:
                    continue
                self.last_pair = max(self.last_pair, pair.number)
                frame = pair.primary
                if pair.secondary.sequence <= self.last_secondary_sequence:
                    continue
                self.last_secondary_sequence = pair.secondary.sequence
                # Сравниваем время доставки, не неизвестное время экспозиции
                delta_ns = abs(frame.timestamp_ns - pair.secondary.timestamp_ns)
                if delta_ns > self.manager.pairer.max_delta_ns:
                    continue
                if not self._fresh(pair.secondary):
                    continue
            else:
                frame = self.manager.get_frame(
                    after_sequence=self.last_sequence, timeout=timeout, latest=True,
                )
                if frame is None:
                    continue
            if frame.sequence <= self.last_sequence:
                continue
            self.last_sequence = frame.sequence
            if frame.timestamp_ns / 1e9 < self.started_at or not self._fresh(frame):
                continue
            self.check_cancelled(deadline)
            return frame, pair
        self.check_cancelled(deadline)
        raise CameraUnavailableError('Не получено свежего согласованного наблюдения')

    def _fresh_pair(self, frame, pair):
        return self._fresh(frame) and (pair is None or self._fresh(pair.secondary))

    def _log_expired(self, frame, pair, stage):
        now = self.clock()
        primary_age = (now - frame.timestamp_ns / 1e9) * 1000
        secondary_age = (None if pair is None else
                         (now - pair.secondary.timestamp_ns / 1e9) * 1000)
        log_debug(
            f'Кадр устарел ({stage}): primary={primary_age:.1f} мс, '
            f'secondary={secondary_age:.1f} мс, предел={self.max_age * 1000:.1f} мс'
            if secondary_age is not None else
            f'Кадр устарел ({stage}): primary={primary_age:.1f} мс, '
            f'предел={self.max_age * 1000:.1f} мс'
        )

    def next(self, deadline=None, not_before=None, *, on_missing=None):
        """Отбирает свежее наблюдение, не продлевая лимит ожидания и трека"""
        wait_deadline = self.clock() + self.wait_timeout
        expired = False
        while True:
            self.check_cancelled(deadline)
            if expired and self.clock() >= wait_deadline:
                raise ObservationRejected('observation_expired')
            try:
                frame, pair = self._read(deadline, wait_deadline=wait_deadline)
                while not_before is not None and frame.timestamp_ns / 1e9 < not_before:
                    frame, pair = self._read(deadline, wait_deadline=wait_deadline)
            except CameraUnavailableError:
                if expired:
                    raise ObservationRejected('observation_expired') from None
                raise

            detection_started = self.clock()
            faces = self.detector(frame.image)
            if self.current is not None:
                gap = (frame.timestamp_ns - self.current.primary.timestamp_ns) / 1e9
                log_debug(
                    f'Haar: кадр {frame.sequence}, лиц={len(faces)}, '
                    f'детекция={(self.clock() - detection_started) * 1000:.1f} мс, '
                    f'интервал наблюдений={gap:.3f} с'
                )
            face_detection_preview.record(frame, faces, 'TRACK' if self.current else 'SEARCH')
            self.check_cancelled(deadline)
            fresh = self._fresh_pair(frame, pair)
            if not fresh:
                self._log_expired(frame, pair, 'после детекции')
                # При поиске лица Monitor и так начинает поиск заново.
                if self.current is None:
                    raise ObservationRejected('observation_expired')

            if len(faces) != 1:
                if self.current is not None:
                    if not len(faces) and on_missing is not None:
                        on_missing(frame)
                        return None
                    raise ObservationRejected('face_lost' if not len(faces) else 'multiple_faces')
                return None
            face_box = faces[0]
            track_id = uuid4().hex
            if self.current is not None:
                previous = self.current
                gap = (frame.timestamp_ns - previous.primary.timestamp_ns) / 1e9
                if gap <= 0 or gap > self.max_gap:
                    log_warning(
                        f'Разрыв трека: {gap:.3f} с, предел {self.max_gap:.3f} с; '
                        f'кадры {previous.primary.sequence} -> {frame.sequence}'
                    )
                    raise ObservationRejected('track_gap')
                if box_overlap(previous.face_box, face_box) < self.min_overlap:
                    raise ObservationRejected('track_changed')
                track_id = previous.track_id

            if not fresh:
                # Не засчитываем устаревший кадр и не обновляем опорный трек.
                # Повторяем захват в пределах исходного лимита ожидания.
                expired = True
                continue
            self.current = FaceObservation(frame, face_box, track_id, pair)
            return self.current

    def wait_for_face(self, on_wait=None):
        """Ожидает единственное лицо с возможностью отмены"""
        while True:
            observation = self.next()
            if observation is not None:
                return observation
            if on_wait is not None:
                on_wait()

    def observations(self, count, frame_delay, deadline):
        """Выдаёт фиксированное число наблюдений без накопления изображений"""
        observation = self.current
        last_used_at = None
        accepted = 0
        while accepted < count:
            self.check_cancelled(deadline)
            if observation is None:
                not_before = None if last_used_at is None else last_used_at + frame_delay
                observation = self.next(deadline, not_before=not_before)
                if observation is None:
                    continue
            captured_at = observation.primary.timestamp_ns / 1e9
            if last_used_at is None or captured_at - last_used_at >= frame_delay:
                if not self._fresh_pair(observation.primary, observation.pair):
                    self._log_expired(observation.primary, observation.pair, 'перед распознаванием')
                    # Сохраняем опорный трек, но не передаём старый кадр модели.
                    # Следующее наблюдение должно пройти обычные проверки трека.
                    observation = None
                    continue
                yield observation
                accepted += 1
                last_used_at = captured_at
            observation = None

class ConcurrentFaceObservationSource:
    """Один поток детекции на сессию, один потребитель свежих наблюдений.

    Исходный источник используется только потоком сопровождения. Потребитель
    получает последний подтверждённый кадр без очереди, повторов и повторной
    детекции. Ошибка трека необратима до завершения сессии.
    """

    def __init__(self, source, deadline, on_rejected, *, interval=0.15, missing_grace=0.5):
        if source.current is None:
            raise ValueError('Сопровождение требует обнаруженного лица')
        self.source = source
        self.clock = source.clock
        self.deadline = deadline
        self.on_rejected = on_rejected
        self.interval = float(interval)
        if not math.isfinite(self.interval) or self.interval <= 0:
            raise ValueError('Интервал сопровождения должен быть положительным')
        self.missing_grace = float(missing_grace)
        if not math.isfinite(self.missing_grace) or not 0 <= self.missing_grace <= source.max_gap:
            raise ValueError('Допуск пропусков Haar должен быть в пределах разрыва трека')
        self._condition = threading.Condition()
        self._latest = source.current
        self._missing_since = None
        self._recovery_sequence = 0
        self._verified_recovery = 0
        self._consumed_sequence = 0
        self._reason = None
        self._thread = threading.Thread(
            target=self._run, name='FaceTracking', daemon=True,
        )

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self.source.closed.set()
        with self._condition:
            self._condition.notify_all()
        # Перед выходом из режима распознавания гарантированно прекращаем
        # детекцию: следующий трек или обслуживание не делят этот источник.
        self._thread.join()

    def _reject(self, reason):
        with self._condition:
            if self.source.closed.is_set() or self._reason is not None:
                return
            self._reason = reason
            self._condition.notify_all()
        # Не вызываем автомат под блокировкой источника: при финальном
        # решении автомат сам берёт эту блокировку.
        self.on_rejected(reason)

    def _mark_missing(self, frame):
        with self._condition:
            if self._missing_since is None:
                self._missing_since = frame.timestamp_ns / 1e9
                log_debug(f'Haar: лицо временно не найдено, кадр {frame.sequence}')
            self._condition.notify_all()
            self._check_locked()

    def _run(self):
        try:
            while not self.source.closed.is_set():
                started = self.clock()
                with self._condition:
                    self._check_locked()
                    read_deadline = self.deadline
                    if self._missing_since is not None:
                        read_deadline = min(
                            read_deadline, self._missing_since + self.missing_grace,
                        )
                observation = self.source.next(
                    read_deadline, on_missing=self._mark_missing,
                )
                if observation is not None:
                    with self._condition:
                        if self.source.closed.is_set():
                            return
                        if self._missing_since is not None:
                            self._check_locked()
                            self._recovery_sequence = observation.primary.sequence
                            log_debug(
                                f'Haar: лицо восстановлено через '
                                f'{self.clock() - self._missing_since:.3f} с'
                            )
                            self._missing_since = None
                        self._latest = observation
                        self._condition.notify_all()
                self.source.closed.wait(max(0.0, self.interval - (self.clock() - started)))
        except ObservationRejected as error:
            reason = str(error)
            with self._condition:
                if (reason == 'timeout' and self.clock() < self.deadline
                        and self._missing_since is not None):
                    reason = 'face_lost'
            self._reject(reason)
        except CameraUnavailableError as error:
            log_warning(f'Сопровождение: камера недоступна: {error}')
            self._reject('camera_unavailable')
        except Exception as error:
            log_warning(f'Сопровождение: ошибка обработки: {type(error).__name__}: {error}')
            self._reject('processing_error')

    def _check_locked(self, deadline=None):
        if self._reason is not None:
            raise ObservationRejected(self._reason)
        limit = self.deadline if deadline is None else min(self.deadline, deadline)
        self.source.check_cancelled(limit)
        if (self._missing_since is not None
                and self.clock() - self._missing_since >= self.missing_grace):
            raise ObservationRejected('face_lost')
        age = self.clock() - self._latest.primary.timestamp_ns / 1e9
        if age > self.source.max_gap:
            log_warning(f'Нет наблюдения трека: {age:.3f} с, предел {self.source.max_gap:.3f} с')
            raise ObservationRejected('track_gap')

    def check_cancelled(self, deadline=None):
        with self._condition:
            self._check_locked(deadline)

    def next(self, deadline=None, not_before=None):
        """Возвращает новый кадр трека, пока поток продолжает сопровождение."""
        limit = min(self.deadline, self.clock() + self.source.wait_timeout)
        if deadline is not None:
            limit = min(limit, deadline)
        with self._condition:
            while True:
                self._check_locked(deadline)
                observation = self._latest
                timestamp = observation.primary.timestamp_ns / 1e9
                if (self._missing_since is None
                        and observation.primary.sequence > self._consumed_sequence
                        and (not_before is None or timestamp >= not_before)
                        and self.source._fresh_pair(observation.primary, observation.pair)):
                    self._consumed_sequence = observation.primary.sequence
                    return observation
                remaining = limit - self.clock()
                if remaining <= 0:
                    self._check_locked(deadline)
                    raise ObservationRejected('observation_expired')
                self._condition.wait(min(CAPTURE_POLL_SECONDS, remaining))

    def observations(self, count, frame_delay, deadline):
        last_used_at = None
        for _ in range(count):
            not_before = None if last_used_at is None else last_used_at + frame_delay
            observation = self.next(deadline, not_before=not_before)
            last_used_at = observation.primary.timestamp_ns / 1e9
            yield observation

    def confirm_recovery(self, verify, deadline):
        """После пропуска Haar заново подтверждает личность до допуска."""
        while True:
            with self._condition:
                self._check_locked(deadline)
                if (self._missing_since is None
                        and self._recovery_sequence <= self._verified_recovery):
                    return None
            observation = self.next(deadline)
            if not verify(observation):
                return 'identity_changed'
            with self._condition:
                self._check_locked(deadline)
                if (self._missing_since is None
                        and observation.primary.sequence >= self._recovery_sequence):
                    self._verified_recovery = self._recovery_sequence
                    return None
                # Ещё один пропуск за время вычисления: нужен новый кадр.

    @contextmanager
    def grant_guard(self):
        """Не допускает выдачу доступа по потерянному или устаревшему треку."""
        with self._condition:
            reason = None
            try:
                self._check_locked()
                observation = self._latest
                if self._missing_since is not None:
                    reason = 'face_lost'
                elif self._recovery_sequence > self._verified_recovery:
                    reason = 'identity_not_confirmed'
                elif not self.source._fresh_pair(observation.primary, observation.pair):
                    reason = 'observation_expired'
            except ObservationRejected as error:
                reason = str(error)
            # Автомат проверяет результат и вызывает замок под той же
            # блокировкой, поэтому уже опубликованная потеря трека не теряется.
            yield reason
