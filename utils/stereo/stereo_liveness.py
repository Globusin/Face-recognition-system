"""Проверка объёма лица по двум камерам

Пороги классификатора не подтверждены на размеченной выборке. В режиме
advisory результат только сохраняется для диагностики; в режиме required
политика допуска использует LIVE/SPOOF/UNKNOWN, а недостаток данных
запрещает доступ
"""

import math
import threading
import time
from pathlib import Path

from utils.access.authentication import CheckResult, CheckStatus
from utils.common.logger import log_error, log_info, log_warning
from utils.stereo.stereo_calibration import camera_signature, load_calibration
from utils.stereo.two_view_pad import inspect_pair

LIVE = 'LIVE'
SPOOF = 'SPOOF'
UNKNOWN = 'UNKNOWN'

# Соответствие трём результатам будущей обязательной проверки в автомате
CHECK_STATUS = {LIVE: 'PASS', SPOOF: 'FAIL', UNKNOWN: 'NOT_AVAILABLE'}

DEFAULT_CLASSIFIER = dict(
    min_points=25,              # 31 точка: минимум для устойчивой плоскости
    max_reprojection_px=4.0,
    max_vertical_px=8.0,
    flat_plane_rms_mm=1.5,      # Ниже этого рельеф считается плоским
    flat_nose_eye_mm=1.0,
    live_plane_rms_mm=2.0,      # Выше этого рельеф похож на объёмное лицо
    live_nose_eye_mm=3.0,
    max_plane_rms_mm=12.0,      # Слишком большой рельеф — не доказательство лица
    max_nose_eye_mm=22.0,
    min_valid_fraction=0.25,
    min_valid_pixels=100,
)


def _number(value, name, *, allow_zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} должен быть числом')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(f'{name} должен быть конечным числом')
    if allow_zero and value < 0:
        raise ValueError(f'{name} не может быть отрицательным')
    if not allow_zero and value <= 0:
        raise ValueError(f'{name} должен быть положительным')
    return value


def _count(value, name, minimum):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{name} должен быть целым числом не меньше {minimum}')
    return value


def liveness_settings(config):
    """Проверяет и дополняет настройки диагностической проверки"""
    section = config.get('stereo_liveness', {}) or {}
    mode = str(section.get('mode', 'off')).strip().lower()
    if mode not in ('off', 'advisory', 'required'):
        raise ValueError(f'Неизвестный режим стереопроверки: {mode}')
    parallel = section.get('parallel') is True
    result_timeout = _number(
        section.get('result_timeout_s', 1.5), 'result_timeout_s',
    )
    dense_depth = bool(section.get('dense_depth', False))
    mounting_confirmed = section.get('mounting_confirmed') is True

    calibration_id = section.get('calibration_id')
    if calibration_id is not None and (
        not isinstance(calibration_id, str) or len(calibration_id) != 32
        or any(char not in '0123456789abcdef' for char in calibration_id)
    ):
        raise ValueError('Неверный номер калибровки в stereo_liveness')

    classifier = dict(DEFAULT_CLASSIFIER)
    provided = section.get('classifier') or {}
    for key in classifier:
        if key in provided:
            classifier[key] = provided[key]

    classifier['min_points'] = _count(classifier['min_points'], 'min_points', 3)
    classifier['min_valid_pixels'] = _count(
        classifier['min_valid_pixels'], 'min_valid_pixels', 1,
    )
    for key in ('flat_plane_rms_mm', 'flat_nose_eye_mm'):
        classifier[key] = _number(classifier[key], key, allow_zero=True)
    for key in ('live_plane_rms_mm', 'live_nose_eye_mm',
                'max_plane_rms_mm', 'max_nose_eye_mm',
                'max_reprojection_px', 'max_vertical_px'):
        classifier[key] = _number(classifier[key], key)
    classifier['min_valid_fraction'] = _number(
        classifier['min_valid_fraction'], 'min_valid_fraction',
    )
    if classifier['min_valid_fraction'] > 1:
        raise ValueError('min_valid_fraction должен быть не больше 1')
    if classifier['live_plane_rms_mm'] <= classifier['flat_plane_rms_mm']:
        raise ValueError('live_plane_rms_mm должен быть больше flat_plane_rms_mm')
    if classifier['max_plane_rms_mm'] < classifier['live_plane_rms_mm']:
        raise ValueError('max_plane_rms_mm не может быть меньше live_plane_rms_mm')
    if classifier['live_nose_eye_mm'] <= classifier['flat_nose_eye_mm']:
        raise ValueError('live_nose_eye_mm должен быть больше flat_nose_eye_mm')
    if classifier['max_nose_eye_mm'] < classifier['live_nose_eye_mm']:
        raise ValueError('max_nose_eye_mm не может быть меньше live_nose_eye_mm')

    return dict(
        mode=mode,
        parallel=parallel,
        result_timeout=result_timeout,
        calibration_id=calibration_id,
        mounting_confirmed=mounting_confirmed,
        dense_depth=dense_depth,
        classifier=classifier,
    )


