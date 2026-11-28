"""Случайные задания и проверка действий, без решения об открытии замка"""

import secrets
import time
from dataclasses import dataclass, field

import cv2
import numpy as np
from utils.common.timing import record_duration
from utils.face.head_pose import estimate_head_pose
from copy import deepcopy


COMMANDS = {
    'BLINK': 'Моргните\nдвумя глазами',
    'TURN_LEFT': 'Поверните\nголову влево',
    'TURN_RIGHT': 'Поверните\nголову вправо',
}

# Моргание временно исключено: частота анализа на Pi пока не проверена
ACTIVE_COMMANDS = ('TURN_LEFT', 'TURN_RIGHT')

DEFAULTS = dict(count=3, baseline_seconds=0.6, baseline_timeout=12.0,
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
    head_pose: dict | None = None


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


def known_face_location(face_box, scale, image_shape):
    """Переводит ROI (x, y, width, height) в координаты face_recognition"""
    try:
        x, y, width, height = (float(value) * scale for value in face_box)
    except (TypeError, ValueError):
        raise ValueError('landmarks_not_detected') from None
    if (not all(np.isfinite(value) for value in (x, y, width, height))
            or width <= 0 or height <= 0):
        raise ValueError('landmarks_not_detected')
    top, left = int(round(y)), int(round(x))
    bottom, right = int(round(y + height)), int(round(x + width))
    height_px, width_px = image_shape
    if not (0 <= left < right <= width_px and 0 <= top < bottom <= height_px):
        raise ValueError('landmarks_not_detected')
    return top, right, bottom, left


def observe_face(image, timestamp, durations=None, *, verify_identity=True, face_box=None):
    import face_recognition

    # Небольшой кадр снижает нагрузку на Pi, координаты дальше не сохраняются
    with record_duration(durations, 'image_preparation'):
        scale = min(1.0, 640 / image.shape[1])
        if scale < 1:
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

    with record_duration(durations, 'face_detection'):
        if face_box is None:
            locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=0, model='hog')
        else:
            # ROI уже найден при сопровождении: повторная детекция не нужна
            locations = [known_face_location(face_box, scale, rgb.shape[:2])]

    if not locations:
        raise ValueError('face_lost')
    if len(locations) != 1:
        raise ValueError('multiple_faces')

    with record_duration(durations, 'landmarks'):
        face_points = face_recognition.face_landmarks(rgb, face_locations=locations, model='large')

    if len(face_points) != 1:
        raise ValueError('landmarks_not_detected')

    face = face_points[0]
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

    with record_duration(durations, 'head_pose'):
        pose = estimate_head_pose(face, rgb.shape[1::-1])

    return FaceObservation(timestamp, left_ratio, right_ratio, yaw, embedding, pose)


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
        self.observation_status = 'waiting_for_face'
        self.head_pose = None
        self.tasks = []

    def task_time(self, timestamp):
        """Времена в отчёте относительно начала сессии, в секундах"""
        return timestamp - self.started

    def record_task_observation(self, observation):
        if not self.tasks or self.tasks[-1]['result'] is not None:
            return
        task = self.tasks[-1]
        if task['prompt_completed_s'] is None or observation.timestamp <= self.stage_started:
            return
        task['observations'] += 1
        task['yaw_ratio_min'] = min(task['yaw_ratio_min'], observation.yaw)
        task['yaw_ratio_max'] = max(task['yaw_ratio_max'], observation.yaw)
        pose = observation.head_pose
        if pose and pose.get('status') == 'estimated':
            task['pose_observations'] += 1
            for angle in ('yaw_deg', 'pitch_deg', 'roll_deg'):
                value = pose[angle]
                bounds = task['angle_ranges_deg'].setdefault(angle, dict(min=value, max=value))
                bounds['min'] = min(bounds['min'], value)
                bounds['max'] = max(bounds['max'], value)

    def wait_for_baseline(self, reason):
        """После потери лица подготовка начинается заново, без переноса участника"""
        self.neutral_samples.clear()
        self.last_timestamp = None
        self.diagnostics = dict(reason=reason)
        if self.completed == 0:
            self.anchor = None

    def missing_observation(self, reason):
        """Пропуск не завершает проверку и не продлевает время задания"""
        self.observation_status = reason
        self.head_pose = None
        if self.tasks and self.tasks[-1]['result'] is None:
            task = self.tasks[-1]
            task['missing_observations'][reason] = task['missing_observations'].get(reason, 0) + 1
        if self.stage == 'baseline':
            self.wait_for_baseline(reason)
        else:
            self.action_started = None
            self.last_timestamp = None
            self.diagnostics = dict(reason=reason)

    @property
    def finished(self):
        return self.stage in ('passed', 'failed')

    def fail(self, reason, now=None):
        self.stage, self.reason = 'failed', reason
        self.observation_status = reason
        if self.tasks and self.tasks[-1]['result'] is None:
            self.tasks[-1].update(result='FAIL', reason=reason,
                                 finished_s=self.task_time(time.monotonic() if now is None else now))
            task = self.tasks[-1]
            task['total_seconds'] = task['finished_s'] - task['generated_s']

    def check_timeout(self, now):
        if self.finished:
            return
        if self.stage == 'baseline' and self.preparation_mode:
            return
        timeout = self.settings['baseline_timeout'] if self.stage == 'baseline' else self.settings['action_timeout']
        if now - self.stage_started >= timeout:
            self.fail('baseline_timeout' if self.stage == 'baseline' else 'timeout', now)

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
        self.head_pose = observation.head_pose
        self.record_task_observation(observation)
        if self.verify_identity:
            if self.anchor is None:
                self.anchor = embedding.copy()
            elif np.linalg.norm(self.anchor - embedding) > self.settings['identity_distance']:
                self.fail('identity_changed')
                return

        if self.stage == 'baseline':
            self.observation_status = 'face_found'
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
                # Создаём запись задания, измерения заполнятся во время выполнения
                task = dict(
                    number=self.completed + 1,
                    command=self.command,

                    generated_s=self.task_time(now),
                    prompt_started_s=None,
                    prompt_completed_s=None,
                    prompt_render_seconds=None,
                    preparation_seconds=now - self.stage_started,
                    total_seconds=None,

                    baseline_yaw_ratio=float(self.baseline[2]),
                    baseline_pose=observation.head_pose,

                    first_action_s=None,
                    confirmed_s=None,
                    returned_s=None,
                    finished_s=None,

                    reaction_seconds=None,
                    confirmation_seconds=None,
                    return_seconds=None,
                    confirmed_hold_seconds=None,

                    observations=0,
                    pose_observations=0,
                    yaw_ratio_min=float(self.baseline[2]),
                    yaw_ratio_max=float(self.baseline[2]),
                    angle_ranges_deg={},
                    missing_observations={},

                    result=None,
                    reason=None,
                )

                self.tasks.append(task)
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
            self.observation_status = 'action_detected' if active else 'waiting_for_action'
            if active:
                if self.action_started is None:
                    self.action_started = observation.timestamp
                    if self.tasks and self.tasks[-1]['first_action_s'] is None:
                        task = self.tasks[-1]
                        task['first_action_s'] = self.task_time(observation.timestamp)
                        task['reaction_seconds'] = task['first_action_s'] - task['prompt_completed_s']
                hold = 0.08 if self.command == 'BLINK' else 0.25
                if observation.timestamp - self.action_started >= hold:
                    self.stage = 'return'
                    self.observation_status = 'action_confirmed'
                    if self.tasks:
                        task = self.tasks[-1]
                        task['confirmed_s'] = self.task_time(observation.timestamp)
                        task['confirmation_seconds'] = task['confirmed_s'] - task['prompt_completed_s']
                        task['confirmed_hold_seconds'] = observation.timestamp - self.action_started
            else:
                self.action_started = None
        elif self.stage == 'return' and neutral:
            self.observation_status = 'returned_to_neutral'
            if self.tasks:
                task = self.tasks[-1]
                task.update(result='PASS', returned_s=self.task_time(observation.timestamp),
                            finished_s=self.task_time(now))
                task['total_seconds'] = task['finished_s'] - task['generated_s']
                task['return_seconds'] = task['returned_s'] - task['confirmed_s']
            self.completed += 1
            self.command = None
            self.neutral_samples.clear()
            self.action_started = None
            self.stage_started = now
            self.stage = 'passed' if self.completed == self.settings['count'] else 'baseline'
        elif self.stage == 'return':
            self.observation_status = 'waiting_for_return'

    def acknowledge_prompt(self, now):
        if self.stage != 'prompt':
            raise RuntimeError('Команда ещё не готова')
        self.stage_started = now
        self.stage = 'action'
        if self.tasks:
            task = self.tasks[-1]
            task['prompt_completed_s'] = self.task_time(now)
            if task['prompt_started_s'] is not None:
                task['prompt_render_seconds'] = task['prompt_completed_s'] - task['prompt_started_s']

    def snapshot(self, now):
        timeout = self.settings['baseline_timeout'] if self.stage == 'baseline' else self.settings['action_timeout']
        return dict(stage=self.stage, command=self.command, completed=self.completed,
                    total=self.settings['count'], reason=self.reason,
                    remaining_seconds=None if self.stage == 'baseline' and self.preparation_mode else
                    max(0, round(timeout - (now - self.stage_started), 1)),
                    preparation_mode=self.preparation_mode, diagnostics=dict(self.diagnostics),
                    frame_timing=dict(self.frame_timing),
                    observation_status=self.observation_status,
                    head_pose=deepcopy(self.head_pose), tasks=deepcopy(self.tasks),
                    identity_continuity_checked=self.verify_identity,
                    elapsed_seconds=round(now - self.started, 2),
                    result='PASS' if self.stage == 'passed' else 'FAIL' if self.stage == 'failed' else None,
                    access_granted=False, experimental=True)
