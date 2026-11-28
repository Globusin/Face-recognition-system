"""Измерение ложного объёма плоской доски и разброса глубины"""

import numpy as np


def measure_planarity(points):
    points = np.asarray(points, dtype=np.float64)
    if points.shape != (49, 3) or not np.isfinite(points).all():
        raise ValueError('Нужно 49 корректных 3D-точек доски')

    centered = points - points.mean(axis=0)
    _, singular_values, directions = np.linalg.svd(centered, full_matrices=False)
    if singular_values[1] < 1e-8:
        raise ValueError('Точки не позволяют определить плоскость')

    # Последний вектор SVD — нормаль плоскости с наименьшей ошибкой
    distances = np.abs(centered @ directions[-1])
    return dict(plane_mean_mm=float(distances.mean()),
                plane_rms_mm=float(np.sqrt(np.mean(distances ** 2))),
                plane_p95_mm=float(np.percentile(distances, 95)),
                plane_max_mm=float(distances.max()))


def measure_depth_stability(point_series):
    points = np.asarray(point_series, dtype=np.float64)
    if points.ndim != 3 or points.shape[1:] != (49, 3) or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError('Для оценки стабильности нужны минимум три набора 3D-точек')

    # Сравниваем глубину одних и тех же углов без вычитания движения доски
    depths = points[:, :, 2]
    point_std = depths.std(axis=0, ddof=1)
    center_depths = depths.mean(axis=1)
    return dict(frames=len(points), mean_depth_mm=float(depths.mean()),
                point_depth_std_mean_mm=float(point_std.mean()),
                point_depth_std_max_mm=float(point_std.max()),
                center_depth_std_mm=float(center_depths.std(ddof=1)),
                center_depth_range_mm=float(np.ptp(center_depths)))