def check_status(decision):
    """Переводит решение классификатора в статус проверки автомата"""
    return CHECK_STATUS.get(decision, 'NOT_AVAILABLE')


def _metric(metrics, name):
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def rule_based_classifier(inspection, settings, calibration_status=None):
    """Правила LIVE/SPOOF/UNKNOWN по метрикам одной пары

    Сигнатура подходит и для будущей ML-модели: на вход результат inspect_pair,
    на выходе решение, причина и признаки. Недостаток данных даёт UNKNOWN,
    а не SPOOF: отказ измерения не является доказательством подделки
    """
    metrics = inspection.get('metrics') or {}
    dense = inspection.get('dense_depth') or {}
    features = dict(
        points=_metric(metrics, 'points'),
        plane_rms_mm=_metric(metrics, 'plane_rms_mm'),
        nose_eye_plane_difference_mm=_metric(metrics, 'nose_eye_plane_difference_mm'),
        reprojection_max_px=_metric(metrics, 'reprojection_max_px'),
        vertical_max_px=_metric(metrics, 'vertical_max_px'),
        valid_fraction=_metric(dense, 'valid_fraction'),
        valid_pixels=_metric(dense, 'valid_pixels'),
        dense_status=dense.get('status'),
    )

    if calibration_status != 'validated':
        return UNKNOWN, 'Калибровка не подтверждена на независимых данных', features
    if inspection.get('status') != 'measured':
        return UNKNOWN, inspection.get('reason') or 'Геометрия лица не измерена', features

    required = ('points', 'plane_rms_mm', 'nose_eye_plane_difference_mm',
                'reprojection_max_px', 'vertical_max_px')
    missing = [name for name in required if features[name] is None]
    if missing:
        return UNKNOWN, 'Не хватает метрик геометрии: ' + ', '.join(missing), features

    # Качество соответствий проверяется раньше решения о рельефе
    if features['points'] < settings['min_points']:
        return UNKNOWN, 'Слишком мало точек лица для оценки объёма', features
    if features['reprojection_max_px'] > settings['max_reprojection_px']:
        return UNKNOWN, 'Слишком большая ошибка репроекции точек', features
    if features['vertical_max_px'] > settings['max_vertical_px']:
        return UNKNOWN, 'Соответствия точек несогласованы по вертикали', features

    if dense.get('status') == 'measured':
        fraction, pixels = features['valid_fraction'], features['valid_pixels']
        if fraction is None or pixels is None:
            return UNKNOWN, 'Плотная карта глубины без метрик', features
        if (fraction < settings['min_valid_fraction']
                or pixels < settings['min_valid_pixels']):
            return UNKNOWN, 'Недостаточно надёжных пикселей глубины', features

    plane_rms = features['plane_rms_mm']
    nose_eye = features['nose_eye_plane_difference_mm']
    # Объёмный предмет с чрезмерным рельефом не считается живым лицом
    if plane_rms > settings['max_plane_rms_mm'] or nose_eye > settings['max_nose_eye_mm']:
        return UNKNOWN, 'Рельеф не соответствует проверенному диапазону лица', features
    if (plane_rms <= settings['flat_plane_rms_mm']
            and nose_eye <= settings['flat_nose_eye_mm']):
        return SPOOF, 'Плоская поверхность лица', features
    if (plane_rms >= settings['live_plane_rms_mm']
            and nose_eye >= settings['live_nose_eye_mm']):
        return LIVE, 'Рельеф соответствует объёмному лицу', features
    return UNKNOWN, 'Рельеф в непроверенной переходной зоне', features


