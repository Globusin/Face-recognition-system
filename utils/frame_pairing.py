import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CameraFrame:
    role: str
    sequence: int
    timestamp_ns: int
    # Изображение недоступно через __repr__
    image: Any = field(repr=False)
    read_time_ms: float = 0.0


@dataclass
class FramePair:
    number: int
    primary: CameraFrame
    secondary: CameraFrame
    delta_ms: float


class FramePairer:
    """Сопоставляет ближайшие по времени кадры двух камер"""

    def __init__(self, max_delta_ms=80.0, buffer_size=8):
        self.max_delta_ns = int(max_delta_ms * 1_000_000)
        self.primary_frames = deque(maxlen=buffer_size)
        self.secondary_frames = deque(maxlen=buffer_size)
        self.pairs = deque(maxlen=buffer_size)
        self.condition = threading.Condition()

        self.pair_count = 0
        self.delta_sum_ms = 0.0
        self.max_delta_ms = 0.0
        self.dropped_primary = 0
        self.dropped_secondary = 0

    def add_frame(self, frame):
        if frame.role not in ('primary', 'secondary'):
            raise ValueError(f"Неизвестная роль камеры: {frame.role}")

        with self.condition:
            target = (
                self.primary_frames
                if frame.role == 'primary'
                else self.secondary_frames
            )

            # deque сам удаляет старый элемент при переполнении
            if len(target) == target.maxlen:
                self._add_drop(frame.role)
            target.append(frame)

            self._make_pairs()
            self.condition.notify_all()

    def _make_pairs(self):
        while self.primary_frames and self.secondary_frames:
            primary = self.primary_frames[0]
            secondary = self.secondary_frames[0]
            difference_ns = primary.timestamp_ns - secondary.timestamp_ns

            if abs(difference_ns) <= self.max_delta_ns:
                self.primary_frames.popleft()
                self.secondary_frames.popleft()

                delta_ms = abs(difference_ns) / 1_000_000
                self.pair_count += 1
                self.delta_sum_ms += delta_ms
                self.max_delta_ms = max(self.max_delta_ms, delta_ms)
                self.pairs.append(
                    FramePair(
                        number=self.pair_count,
                        primary=primary,
                        secondary=secondary,
                        delta_ms=delta_ms,
                    )
                )
                continue

            # Более старый кадр уже не сможет образовать пару
            if difference_ns < 0:
                self.primary_frames.popleft()
                self._add_drop('primary')
            else:
                self.secondary_frames.popleft()
                self._add_drop('secondary')

    def _add_drop(self, role):
        if role == 'primary':
            self.dropped_primary += 1
        else:
            self.dropped_secondary += 1

    def wait_for_pair(self, after_number=0, timeout=1.0) -> Optional[FramePair]:
        """Ждёт пару с номером больше after_number и не возвращает старые пары"""
        # Монотонное время не зависит от перевода системных часов
        deadline = time.monotonic() + timeout

        with self.condition:
            while True:
                for pair in self.pairs:
                    if pair.number > after_number:
                        return pair

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None

                # Поток спит до появления новой пары (notify_all) или окончания таймаута
                self.condition.wait(remaining)

    def get_metrics(self):
        dropped = self.dropped_primary + self.dropped_secondary
        total = self.pair_count + dropped

        return {
            'paired_frames': self.pair_count,
            'average_delta_ms': (
                self.delta_sum_ms / self.pair_count
                if self.pair_count
                else None
            ),
            'max_delta_ms': self.max_delta_ms if self.pair_count else None,
            'dropped_primary': self.dropped_primary,
            'dropped_secondary': self.dropped_secondary,
            'drop_rate': dropped / total if total else 0.0,
        }
