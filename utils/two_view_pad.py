"""Экспериментальные измерения лица с двух камер, без решения о доступе"""

import time

import cv2
import numpy as np


# Контур челюсти зависит от ракурса, губы — от выражения лица
# Для первого опыта используем 31 точку бровей, глаз и носа
LANDMARK_GROUPS = ('left_eyebrow', 'right_eyebrow', 'nose_bridge',
                   'nose_tip', 'left_eye', 'right_eye')
GROUP_LENGTHS = (5, 5, 4, 5, 6, 6)
GROUP_NAMES = ('левая бровь', 'правая бровь', 'переносица',
               'низ носа', 'левый глаз', 'правый глаз')
DEFAULT_LIMITS = dict(max_delta_ms=10.0, max_vertical_px=8.0,
                      max_reprojection_px=4.0, min_disparity_px=1.0,
                      min_depth_mm=150.0, max_depth_mm=2000.0, pair_wait_seconds=5.0,
                      max_exposure_error_ms=30.0, max_image_speed_px_s=25.0, max_depth_uncertainty_mm=5.0)


def measurement_limits(settings):
    limits = {key: settings.get(key, default) for key, default in DEFAULT_LIMITS.items()}
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not np.isfinite(value) or value <= 0 for value in limits.values()):
        raise ValueError('Пределы измерения геометрии лица должны быть положительными числами')
    if limits['min_depth_mm'] >= limits['max_depth_mm']:
        raise ValueError('Неверный диапазон глубины лица')
    return limits


def wait_for_measurement_pair(manager, limits, selection):
    """Пропускает неподходящие пары, не меняя общий режим камер"""
    started = time.monotonic()
    deadline = started + limits['pair_wait_seconds']
    after = manager.get_status()['pairing']['paired_frames']
    last_sequences = None
    selection.update(checked_pairs=0, skipped_pairs=0, minimum_delta_ms=None)
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            pair = manager.get_pair(after_number=after, timeout=remaining)
            if pair is None:
                break
            if pair.number <= after:
                raise ValueError('Получена повторная пара кадров')
            after = pair.number
            sequences = (pair.primary.sequence, pair.secondary.sequence)
            if last_sequences is not None and any(
                current <= previous for current, previous in zip(sequences, last_sequences)
            ):
                raise ValueError('Получены повторные кадры камер')
            last_sequences = sequences
            selection['checked_pairs'] += 1

            now = time.monotonic_ns()
            ages = [now - frame.timestamp_ns for frame in (pair.primary, pair.secondary)]
            delta = abs(pair.primary.timestamp_ns - pair.secondary.timestamp_ns) / 1_000_000
            fresh = all(0 <= age <= 1_000_000_000 for age in ages)
            if fresh:
                best = selection['minimum_delta_ms']
                selection['minimum_delta_ms'] = delta if best is None else min(best, delta)
            if fresh and delta <= limits['max_delta_ms']:
                return pair
            selection['skipped_pairs'] += 1
    finally:
        selection['wait_seconds'] = time.monotonic() - started

    if selection['minimum_delta_ms'] is not None:
        raise ValueError('Камеры не дали достаточно близкие по времени кадры: '
                         f'лучший рассинхрон {selection["minimum_delta_ms"]:.1f} мс, '
                         f'допустимо {limits["max_delta_ms"]:.1f} мс')
    raise ValueError('Не удалось получить свежую пару кадров от двух камер')


def extract_face_points(image):
    # Модели уже входят в face_recognition и загружаются библиотекой один раз
    import face_recognition

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=0, model='hog')
    if len(locations) != 1:
        raise ValueError('В каждой камере должно быть ровно одно лицо')

    landmarks = face_recognition.face_landmarks(rgb, face_locations=locations, model='large')
    if len(landmarks) != 1:
        raise ValueError('Не удалось получить точки лица')

    points = []
    for name, count in zip(LANDMARK_GROUPS, GROUP_LENGTHS):
        group = landmarks[0].get(name, [])
        if len(group) != count:
            raise ValueError('Неполный набор точек лица')
        points.extend(group)

    points = np.asarray(points, dtype=np.float64)
    height, width = image.shape[:2]
    if (points.shape != (31, 2) or not np.isfinite(points).all()
            or np.any(points < 0) or np.any(points >= [width, height])):
        raise ValueError('Точки лица выходят за границы кадра')
    return points