def measure_pair(pair, arrays, image_size, limits, settings, *,
                 dense_depth=False, calibration_status='validated', classifier=None):
    """Измеряет одну пару кадров и классифицирует её без разрешения доступа"""
    started = time.perf_counter()
    # Профиль времени камер в Monitor не проверяется, поэтому допустим
    # только статический диагностический предел рассинхронизации
    inspection = inspect_pair(pair, arrays, image_size, limits,
                              static_diagnostic=True, dense_depth=dense_depth)
    classify = classifier or rule_based_classifier
    decision, reason, features = classify(inspection, settings, calibration_status)
    return dict(
        version=1,
        algorithm='stereo_face_31_rule_v1',
        status=inspection.get('status'),
        decision=decision,
        reason=reason,
        features=features,
        metrics=inspection.get('metrics'),
        sparse=inspection.get('sparse_geometry'),
        dense=inspection.get('dense_depth'),
        diagnostics=inspection.get('diagnostics'),
        calibration_status=calibration_status,
        pair_number=getattr(pair, 'number', None),
        delta_ms=getattr(pair, 'delta_ms', None),
        timing_verified=False,
        diagnostic_only=True,
        access_granted=False,
        decision_source='ml' if classifier is not None else 'rule_based',
        elapsed_seconds=time.perf_counter() - started,
    )


class StereoLivenessDiagnostics:
    """Диагностический замер пары в Monitor

    Калибровка загружается один раз и только в статусе validated. Любая ошибка
    возвращается как причина UNKNOWN и не влияет на решение о доступе
    """

    def __init__(self, manager, settings, calibration_root, limits,
                 classifier=None, clock=time.monotonic):
        self.manager = manager
        self.settings = settings
        self.calibration_root = Path(calibration_root)
        self.limits = limits
        self.classifier = classifier
        self.clock = clock
        self._loaded = None
        self._failure = None

    def measure(self, pair):
        metadata, arrays = self._calibration()
        if camera_signature(self.manager) != metadata['cameras']:
            raise ValueError('Режим камер не совпадает с сохранённой калибровкой')
        limits = dict(self.limits, max_delta_ms=self.limits['static_max_delta_ms'])
        return measure_pair(
            pair, arrays, metadata['image_size'], limits,
            self.settings['classifier'],
            dense_depth=self.settings['dense_depth'],
            calibration_status=metadata.get('status'),
            classifier=self.classifier,
        )

    def _calibration(self):
        if self._loaded is not None:
            return self._loaded
        if not self.settings['calibration_id']:
            raise ValueError(
                'Калибровка недоступна: не задан номер калибровки в stereo_liveness'
            )
        if not self.settings['mounting_confirmed']:
            raise ValueError(
                'Калибровка недоступна: не подтверждена неизменность крепления камер'
            )
        if self._failure is not None:
            raise ValueError(self._failure)

        try:
            folder = self.calibration_root / self.settings['calibration_id']
            metadata, arrays = load_calibration(
                folder, camera_signature(self.manager), mounting_confirmed=True,
            )
            if metadata.get('units') != 'mm':
                raise ValueError('нужна калибровка в миллиметрах')
        except (OSError, ValueError, KeyError) as error:
            self._failure = f'Калибровка недоступна: {error}'
            raise ValueError(self._failure) from None

        self._loaded = (metadata, arrays)
        return self._loaded


