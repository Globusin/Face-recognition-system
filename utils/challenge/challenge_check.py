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
from utils.common.logger import log_error, log_warning
from utils.device.display import DisplayState, NullDisplay
from utils.face.face_observations import ObservationRejected
from utils.face.recognition import get_embeddings_from_frame, match_embedding

PROMPT_BASELINE = 'Смотрите\nпрямо\nГлаза открыты'
PROMPT_RETURN = 'Вернитесь\nв исходное\nположение'


class ChallengeDisplayError(RuntimeError):
    """Команду не удалось показать: проверка без инструкции недействительна"""


class UnavailableChallengeCheck:
    """Обязательная проверка при ошибке конфигурации

    Не отключает задание молча: каждый допуск запрещается, пока конфигурация
    не исправлена
    """

    def __init__(self, reason):
        self.reason = reason

    def should_run(self, session):
        return True

    def __call__(self, session):
        return CheckResult(CheckStatus.NOT_AVAILABLE, self.reason)


def build_challenge_check(config, display, policy):
    """Создаёт адаптер заданий или None, если политика явно отключена

    Ошибка конфигурации при непустой политике не считается отключением:
    возвращается недоступная проверка, чтобы доступ оставался запрещён
    """
    if policy.challenge_mode == 'disabled':
        return None

    section = config.get('challenge_response', {}) or {}
    try:
        settings = challenge_settings(section)
    except ValueError as error:
        log_error(f'Задания: ошибка конфигурации, проверка недоступна: {error}')
        return UnavailableChallengeCheck(f'challenge_config_error: {error}')

    settings['count'] = policy.challenge_count
    return ChallengeCheck(settings, policy, display)


class ChallengeCheck:
    """Проверка заданиями для одной сессии аутентификации

    Кадры берутся из источника наблюдений распознавания: они принадлежат треку,
    по которому принято решение, поэтому кадры до команды не засчитываются,
    а потеря лица отменяет попытку. После выполнения задания один новый
    эмбеддинг подтверждает, что перед камерой тот же пользователь. Повторно
    результат той же сессии не используется
    """

    def __init__(self, settings, policy, display, clock=time.monotonic):
        self.settings = settings
        self.policy = policy
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
        """Нужно ли задание по политике и данным проверки объёма"""
        return self.policy.challenge_required(session)

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
        last_observation = None
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
                last_observation = observation
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

        if flow.stage != 'passed':
            return CheckResult(CheckStatus.FAIL, flow.reason or 'challenge_failed')
        if last_observation is None:
            return CheckResult(CheckStatus.FAIL, 'identity_not_measured')
        failure = self._identity_failure(last_observation, session)
        if failure is not None:
            return CheckResult(CheckStatus.FAIL, failure)
        return CheckResult(CheckStatus.PASS, 'challenge_passed')

    def _identity_failure(self, observation, session):
        """Один эмбеддинг после задания должен принадлежать тому же пользователю"""
        try:
            embeddings = get_embeddings_from_frame(
                observation.primary.image, observation.face_box,
            )
            if not embeddings:
                return 'identity_not_measured'
            user_id, distance = match_embedding(embeddings[0])
        except Exception as error:
            log_warning(f'Задания: не удалось подтвердить личность: {error}')
            return 'identity_not_measured'

        session.diagnostics['challenge_identity'] = dict(
            user_id=user_id, distance=distance,
        )
        if user_id is None:
            return 'identity_not_measured'
        if user_id != session.user_id:
            # Подмена человека между распознаванием и заданием
            return 'identity_changed'
        return None

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