def measure_face_geometry(primary, secondary, arrays, limits, diagnostics=None):
    rectified = []
    for points, suffix in ((primary, '1'), (secondary, '2')):
        points = np.asarray(points, dtype=np.float64)
        if points.shape != (31, 2) or not np.isfinite(points).all():
            raise ValueError('Нужно 31 соответствие точек лица')
        rectified.append(cv2.undistortPoints(
            points.reshape(-1, 1, 2), arrays['k' + suffix], arrays['d' + suffix],
            R=arrays['R' + suffix], P=arrays['P' + suffix])[:, 0])

    if not all(np.isfinite(points).all() for points in rectified):
        raise ValueError('Некорректные координаты после выравнивания камер')
    vertical = np.abs(rectified[0][:, 1] - rectified[1][:, 1])
    worst_index = int(np.argmax(vertical))
    group_start = 0
    for name, count in zip(GROUP_NAMES, GROUP_LENGTHS):
        if worst_index < group_start + count:
            point_name = f'{name}, точка {worst_index - group_start + 1}'
            break
        group_start += count
    if diagnostics is not None:
        diagnostics.update(worst_point_number=worst_index + 1, worst_point_name=point_name,
                           vertical_mean_px=float(vertical.mean()), vertical_max_px=float(vertical.max()),
                           vertical_limit_px=limits['max_vertical_px'],
                           exceeding_points=int(np.count_nonzero(vertical > limits['max_vertical_px'])))
    if vertical.max() > limits['max_vertical_px']:
        raise ValueError(f'Точка №{worst_index + 1} ({point_name}): '
                         f'расхождение по вертикали {vertical.max():.2f} px, '
                         f'допустимо {limits["max_vertical_px"]:.2f} px')
    disparity = np.abs(rectified[0][:, 0] - rectified[1][:, 0])
    if disparity.min() < limits['min_disparity_px']:
        raise ValueError('Недостаточный параллакс для измерения глубины')

    homogeneous = cv2.triangulatePoints(arrays['P1'], arrays['P2'], rectified[0].T, rectified[1].T)
    if not np.isfinite(homogeneous).all() or np.any(np.abs(homogeneous[3]) < 1e-10):
        raise ValueError('Вырожденная триангуляция лица')
    xyz = (homogeneous[:3] / homogeneous[3]).T
    if (not np.isfinite(xyz).all() or np.any(xyz[:, 2] < limits['min_depth_mm'])
            or np.any(xyz[:, 2] > limits['max_depth_mm'])):
        raise ValueError('Глубина лица вне диапазона измерений')

    reprojection = []
    for matrix, expected in zip((arrays['P1'], arrays['P2']), rectified):
        projected = matrix @ np.vstack((xyz.T, np.ones(len(xyz))))
        if np.any(projected[2] <= 0):
            raise ValueError('Точки находятся за камерой')
        reprojection.extend(np.linalg.norm((projected[:2] / projected[2]).T - expected, axis=1))
    if max(reprojection) > limits['max_reprojection_px']:
        raise ValueError('Слишком большая ошибка репроекции точек лица')

    centered = xyz - xyz.mean(axis=0)
    _, singular_values, directions = np.linalg.svd(centered, full_matrices=False)
    if singular_values[1] < 1e-8:
        raise ValueError('Недостаточно пространственно разнесённых точек')

    # SVD подбирает плоскость с наименьшей суммой квадратов расстояний
    signed_distances = centered @ directions[-1]
    distances = np.abs(signed_distances)
    eye_indices = np.arange(19, 31)
    nose_indices = np.arange(14, 19)
    nose_eye_difference = abs(signed_distances[nose_indices].mean()
                              - signed_distances[eye_indices].mean())
    return dict(points=len(xyz), mean_depth_mm=float(xyz[:, 2].mean()),
                plane_mean_mm=float(distances.mean()),
                plane_rms_mm=float(np.sqrt(np.mean(distances ** 2))),
                plane_max_mm=float(distances.max()),
                nose_eye_plane_difference_mm=float(nose_eye_difference),
                vertical_mean_px=float(vertical.mean()), vertical_max_px=float(vertical.max()),
                reprojection_max_px=float(max(reprojection)))


def inspect_pair(pair, arrays, image_size, limits, temporal_context=None):
    """Одна программно согласованная пара, без повторного использования кадров"""
    started = time.perf_counter()
    images = {role: getattr(pair, role).image for role in ('primary', 'secondary')}
    points = {}
    diagnostics = {}
    try:
        frames = (pair.primary, pair.secondary)
        now = time.monotonic_ns()
        ages_ns = [now - frame.timestamp_ns for frame in frames]
        delta_ms = abs(frames[0].timestamp_ns - frames[1].timestamp_ns) / 1_000_000
        if any(age < 0 or age > 1_000_000_000 for age in ages_ns):
            raise ValueError('Пара кадров устарела')
        if delta_ms > limits['max_delta_ms']:
            raise ValueError('Кадры камер получены слишком далеко друг от друга по времени')
        if any(list(image.shape[1::-1]) != list(image_size) for image in images.values()):
            raise ValueError('Размер кадров не соответствует калибровке')

        points = {role: extract_face_points(image) for role, image in images.items()}
        metrics = measure_face_geometry(points['primary'], points['secondary'], arrays, limits, diagnostics)
        if temporal_context is None:
            raise ValueError('Не оценена временная точность камер')
        from utils.stereo_timing import timing_depth_uncertainty
        uncertainty = timing_depth_uncertainty(points, pair, temporal_context['previous'],
                                              temporal_context['profile'], arrays, limits)
        metrics.update(uncertainty)
        result = dict(status='measured', metrics=metrics)
    except (ValueError, RuntimeError, ImportError, cv2.error) as error:
        result = dict(status='not_measurable', reason=str(error))

    if diagnostics:
        result['diagnostics'] = diagnostics
    if len(points) == 2:
        try:
            result['previews'] = face_point_previews(images, points, diagnostics)
        except (ValueError, cv2.error) as error:
            result['preview_error'] = str(error)

    result['elapsed_seconds'] = time.perf_counter() - started
    return result


def face_point_previews(images, points, diagnostics):
    """Размечает исходные кадры даже при отказе геометрии, не сохраняя лица"""
    from utils.stereo_calibration import annotated_preview

    previews = {}
    for role, image in images.items():
        preview = image.copy()
        for index, point in enumerate(points[role]):
            position = tuple(np.rint(point).astype(int))
            is_worst = index + 1 == diagnostics.get('worst_point_number')
            color = (0, 0, 255) if is_worst else (0, 255, 0)
            cv2.circle(preview, position, 7 if is_worst else 3, color, 2 if is_worst else -1)
            cv2.putText(preview, str(index + 1), position, cv2.FONT_HERSHEY_SIMPLEX,
                        0.5 if is_worst else 0.35, color, 2 if is_worst else 1)
        previews[role] = annotated_preview(preview, None)
    return previews