class StereoWorker:
    """Один рабочий поток: замер объёма идёт во время распознавания

    Очередь не растёт: пока замер выполняется, новое задание пропускается.
    Результат привязан к session_id и не переиспользуется другой сессией
    """

    def __init__(self, diagnostics, clock=time.monotonic):
        self.diagnostics = diagnostics
        self.clock = clock
        self._lock = threading.Lock()
        self._thread = None
        self._latest = None
        self._closed = False
        self.skipped = 0
        self.completed = 0

    def submit(self, session_id, pair):
        """Запускает замер пары, не дожидаясь результата"""
        with self._lock:
            if self._closed:
                return False
            if self._thread is not None and self._thread.is_alive():
                self.skipped += 1
                return False
            self._thread = threading.Thread(
                target=self._run, args=(session_id, pair),
                name='stereo-worker', daemon=True,
            )
            self._thread.start()
            return True

    def take(self, session_id, timeout):
        """Возвращает результат только для этой сессии или None по таймауту"""
        deadline = self.clock() + timeout
        while True:
            with self._lock:
                if self._latest is not None and self._latest[0] == session_id:
                    return self._latest[1]
            if self.clock() >= deadline:
                return None
            time.sleep(0.01)

    def close(self, timeout=1.0):
        with self._lock:
            self._closed = True
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self, session_id, pair):
        try:
            result = self.diagnostics.measure(pair)
        except Exception as error:
            log_warning(f'Стерео-замер недоступен: {error}')
            result = dict(
                decision=UNKNOWN, status='not_measured', reason=str(error),
                diagnostic_only=True, access_granted=False, timing_verified=False,
            )
        with self._lock:
            self._latest = (session_id, result)
            self.completed += 1


class StereoCheck:
    """Проверка объёма лица как проверка сессии

    В режиме required проверка обязательна: PASS только при LIVE, при
    SPOOF или отсутствии данных доступ запрещается. В advisory результат
    только сохраняется в diagnostics и не влияет на допуск
    """

    def __init__(self, diagnostics, mode, worker=None, timeout=1.5):
        if mode not in ('advisory', 'required'):
            raise ValueError('Стереопроверка должна быть advisory или required')
        self.diagnostics = diagnostics
        self.mode = mode
        self.worker = worker
        self.timeout = timeout
        self.source = None

    def bind(self, source):
        if self.source is not None:
            raise RuntimeError('Источник наблюдений уже привязан')
        self.source = source

    def release(self):
        self.source = None

    def __call__(self, session):
        result = self._measure(session)
        if result is None:
            status = (CheckStatus.NOT_AVAILABLE if self.mode == 'required'
                      else CheckStatus.SKIPPED)
            return CheckResult(status, 'stereo_not_ready')
        session.diagnostics['stereo'] = result
        decision = result.get('decision')
        if decision == SPOOF:
            # SPOOF — обнаруженная атака, независимо от режима проверки
            return CheckResult(CheckStatus.FAIL, 'liveness_spoof')
        if self.mode != 'required':
            # advisory разрешить доступ не может, только запретить по SPOOF
            return CheckResult(CheckStatus.SKIPPED, 'advisory')
        if decision == LIVE:
            return CheckResult(CheckStatus.PASS, 'stereo_live')
        return CheckResult(
            CheckStatus.NOT_AVAILABLE,
            result.get('reason') or 'stereo_inconclusive',
        )

    def _measure(self, session):
        if self.worker is not None:
            return self.worker.take(session.session_id, self.timeout)
        if self.source is None:
            return None
        try:
            observation = self.source.next(session.deadline)
            if observation is None or observation.pair is None:
                return None
            return self.diagnostics.measure(observation.pair)
        except Exception as error:
            log_warning(f'Стерео-проверка недоступна: {error}')
            return None
