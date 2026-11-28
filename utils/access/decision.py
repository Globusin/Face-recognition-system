"""Единая политика допуска по результатам проверок

Правила строятся только по статусам проверок: высокая оценка распознавания
не отменяет провал обязательной проверки, а недостающие обязательные данные
считаются отказом
"""

from dataclasses import dataclass

from utils.stereo.stereo_liveness import LIVE, SPOOF

GRANTED = 'GRANTED'
DENIED = 'DENIED'

STEREO_MODES = ('off', 'advisory', 'required')
CHALLENGE_MODES = ('disabled', 'adaptive', 'always')

PASS = 'PASS'
FAIL = 'FAIL'


@dataclass(frozen=True)
class Decision:
    status: str
    reason: str = ''


class AccessPolicy:
    """Обязательность проверок и итоговое решение по сессии"""

    def __init__(self, stereo_mode='off', challenge_mode='disabled',
                 challenge_count=1, config_error=''):
        if stereo_mode not in STEREO_MODES:
            raise ValueError(f'Неизвестный режим стереопроверки: {stereo_mode}')
        if challenge_mode not in CHALLENGE_MODES:
            raise ValueError(f'Неизвестная политика заданий: {challenge_mode}')
        if (isinstance(challenge_count, bool)
                or not isinstance(challenge_count, int)
                or not 1 <= challenge_count <= 5):
            raise ValueError('Число заданий должно быть от 1 до 5')
        self.stereo_mode = stereo_mode
        self.challenge_mode = challenge_mode
        self.challenge_count = challenge_count
        self.config_error = config_error

    @classmethod
    def from_config(cls, config):
        stereo = config.get('stereo_liveness', {}) or {}
        challenge = config.get('challenge_response', {}) or {}
        return cls(
            stereo_mode=str(stereo.get('mode', 'off')).strip().lower(),
            challenge_mode=str(challenge.get('policy', 'disabled')).strip().lower(),
            challenge_count=challenge.get('pipeline_count', 4),
        )

    @property
    def stereo_required(self):
        return self.stereo_mode == 'required'

    def challenge_required(self, session):
        """Нужно ли задание по политике и данным проверки объёма"""
        verdict = (session.diagnostics.get('stereo') or {}).get('decision')
        # SPOOF — обнаруженная атака: задание не предлагается, доступ запрещён
        if verdict == SPOOF:
            return False
        if self.challenge_mode == 'disabled':
            return False
        if self.challenge_mode == 'always':
            return True
        # Задание подкрепляет только слабые свидетельства живости
        return verdict != LIVE

    def evaluate(self, session):
        """Итоговое решение до управления замком"""
        if self.config_error:
            # Неверная конфигурация политики запрещает допуск полностью
            return Decision(DENIED, self.config_error)
        recognition = session.checks.get('recognition')
        if recognition is None or recognition.status != PASS:
            return Decision(DENIED, 'identity_not_confirmed')

        verdict = (session.diagnostics.get('stereo') or {}).get('decision')
        if verdict == SPOOF:
            # Обнаруженная атака запрещает доступ даже в advisory
            return Decision(DENIED, 'liveness_spoof')

        if self.stereo_required:
            stereo = session.checks.get('stereo')
            if stereo is None:
                return Decision(DENIED, 'stereo_required')
            if stereo.status != PASS:
                return Decision(DENIED, stereo.reason or 'stereo_not_passed')

        for name, result in session.checks.items():
            if result.status == FAIL:
                return Decision(DENIED, result.reason or f'{name}_failed')

        if self.challenge_required(session):
            challenge = session.checks.get('challenge')
            if challenge is None:
                return Decision(DENIED, 'challenge_required')
            if challenge.status != PASS:
                return Decision(
                    DENIED, challenge.reason or 'challenge_not_passed',
                )

        return Decision(GRANTED)
