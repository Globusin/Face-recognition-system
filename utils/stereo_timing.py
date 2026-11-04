"""Эмпирическая относительная задержка по движению доски, не аппаратная синхронизация"""

import cv2
import numpy as np
import subprocess


def exposure_settings(manager):
    """Только чтение настроек V4L2, без автоматического изменения камер"""
    controls = ('auto_exposure', 'exposure_time_absolute', 'exposure_dynamic_framerate')
    settings = {}
    for role in ('primary', 'secondary'):
        source = manager.sources.get(role)
        device = f'/dev/video{source}' if isinstance(source, int) else str(source)
        try:
            result = subprocess.run(['v4l2-ctl', '--device', device, '--get-ctrl=' + ','.join(controls)],
                                    capture_output=True, text=True, timeout=2, check=True)
            values = {}
            for line in result.stdout.splitlines():
                name, separator, value = line.partition(':')
                if separator:
                    values[name.strip()] = int(value.strip())
            if set(values) != set(controls):
                raise ValueError('Неполные настройки экспозиции')
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            raise ValueError(f'Не удалось проверить экспозицию {role}; нужны доступные V4L2 controls') from error
        if values['auto_exposure'] != 1 or values['exposure_dynamic_framerate'] != 0 or values['exposure_time_absolute'] <= 0:
            raise ValueError(f'Для теста времени {role} нужны ручная выдержка и выключенный динамический FPS')
        settings[role] = values
    return settings


def rectified_points(points, arrays, suffix):
    return cv2.undistortPoints(np.asarray(points, dtype=np.float64).reshape(-1, 1, 2),
        arrays['k' + suffix], arrays['d' + suffix], R=arrays['R' + suffix], P=arrays['P' + suffix])[:, 0]


def estimate_timing(samples):
    """Сдвигает временную ось secondary, подбирая совпадение вертикальных траекторий"""
    series = {}
    for role in ('primary', 'secondary'):
        values = np.asarray(samples[role], dtype=np.float64)
        if (values.ndim != 2 or values.shape[1] != 2 or len(values) < 30
                or not np.isfinite(values).all() or np.any(np.diff(values[:, 0]) <= 0)):
            raise ValueError('Для теста времени нужны минимум 30 последовательных наблюдений каждой камеры')
        if values[-1, 0] - values[0, 0] < 8 or np.ptp(values[:, 1]) < 40:
            raise ValueError('Недостаточная длительность или амплитуда движения доски')
        changes = np.diff(values[:, 1])
        signs = np.sign(changes[np.abs(changes) > 1])
        if np.count_nonzero(np.diff(signs)) < 2:
            raise ValueError('Нужны несколько смен направления движения доски')
        series[role] = values

    primary, secondary = series['primary'], series['secondary']
    # Общая область неизменна для всех кандидатов, без экстраполяции краёв
    reference = primary[(primary[:, 0] >= max(primary[0, 0], secondary[0, 0] + .3))
                        & (primary[:, 0] <= min(primary[-1, 0], secondary[-1, 0] - .3))]
    if len(reference) < 24:
        raise ValueError('Недостаточно общего участка траекторий')
    shifts = np.arange(-.3, .3001, .002)

    def fit(part):
        errors = np.array([np.sqrt(np.mean((part[:, 1] - np.interp(
            part[:, 0], secondary[:, 0] + shift, secondary[:, 1])) ** 2)) for shift in shifts])
        best = int(np.argmin(errors))
        if best in (0, len(shifts) - 1):
            raise ValueError('Оценка задержки упёрлась в границу поиска ±300 мс')
        plausible = shifts[errors <= errors[best] + .5]
        if np.ptp(plausible) > .1:
            raise ValueError('Задержка неоднозначна: измените ритм движения доски')
        return float(shifts[best]), float(errors[best])

    shift, residual = fit(reference)
    segments = [fit(part)[0] for part in np.array_split(reference, 3)]
    if residual > 3:
        raise ValueError('Траектории не согласуются после временного сдвига: ошибка более 3 px')
    gap = max(float(np.diff(values[:, 0]).max()) for values in series.values())
    # Рабочая оценка: половина наибольшего интервала, разброс трёх участков и шаг поиска
    uncertainty = gap / 2 + max(abs(value - shift) for value in segments) + .001
    return dict(offset_ms=shift * 1000, uncertainty_ms=uncertainty * 1000,
                residual_rms_px=residual, maximum_sample_gap_ms=gap * 1000,
                segment_offsets_ms=[value * 1000 for value in segments],
                timestamp_source='read_complete_monotonic', hardware_synchronized=False,
                rolling_shutter_assessed=False,
                uncertainty_kind='empirical_envelope_not_certified_bound')


