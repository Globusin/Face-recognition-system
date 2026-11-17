"""Случайные задания и проверка действий, без решения об открытии замка"""

import secrets
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from utils.stereo_timing import record_duration


COMMANDS = {
    'BLINK': 'Моргните\nдвумя глазами',
    'TURN_LEFT': 'Поверните\nголову влево',
    'TURN_RIGHT': 'Поверните\nголову вправо',
}

# Моргание временно исключено: частота анализа на Pi пока не проверена
ACTIVE_COMMANDS = ('TURN_LEFT', 'TURN_RIGHT')

DEFAULTS = dict(count=3, baseline_seconds=0.6, baseline_timeout=6.0,
                action_timeout=8.0, max_gap_seconds=1.5,
                closed_ratio=0.65, open_ratio=0.85, turn_ratio=0.18,
                neutral_ratio=0.12, identity_distance=0.45)


def challenge_settings(config):
    settings = {key: config.get(key, value) for key, value in DEFAULTS.items()}
    if any(isinstance(value, bool) or not isinstance(value, (float, int))
           or not np.isfinite(value) or value <= 0 for value in settings.values()):
        raise ValueError('Параметры заданий должны быть положительными числами')
    if type(settings['count']) is not int or not 1 <= settings['count'] <= 5:
        raise ValueError('Число заданий должно быть от 1 до 5')
    if not 0 < settings['closed_ratio'] < settings['open_ratio'] < 1:
        raise ValueError('Неверные пороги открытия глаз')
    if not settings['neutral_ratio'] < settings['turn_ratio'] < 1:
        raise ValueError('Неверные пороги поворота головы')
    if settings['action_timeout'] > 15 or settings['baseline_timeout'] > 15:
        raise ValueError('Ожидание одного этапа не должно превышать 15 секунд')
    return settings


@dataclass
class FaceObservation:
    timestamp: float
    left_eye: float
    right_eye: float
    yaw: float
    embedding: np.ndarray | None = field(default=None, repr=False)


def eye_aspect_ratio(points):
    """Оценивает открытие глаза: отношение его высоты к ширине по шести точкам"""
    points = np.asarray(points, dtype=float)
    if points.shape != (6, 2) or not np.isfinite(points).all():
        raise ValueError('landmarks_not_detected')

    width = np.linalg.norm(points[0] - points[3])
    if width < 2:
        raise ValueError('landmarks_not_detected')

    first_height = np.linalg.norm(points[1] - points[5])
    second_height = np.linalg.norm(points[2] - points[4])
    average_height = (first_height + second_height) / 2

    return float(average_height / width)


def observe_face(image, timestamp, durations=None, *, verify_identity=True):
    import face_recognition

    # Небольшой кадр снижает нагрузку на Pi, координаты дальше не сохраняются
    with record_duration(durations, 'image_preparation'):
        scale = min(1.0, 640 / image.shape[1])
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    with record_duration(durations, 'face_detection'):
        locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=0, model='hog')

    if not locations:
        raise ValueError('face_lost')
    if len(locations) != 1:
        raise ValueError('multiple_faces')

    with record_duration(durations, 'landmarks'):
        landmarks = face_recognition.face_landmarks(rgb, face_locations=locations, model='large')

    if len(landmarks) != 1:
        raise ValueError('landmarks_not_detected')

    face = landmarks[0]
    left = face.get('left_eye', [])
    right = face.get('right_eye', [])
    left_ratio, right_ratio = eye_aspect_ratio(left), eye_aspect_ratio(right)

    nose = np.asarray(face.get('nose_tip', []), dtype=float)
    if nose.shape != (5, 2) or not np.isfinite(nose).all():
        raise ValueError('landmarks_not_detected')

    centers = sorted([np.mean(left, axis=0), np.mean(right, axis=0)], key=lambda point: point[0])
    eye_distance = centers[1][0] - centers[0][0]
    if eye_distance < 10:
        raise ValueError('landmarks_not_detected')

    yaw = float((nose[2, 0] - (centers[0][0] + centers[1][0]) / 2) / eye_distance)

    embedding = None
    if verify_identity:
        with record_duration(durations, 'embedding'):
            encodings = face_recognition.face_encodings(
                rgb,
                known_face_locations=locations,
                num_jitters=1,
                model='small',
            )

        if len(encodings) != 1:
            raise ValueError('landmarks_not_detected')

        embedding = np.asarray(encodings[0])

    return FaceObservation(timestamp, left_ratio, right_ratio, yaw, embedding)


