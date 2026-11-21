"""Накопление свидетельств идентичности по последовательным кадрам

Модуль не обращается к камере, базе данных или dlib: на вход поступают готовые
результаты поиска по базе, поэтому формулы проверяются тестами без оборудования
"""

import math
from dataclasses import dataclass
from typing import Optional

PASS = 'PASS'
FAIL = 'FAIL'
INDETERMINATE = 'INDETERMINATE'


@dataclass(frozen=True)
class EvidenceDecision:
    """Итог накопления свидетельств по одной попытке"""
    status: str
    reason: str = ''
    user_id: Optional[int] = None
    distance: Optional[float] = None
    score: Optional[float] = None
    frames: int = 0


def calculate_distance_std(distances):
    """Стандартное отклонение дистанций до одного шаблона"""
    if len(distances) < 2:
        return 0
    mean_distance = sum(distances) / len(distances)
    variance = sum((distance - mean_distance) ** 2 for distance in distances) / len(distances)
    return variance ** 0.5


def _sigmoid(value):
    # Отдельные ветви не дают exp переполниться на больших по модулю значениях
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exponent = math.exp(value)
    return exponent / (1 + exponent)


def _finite(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise ValueError(f'{name} должен быть числом') from None
    if not math.isfinite(value):
        raise ValueError(f'{name} должен быть конечным числом')
    return value


class IdentityEvidence:
    """Последовательное накопление свидетельств за одного пользователя

    Каждый кадр даёт отношение правдоподобий для кандидата. Кадры одной камеры,
    снятые подряд, сильно коррелированы, поэтому вклад второго и последующих
    кадров умножается на correlation_discount: это поправка на эффективный размер
    выборки, а не измеренная вероятность. score — сжатая в 0..1 величина
    логарифма отношения правдоподобий, вероятностью не является
    """

    def __init__(self, *, prior_probability, distance_sigma, unknown_likelihood,
                 miss_likelihood_ratio, minimum_likelihood, correlation_discount,
                 min_frames, max_frames, min_successful_frames, max_distance_std,
                 decision_threshold=None, early_stop_threshold=None):
        prior_probability       = _finite(prior_probability, 'prior_probability')
        distance_sigma          = _finite(distance_sigma, 'distance_sigma')
        unknown_likelihood      = _finite(unknown_likelihood, 'unknown_likelihood')
        miss_likelihood_ratio   = _finite(miss_likelihood_ratio, 'miss_likelihood_ratio')
        minimum_likelihood      = _finite(minimum_likelihood, 'minimum_likelihood')
        correlation_discount    = _finite(correlation_discount, 'correlation_discount')
        max_distance_std        = _finite(max_distance_std, 'max_distance_std')

        if not 0 < prior_probability < 1:
            raise ValueError('prior_probability должен быть в диапазоне (0, 1)')
        if distance_sigma <= 0:
            raise ValueError('distance_sigma должен быть положительным')
        if unknown_likelihood <= 0:
            raise ValueError('unknown_likelihood должен быть положительным')
        # Отношение больше единицы поощряло бы кадры, где совпал другой пользователь
        if not 0 < miss_likelihood_ratio <= 1:
            raise ValueError('miss_likelihood_ratio должен быть в диапазоне (0, 1]')
        if minimum_likelihood <= 0:
            raise ValueError('minimum_likelihood должен быть положительным')
        if not 0 < correlation_discount <= 1:
            raise ValueError('correlation_discount должен быть в диапазоне (0, 1]')
        if max_distance_std < 0:
            raise ValueError('max_distance_std не может быть отрицательным')

        if isinstance(min_frames, bool) or isinstance(max_frames, bool):
            raise ValueError('Количество кадров должно быть целым числом')
        min_frames = int(min_frames)
        max_frames = int(max_frames)
        min_successful_frames = int(min_successful_frames)
        if min_frames < 1:
            raise ValueError('min_frames должен быть положительным')
        if max_frames < min_frames:
            raise ValueError('max_frames не может быть меньше min_frames')
        if not 1 <= min_successful_frames <= max_frames:
            raise ValueError('min_successful_frames должен быть в диапазоне [1, max_frames]')

        if decision_threshold is not None:
            decision_threshold = _finite(decision_threshold, 'decision_threshold')
            if not 0 < decision_threshold < 1:
                raise ValueError('decision_threshold должен быть в диапазоне (0, 1)')
        if early_stop_threshold is not None:
            early_stop_threshold = _finite(early_stop_threshold, 'early_stop_threshold')
            if not 0 < early_stop_threshold <= 1:
                raise ValueError('early_stop_threshold должен быть в диапазоне (0, 1]')

        self.prior_probability = prior_probability
        self.distance_sigma = distance_sigma
        self.unknown_likelihood = unknown_likelihood
        self.miss_likelihood_ratio = miss_likelihood_ratio
        self.minimum_likelihood = minimum_likelihood
        self.correlation_discount = correlation_discount
        self.min_frames = min_frames
        self.max_frames = max_frames
        self.min_successful_frames = min_successful_frames
        self.max_distance_std = max_distance_std
        self.decision_threshold = decision_threshold
        self.early_stop_threshold = early_stop_threshold

        self._prior_log_odds = math.log(prior_probability / (1 - prior_probability))
        self._frames = []
        self._support = {}
        self._distances = {}

    @property
    def frame_count(self):
        return len(self._frames)

    @property
    def scores(self):
        """Текущий score каждого кандидата"""
        return {user_id: self.score(user_id) for user_id in self._support}

    def add(self, nearest_user_id, distance):
        """Добавляет наблюдение; None означает совпадение вне порога similarity"""
        if nearest_user_id is None:
            self._frames.append((None, None))
            return
        try:
            distance = float(distance)
        except (TypeError, ValueError):
            self._frames.append((None, None))
            return
        if not math.isfinite(distance) or distance < 0:
            self._frames.append((None, None))
            return
        self._frames.append((nearest_user_id, distance))
        self._support[nearest_user_id] = self._support.get(nearest_user_id, 0) + 1
        self._distances.setdefault(nearest_user_id, []).append(distance)

    def mean_distance(self, user_id):
        distances = self._distances.get(user_id) or []
        return sum(distances) / len(distances) if distances else None

    def score(self, user_id):
        """Score кандидата по накопленным кадрам"""
        if user_id not in self._support:
            return 0.0
        return _sigmoid(self._log_odds(user_id))

    def best(self):
        """Ведущий кандидат и его score; при равенстве выбирается по числу кадров"""
        if not self._support:
            return None, None
        # Порядок ключей словаря сохраняет первого встреченного кандидата,
        # поэтому выбор детерминирован без предположения о типе user_id
        user_id = max(
            self._support,
            key=lambda candidate: (self.score(candidate), self._support[candidate]),
        )
        return user_id, self.score(user_id)

    def early_decision(self):
        """Решение, если продолжать сбор кадров уже не нужно"""
        frames = self.frame_count
        if frames < self.min_frames:
            return None

        leader, score = self.best()
        remaining = self.max_frames - frames
        if leader is None:
            if remaining < self.min_successful_frames:
                return EvidenceDecision(FAIL, 'insufficient_matches', frames=frames)
            return None

        support = self._support[leader]
        # Если даже все оставшиеся кадры не дадут минимум совпадений, ждать нечего
        if remaining < self.min_successful_frames - support:
            return EvidenceDecision(
                FAIL, 'insufficient_matches', user_id=leader, score=score, frames=frames,
            )
        if support < self.min_successful_frames:
            return None
        if not self._stable_leader(leader):
            return None
        if self._other_support(leader) >= self.min_successful_frames:
            return EvidenceDecision(
                INDETERMINATE, 'conflicting_identities',
                user_id=leader, score=score, frames=frames,
            )
        if calculate_distance_std(self._distances[leader]) > self.max_distance_std:
            return None
        if self.early_stop_threshold is not None and score < self.early_stop_threshold:
            return None
        return EvidenceDecision(
            PASS, 'early_stop', user_id=leader, distance=self.mean_distance(leader),
            score=score, frames=frames,
        )

    def result(self):
        """Итоговое решение, когда кадры закончились"""
        frames = self.frame_count
        if not frames:
            return EvidenceDecision(FAIL, 'no_frames', frames=0)
        # Попытка, оборванная по времени или потере трека, не даёт права
        # на вывод даже при высоком score: минимум кадров обязателен для любого решения
        if frames < self.min_frames:
            return EvidenceDecision(FAIL, 'insufficient_frames', frames=frames)

        leader, score = self.best()
        if leader is None:
            return EvidenceDecision(FAIL, 'no_identity_matches', frames=frames)

        # Значимая поддержка второго пользователя означает смену личности
        if self._other_support(leader) >= self.min_successful_frames:
            return EvidenceDecision(
                INDETERMINATE, 'conflicting_identities',
                user_id=leader, score=score, frames=frames,
            )
        if self._support[leader] < self.min_successful_frames:
            return EvidenceDecision(
                FAIL, 'insufficient_matches', user_id=leader, score=score, frames=frames,
            )
        if calculate_distance_std(self._distances[leader]) > self.max_distance_std:
            return EvidenceDecision(
                FAIL, 'unstable_distance', user_id=leader, score=score, frames=frames,
            )
        if self.decision_threshold is not None and score < self.decision_threshold:
            return EvidenceDecision(
                FAIL, 'weak_evidence', user_id=leader, score=score, frames=frames,
            )
        return EvidenceDecision(
            PASS, 'identity_confirmed', user_id=leader,
            distance=self.mean_distance(leader), score=score, frames=frames,
        )

    def _stable_leader(self, leader):
        """Последние min_successful_frames кадров должны поддерживать одного пользователя"""
        window = self._frames[-self.min_successful_frames:]
        if len(window) < self.min_successful_frames:
            return False
        return all(user_id == leader for user_id, _ in window)

    def _other_support(self, leader):
        supports = [
            count for user_id, count in self._support.items() if user_id != leader
        ]
        return max(supports) if supports else 0

    def _weight(self, frame_index):
        # Первый кадр задаёт базовое свидетельство, следующие лишь уточняют его
        return 1.0 if frame_index == 0 else self.correlation_discount

    def _likelihood_ratio(self, distance):
        match_likelihood = math.exp(-(distance ** 2) / (2 * self.distance_sigma ** 2))
        return max(match_likelihood, self.minimum_likelihood) / self.unknown_likelihood

    def _log_odds(self, user_id):
        total = self._prior_log_odds
        for frame_index, (frame_user_id, frame_distance) in enumerate(self._frames):
            if frame_user_id == user_id and frame_distance is not None:
                ratio = self._likelihood_ratio(frame_distance)
            else:
                ratio = self.miss_likelihood_ratio
            total += self._weight(frame_index) * math.log(
                max(ratio, self.minimum_likelihood)
            )
        return total