def check_timing_profile(profile, calibration_id, fingerprint, status, now, confirmed):
    if confirmed is not True:
        raise ValueError('Подтвердите неизменность света и настроек камер после теста времени')
    if not profile or profile.get('status') != 'measured':
        raise ValueError('Сначала выполните тест времени с движущейся доской')
    if (profile.get('calibration_id') != calibration_id or profile.get('fingerprint') != fingerprint
            or profile.get('run_id') != status.get('run_id') or not status.get('run_id')):
        raise ValueError('Тест времени не соответствует калибровке или текущему запуску камер')
    if not 0 <= now - profile['created_monotonic'] <= 600:
        raise ValueError('Тест времени устарел, повторите его')
    for role in ('primary', 'secondary'):
        previous = profile['recent_fps'][role]
        current = status['cameras'][role].get('recent_fps', 0)
        if previous <= 0 or current <= 0 or abs(current / previous - 1) > .2:
            raise ValueError('Частота камеры изменилась более чем на 20 %, повторите тест времени')


def timing_depth_uncertainty(points, pair, previous, profile, arrays, limits):
    corrected = []
    speeds = []
    for role, suffix in (('primary', '1'), ('secondary', '2')):
        current = rectified_points(points[role], arrays, suffix)
        earlier = rectified_points(previous['points'][role], arrays, suffix)
        elapsed = (getattr(pair, role).timestamp_ns - previous['timestamps'][role]) / 1e9
        if not 0 < elapsed <= 3:
            raise ValueError('Недостаточно свежих последовательных точек для оценки движения')
        speeds.append(float(np.max(np.linalg.norm(current - earlier, axis=1)) / elapsed))
        corrected.append(current)
    if max(speeds) > limits['max_image_speed_px_s']:
        raise ValueError('Лицо движется слишком быстро для временной точности стереопары')

    arrival_difference = (pair.primary.timestamp_ns - pair.secondary.timestamp_ns) / 1e6
    # V4L2 exposure_time_absolute задаётся в единицах 100 мкс
    exposures = [profile['exposure_controls'][role]['exposure_time_absolute'] for role in ('primary', 'secondary')]
    integration_margin = sum(exposures) * .05
    timing_error = (abs(arrival_difference - profile['estimate']['offset_ms'])
                    + profile['estimate']['uncertainty_ms'] + integration_margin)
    if timing_error > limits['max_exposure_error_ms']:
        raise ValueError(f'Временная неопределённость {timing_error:.1f} мс превышает '
                         f'предел {limits["max_exposure_error_ms"]:.1f} мс')
    if not np.allclose(arrays['P1'][:, :3], arrays['P2'][:, :3]):
        raise ValueError('Модель погрешности требует одинаковых ректифицированных матриц камер')
    disparity = np.abs(corrected[0][:, 0] - corrected[1][:, 0])
    # Оценка условна: истинная скорость между кадрами должна оставаться в разрешённом диапазоне
    disparity_error = 2 * limits['max_image_speed_px_s'] * timing_error / 1000
    if np.any(disparity <= disparity_error):
        raise ValueError('Временная ошибка слишком велика относительно параллакса')
    focal_baseline = abs(arrays['P1'][0, 3] - arrays['P2'][0, 3])
    depth_error = focal_baseline * disparity_error / (disparity * (disparity - disparity_error))
    result = dict(estimated_exposure_error_ms=float(timing_error),
                  exposure_integration_margin_ms=float(integration_margin),
                  observed_image_speed_px_s=max(speeds), timing_depth_uncertainty_mm=float(depth_error.max()),
                  assumed_speed_limit_px_s=limits['max_image_speed_px_s'],
                  uncertainty_kind='conditional_timing_only_not_total_error')
    if depth_error.max() > limits['max_depth_uncertainty_mm']:
        raise ValueError(f'Временная погрешность глубины {depth_error.max():.2f} мм превышает '
                         f'предел {limits["max_depth_uncertainty_mm"]:.2f} мм')
    return result
