"""Интерактивные задания как проверка сессии аутентификации

Результат относится только к текущей сессии: кадры берутся из того же источника
наблюдений, что и распознавание, а команда выбирается заново при каждой попытке
"""

import time

from utils.access.authentication import CheckResult, CheckStatus
from utils.capture.camera_manager import CameraUnavailableError
from utils.challenge.challenge_response import (
    COMMANDS, ChallengeFlow, challenge_settings, observe_face,
)
from utils.device.display import DisplayState, NullDisplay
from utils.face.face_observations import ObservationRejected
from utils.common.logger import log_warning

POLICIES = ('disabled', 'adaptive', 'always')
DEFAULT_ADAPTIVE_DISTANCE = 0.12
DEFAULT_PIPELINE_COUNT = 1
PROMPT_BASELINE = 'Смотрите\nпрямо\nГлаза открыты'
PROMPT_RETURN = 'Вернитесь\nв исходное\nположение'


class ChallengeDisplayError(RuntimeError):
    """Команду не удалось показать: проверка без инструкции недействительна"""


def challenge_policy_settings(config):
    """Политика заданий и порог риска для адаптивного режима"""
    section = config.get('challenge_response', {}) or {}
    policy = str(section.get('policy', 'disabled')).strip().lower()
    if policy not in POLICIES:
        raise ValueError(f'Неизвестная политика заданий: {policy}')

    distance = section.get('adaptive_max_distance', DEFAULT_ADAPTIVE_DISTANCE)
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        raise ValueError('adaptive_max_distance должен быть числом')
    distance = float(distance)
    if not 0 < distance <= 1:
        raise ValueError('adaptive_max_distance должен быть в диапазоне (0, 1]')

    count = section.get('pipeline_count', DEFAULT_PIPELINE_COUNT)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 5:
        raise ValueError('pipeline_count должен быть целым числом от 1 до 5')

    return dict(policy=policy, adaptive_max_distance=distance, count=count)


def build_challenge_check(config, display):
    """Создаёт адаптер заданий или None, если политика отключена"""
    policy = challenge_policy_settings(config)
    if policy['policy'] == 'disabled':
        return None
    settings = challenge_settings(config.get('challenge_response', {}))
    # Заданий в рабочем конвейере меньше, чтобы уложиться в тайм-аут сессии
    settings['count'] = policy['count']
    return ChallengeCheck(settings, policy, display)


class ChallengeCheck:
    """Проверка заданиями для одной сессии аутентификации

    Кадры берутся из источника наблюдений распознавания: они принадлежат треку,
    по которому принято решение, поэтому кадры до команды не засчитываются,
    а потеря лица отменяет попытку. Повторно результат той же сессии не
    используется
    """

    def __init__(self, settings, policy, display, clock=time.monotonic):
        self.settings = settings
        self.policy = policy['policy']
        self.adaptive_max_distance = policy['adaptive_max_distance']
        self.display = display
        self.clock = clock
        self.source = None
        self._used_sessions = set()

    def bind(self, source):
        """Привязывает источник наблюдений текущей попытки"""
        if self.source is not None:
            raise RuntimeError('Источник наблюдений уже привязан')
        self.source = source

    def release(self):
        self.source = None

    def should_run(self, session):
        """Нужна ли проверка по политике для этой сессии"""
        if self.policy == 'disabled':
            return False
        if self.policy == 'always':
            return True
        # Порог дистанции — временный признак риска, а не калиброванная величина
        return (session.distance is not None
                and session.distance >= self.adaptive_max_distance)

    def __call__(self, session):
        if self.source is None:
            return CheckResult(CheckStatus.NOT_AVAILABLE, 'source_missing')
        if session.session_id in self._used_sessions:
            return CheckResult(CheckStatus.FAIL, 'challenge_reused')
        self._used_sessions.add(session.session_id)
        if self._prior_failure(session):
            # Задание не может компенсировать уже обнаруженный провал
            return CheckResult(CheckStatus.FAIL, 'prior_check_failed')
        if self.display is None or isinstance(self.display, NullDisplay):
            return CheckResult(CheckStatus.NOT_AVAILABLE, 'display_unavailable')
        # Непрерывность личности обеспечивает трек источника наблюдений;
        # embeddings на каждом кадре задания слишком дороги для Raspberry Pi
        flow = ChallengeFlow(self.settings, now=self.clock(), verify_identity=False)
        return self._run(session, flow)

    def _prior_failure(self, session):
        return any(
            result.status == CheckStatus.FAIL
            for name, result in session.checks.items() if name != 'challenge'
        )

    def _run(self, session, flow):
        last_stage = None
        try:
            while not flow.finished:
                now = self.clock()
                if now >= session.deadline:
                    flow.fail('timeout', now)
                    break
                flow.check_timeout(now)
                if flow.finished:
                    break

                try:
                    observation = self.source.next(session.deadline)
                except ObservationRejected as error:
                    flow.fail(str(error), self.clock())
                    break
                except CameraUnavailableError:
                    flow.fail('camera_unavailable', self.clock())
                    break
                if observation is None:
                    flow.fail('face_lost', self.clock())
                    break
                if observation.track_id != session.tracked_face_id:
                    flow.fail('track_changed', self.clock())
                    break

                face = observe_face(
                    observation.primary.image,
                    observation.primary.timestamp_ns / 1e9,
                    face_box=observation.face_box,
                )
                if flow.stage != last_stage:
                    self._show_stage(flow)
                    last_stage = flow.stage

                flow.feed(face, self.clock())
                if flow.stage == 'prompt':
                    if flow.tasks:
                        flow.tasks[-1]['prompt_started_s'] = flow.task_time(self.clock())
                    self._show_command(flow.command)
                    # Кадры до завершения вывода команды не засчитываются
                    flow.acknowledge_prompt(self.clock())
                    last_stage = 'action'
        except ChallengeDisplayError:
            flow.fail('display_error', self.clock())
        except Exception as error:
            flow.fail('processing_error', self.clock())
            log_warning(f'Задания: ошибка выполнения: {type(error).__name__}: {error}')

        if flow.stage == 'passed':
            return CheckResult(CheckStatus.PASS, 'challenge_passed')
        return CheckResult(CheckStatus.FAIL, flow.reason or 'challenge_failed')

    def _show_stage(self, flow):
        if flow.stage == 'baseline':
            self._show_state(PROMPT_BASELINE)
        elif flow.stage == 'return':
            self._show_state(PROMPT_RETURN)

    def _show_command(self, command):
        self._show_state(COMMANDS[command])

    def _show_state(self, detail):
        try:
            self.display.show_state(DisplayState.CHALLENGE, detail)
        except Exception as error:
            raise ChallengeDisplayError(str(error)) from error
