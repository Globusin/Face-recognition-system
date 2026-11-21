"""Управление жизненным циклом одной попытки без алгоритмов распознавания."""

import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, Protocol
from uuid import uuid4


class AuthenticationState(str, Enum):
    IDLE = 'IDLE'  # Ожидание лица
    TRACKING = 'TRACKING'  # Отслеживание обнаруженного лица
    EVALUATING = 'EVALUATING'  # Проверка идентичности и живости
    CHALLENGE = 'CHALLENGE'  # Выполнение задания
    GRANTED = 'GRANTED'  # Доступ разрешён
    DENIED = 'DENIED'  # Доступ запрещён
    COOLDOWN = 'COOLDOWN'  # Завершение попытки
    ERROR = 'ERROR'  # Ошибка оборудования или обработки


class CheckStatus(str, Enum):
    PASS = 'PASS'
    FAIL = 'FAIL'
    NOT_AVAILABLE = 'NOT_AVAILABLE'


@dataclass(frozen=True)
class CheckResult:
    status: CheckStatus
    reason: str = ''


@dataclass
class AuthenticationSession:
    session_id: str
    started_at: float
    updated_at: float
    deadline: float
    state: AuthenticationState = AuthenticationState.TRACKING
    tracked_face_id: Optional[str] = None
    user_id: Optional[int] = None
    distance: Optional[float] = None
    checks: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)
    reason: str = ''
    finished_at: Optional[float] = None
    unlock_attempted: bool = False


class SessionCheck(Protocol):
    """Будущий адаптер Stereo/Challenge; результат относится только к этой сессии

    Адаптер обязан проверять непрерывность лица и возвращать NOT_AVAILABLE,
    если данных недостаточно. На этапе реализации автомата реальные адаптеры не подключаются
    """

    def __call__(self, session: AuthenticationSession) -> CheckResult:
        ...