class ChallengeFlow:
    """Конечный автомат не зависит от камеры, TFT и HTTP"""

    def __init__(self, settings, now=None, *, preparation_mode=False, verify_identity=True):
        self.settings = settings
        self.started = time.monotonic() if now is None else now
        self.stage_started = self.started
        self.stage = 'baseline'
        self.command = None
        self.completed = 0
        self.reason = None
        self.anchor = None
        self.last_timestamp = None
        self.neutral_samples = []
        self.baseline = None
        self.action_started = None
        self.preparation_mode = preparation_mode
        self.verify_identity = verify_identity
        self.diagnostics = {}
        self.frame_timing = {}

    def wait_for_baseline(self, reason):
        """После потери лица подготовка начинается заново, без переноса участника"""
        self.neutral_samples.clear()
        self.last_timestamp = None
        self.diagnostics = dict(reason=reason)
        if self.completed == 0:
            self.anchor = None

    @property
    def finished(self):
        return self.stage in ('passed', 'failed')

    def fail(self, reason):
        self.stage, self.reason = 'failed', reason

    def check_timeout(self, now):
        if self.finished:
            return
        if self.stage == 'baseline' and self.preparation_mode:
            return
        timeout = self.settings['baseline_timeout'] if self.stage == 'baseline' else self.settings['action_timeout']
        if now - self.stage_started >= timeout:
            self.fail('baseline_timeout' if self.stage == 'baseline' else 'timeout')

    def feed(self, observation, now):
        self.check_timeout(now)
        if self.finished:
            return
        values = np.array([observation.timestamp, observation.left_eye, observation.right_eye, observation.yaw])
        embedding = np.asarray(observation.embedding)
        if (not np.isfinite(values).all() or min(observation.left_eye, observation.right_eye) <= 0
                or self.verify_identity and
                (embedding.shape != (128,) or not np.isfinite(embedding).all())):
            self.fail('landmarks_not_detected')
            return
        age = now - observation.timestamp
        gap = None if self.last_timestamp is None else observation.timestamp - self.last_timestamp
        self.frame_timing.update(age_after_processing_ms=age * 1000,
                                 observation_gap_ms=None if gap is None else gap * 1000,
                                 observation_limit_ms=self.settings['max_gap_seconds'] * 1000)
        failure = None
        if age < 0:
            failure = 'future_observation_timestamp'
        elif age > self.settings['max_gap_seconds']:
            failure = 'observation_too_old'
        elif gap is not None and gap <= 0:
            failure = 'non_increasing_observation_timestamp'
        elif gap is not None and gap > self.settings['max_gap_seconds']:
            failure = 'observation_gap_exceeded'
        if failure:
            self.frame_timing['failure'] = failure
            self.fail('stale_frame')
            return
        self.last_timestamp = observation.timestamp
        if self.verify_identity:
            if self.anchor is None:
                self.anchor = embedding.copy()
            elif np.linalg.norm(self.anchor - embedding) > self.settings['identity_distance']:
                self.fail('identity_changed')
                return

        if self.stage == 'baseline':
            eyes_open = 0.18 <= observation.left_eye <= 0.45 and 0.18 <= observation.right_eye <= 0.45
            head_straight = abs(observation.yaw) < self.settings['neutral_ratio']
            neutral = eyes_open and head_straight
            self.diagnostics = dict(left_ear=float(observation.left_eye), right_ear=float(observation.right_eye),
                                    yaw=float(observation.yaw), ear_min=0.18, ear_max=0.45,
                                    yaw_limit=self.settings['neutral_ratio'],
                                    reason='eyes_not_open' if not eyes_open else
                                    'head_not_straight' if not head_straight else 'collecting')
            if not neutral:
                self.neutral_samples.clear()
                return
            self.neutral_samples.append(observation)
            self.diagnostics.update(samples=len(self.neutral_samples),
                                    duration_seconds=observation.timestamp - self.neutral_samples[0].timestamp,
                                    required_seconds=self.settings['baseline_seconds'])
            if (len(self.neutral_samples) >= 3 and
                    observation.timestamp - self.neutral_samples[0].timestamp >= self.settings['baseline_seconds']):
                self.baseline = np.median([[item.left_eye, item.right_eye, item.yaw]
                                           for item in self.neutral_samples], axis=0)
                # Команда выбирается лишь после нейтрального положения
                self.command = secrets.choice(ACTIVE_COMMANDS)
                self.stage = 'prompt'
            return

        # Вызов acknowledge_prompt следует только после вывода команды на дисплей
        if self.stage == 'prompt' or observation.timestamp <= self.stage_started:
            return
        eye_ratios = np.array([observation.left_eye, observation.right_eye]) / self.baseline[:2]
        yaw_delta = observation.yaw - self.baseline[2]
        eyes_open = bool(np.all(eye_ratios >= self.settings['open_ratio']))
        neutral = abs(yaw_delta) < self.settings['neutral_ratio'] and eyes_open
        if self.command == 'BLINK':
            active = bool(np.all(eye_ratios < self.settings['closed_ratio']))
        else:
            # Для незеркального изображения вправо по кадру - влево для участника
            direction = 1 if self.command == 'TURN_LEFT' else -1
            active = direction * yaw_delta > self.settings['turn_ratio'] and eyes_open

        if self.stage == 'action':
            if active:
                if self.action_started is None:
                    self.action_started = observation.timestamp
                hold = 0.08 if self.command == 'BLINK' else 0.25
                if observation.timestamp - self.action_started >= hold:
                    self.stage = 'return'
            else:
                self.action_started = None
        elif self.stage == 'return' and neutral:
            self.completed += 1
            self.command = None
            self.neutral_samples.clear()
            self.action_started = None
            self.stage_started = now
            self.stage = 'passed' if self.completed == self.settings['count'] else 'baseline'

    def acknowledge_prompt(self, now):
        if self.stage != 'prompt':
            raise RuntimeError('Команда ещё не готова')
        self.stage_started = now
        self.stage = 'action'

    def snapshot(self, now):
        timeout = self.settings['baseline_timeout'] if self.stage == 'baseline' else self.settings['action_timeout']
        return dict(stage=self.stage, command=self.command, completed=self.completed,
                    total=self.settings['count'], reason=self.reason,
                    remaining_seconds=None if self.stage == 'baseline' and self.preparation_mode else
                    max(0, round(timeout - (now - self.stage_started), 1)),
                    preparation_mode=self.preparation_mode, diagnostics=dict(self.diagnostics),
                    frame_timing=dict(self.frame_timing),
                    identity_continuity_checked=self.verify_identity,
                    elapsed_seconds=round(now - self.started, 2),
                    result='PASS' if self.stage == 'passed' else 'FAIL' if self.stage == 'failed' else None,
                    access_granted=False, experimental=True)
