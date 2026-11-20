"""Свежие наблюдения лица для одной попытки аутентификации"""

import math
import time
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from utils.camera_manager import CameraUnavailableError
from utils.face_detection_preview import face_detection_preview
from utils.frame_pairing import CameraFrame, FramePair
from utils.video_capture import detect_faces
from utils.camera_manager import CameraManager


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

    def check_cancelled(self, deadline=None):
        if self.stop_event.is_set():
            raise ObservationRejected('stopped')
        if self.cancel_event.is_set():
            raise ObservationRejected('maintenance')
        if deadline is not None and self.clock() >= deadline:
            raise ObservationRejected('timeout')

    def _fresh(self, frame):
        age = self.clock() - frame.timestamp_ns / 1e9
        return 0 <= age <= self.max_age

    def _read(self, deadline=None):
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

    def next(self, deadline=None, not_before=None):
        """Детектирует лицо один раз и продолжает только непрерывный трек"""
        frame, pair = self._read(deadline)
        while not_before is not None and frame.timestamp_ns / 1e9 < not_before:
            frame, pair = self._read(deadline)
        faces = self.detector(frame.image)
        face_detection_preview.record(frame, faces, 'TRACK' if self.current else 'SEARCH')
        self.check_cancelled(deadline)
        if not self._fresh(frame) or (pair is not None and not self._fresh(pair.secondary)):
            raise ObservationRejected('observation_expired')
        if len(faces) != 1:
            if self.current is not None:
                raise ObservationRejected('face_lost' if not faces else 'multiple_faces')
            return None
        face_box = faces[0]
        track_id = uuid4().hex
        if self.current is not None:
            previous = self.current
            gap = (frame.timestamp_ns - previous.primary.timestamp_ns) / 1e9
            if gap <= 0 or gap > self.max_gap:
                raise ObservationRejected('track_gap')
            if box_overlap(previous.face_box, face_box) < self.min_overlap:
                raise ObservationRejected('track_changed')
            track_id = previous.track_id
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
                if not self._fresh(observation.primary):
                    raise ObservationRejected('observation_expired')
                yield observation
                accepted += 1
                last_used_at = captured_at
            observation = None