class AuthenticationEngine:
    """Последовательный автомат Monitor с отменой из другого потока

    Долгие вычисления выполняются вне блокировки. После их завершения повторно
    проверяются отмена, обслуживание и deadline до любых действий с замком
    """

    def __init__(self, lock_controller, maintenance, stop_event, *,
                 session_timeout=20.0, cooldown_seconds=2.0,
                 door_open_seconds=5.0, clock=time.monotonic,
                 stereo_check: Optional[SessionCheck] = None,
                 challenge_check: Optional[SessionCheck] = None,
                 on_state: Optional[Callable] = None):
        for value in (session_timeout, cooldown_seconds, door_open_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError('Интервалы аутентификации должны быть положительными')
        self.lock_controller = lock_controller
        self.maintenance = maintenance
        self.stop_event = stop_event
        self.session_timeout = session_timeout
        self.cooldown_seconds = cooldown_seconds
        self.door_open_seconds = door_open_seconds
        self.clock = clock
        self.stereo_check = stereo_check
        self.challenge_check = challenge_check
        self.on_state = on_state
        self.state = AuthenticationState.IDLE
        self.session = None
        self._lock = threading.RLock()
        self._door_deadline = None
        self._cooldown_deadline = None
        self._closed = False
        self._processing = False

    def _transition(self, state, reason=''):
        self.state = state
        if self.session is not None:
            self.session.state = state
            self.session.updated_at = self.clock()
            if reason:
                self.session.reason = reason
            if state in (AuthenticationState.GRANTED, AuthenticationState.DENIED,
                         AuthenticationState.ERROR):
                self.session.finished_at = self.clock()
        if self.on_state is not None:
            self.on_state(state)

    def begin(self, tracked_face_id=None):
        """Создаёт сессию после детекции; ID трека не является ID личности."""
        with self._lock:
            if (self._closed or self._processing or self.state != AuthenticationState.IDLE
                    or self.stop_event.is_set()
                    or self.maintenance.requested.is_set()):
                return None
            now = self.clock()
            self.session = AuthenticationSession(
                uuid4().hex, now, now, now + self.session_timeout,
                tracked_face_id=tracked_face_id,
            )
            self._transition(AuthenticationState.TRACKING)
            return self.session.session_id

    def _active(self, session_id):
        if self.session is None or self.session.session_id != session_id:
            return False
        if self.state not in (AuthenticationState.TRACKING,
                              AuthenticationState.EVALUATING,
                              AuthenticationState.CHALLENGE):
            return False
        if self.stop_event.is_set() or self.maintenance.requested.is_set():
            self.cancel('stopped' if self.stop_event.is_set() else 'maintenance')
            return False
        if self.clock() >= self.session.deadline:
            self.cancel('timeout')
            return False
        return True

    def evaluate(self, session_id, recognize):
        """Обрабатывает одну попытку; параллельный повторный вызов игнорируется."""
        with self._lock:
            if self._processing or not self._active(session_id):
                return
            self._processing = True
        try:
            self._evaluate(session_id, recognize)
        finally:
            with self._lock:
                self._processing = False

    def _evaluate(self, session_id, recognize):
        with self._lock:
            if not self._active(session_id) or self.state != AuthenticationState.TRACKING:
                return
            self._transition(AuthenticationState.EVALUATING)
        try:
            authenticated, user_id, distance = recognize()
            with self._lock:
                if not self._active(session_id):
                    return
                valid = (authenticated and user_id is not None
                         and distance is not None and math.isfinite(distance)
                         and distance >= 0)
                self.session.checks['recognition'] = CheckResult(
                    CheckStatus.PASS if valid else CheckStatus.FAIL,
                )
                if not valid:
                    self.cancel('identity_not_confirmed')
                    return
                self.session.user_id = user_id
                self.session.distance = distance
            for name, check in (('stereo', self.stereo_check),
                                ('challenge', self.challenge_check)):
                if check is None:
                    continue
                with self._lock:
                    if not self._active(session_id):
                        return
                    if name == 'challenge':
                        self._transition(AuthenticationState.CHALLENGE)
                result = check(self.session)
                with self._lock:
                    if not self._active(session_id):
                        return
                    if not isinstance(result, CheckResult):
                        raise ValueError('Некорректный результат проверки')
                    self.session.checks[name] = result
                    if result.status != CheckStatus.PASS:
                        self.cancel(result.reason or f'{name}_not_passed')
                        return
            with self._lock, self.maintenance.lock:
                if not self._active(session_id):
                    return
                self.session.unlock_attempted = True
                # Даже неудачный unlock может частично сработать на оборудовании
                self._door_deadline = self.clock() + self.door_open_seconds
                if not self.lock_controller.unlock():
                    self.fail('unlock_failed')
                    return
                self.maintenance.door_open.set()
                if not self._active(session_id):
                    self._close_door()
                    return
                self._transition(AuthenticationState.GRANTED)
        except Exception:
            with self._lock:
                if self._active(session_id):
                    self.fail('processing_error')

    def cancel(self, reason='cancelled'):
        """Отменяет только незавершённую попытку; поздний результат игнорируется."""
        with self._lock:
            if self.state in (AuthenticationState.TRACKING,
                              AuthenticationState.EVALUATING,
                              AuthenticationState.CHALLENGE):
                self._transition(AuthenticationState.DENIED, reason)

    def face_lost(self, session_id):
        """Принимает событие потери лица только от текущего трека/сессии."""
        with self._lock:
            if self.session and self.session.session_id == session_id:
                self.cancel('face_lost')

    def fail(self, reason='hardware_error'):
        with self._lock:
            self._transition(AuthenticationState.ERROR, reason)

    def _close_door(self):
        with self.maintenance.lock:
            try:
                locked = self.lock_controller.lock()
            except Exception:
                locked = False
            if not locked:
                self._transition(AuthenticationState.ERROR, 'lock_failed')
                return False
            self.maintenance.door_open.clear()
            self._door_deadline = None
            return True

    def tick(self):
        """Обслуживает deadline, автозакрытие и паузу между попытками"""
        with self._lock:
            if self.session:
                self._active(self.session.session_id)
            if self._door_deadline is not None:
                if self.clock() < self._door_deadline:
                    return
                if not self._close_door():
                    return
            if self.state in (AuthenticationState.GRANTED, AuthenticationState.DENIED,
                              AuthenticationState.ERROR):
                self._cooldown_deadline = self.clock() + self.cooldown_seconds
                self._transition(AuthenticationState.COOLDOWN)
            elif (self.state == AuthenticationState.COOLDOWN
                  and self.clock() >= self._cooldown_deadline and not self._closed):
                self._transition(AuthenticationState.IDLE)

    def close(self):
        """Запрещает новые попытки и закрывает замок при остановке Monitor."""
        with self._lock:
            self._closed = True
            self.cancel('stopped')
            return self._close_door()
