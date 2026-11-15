"""Плотная глубина внутренней области лица, только статический эксперимент"""

import base64
import time

import cv2
import numpy as np


def encode_preview(image):
    success, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not success:
        raise ValueError('Не удалось подготовить карту глубины')
    return 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii')


def region_mask(shape, points, radius=0):
    mask = np.zeros(shape, dtype=np.uint8)
    polygon = cv2.convexHull(np.rint(points).astype(np.int32))
    cv2.fillConvexPoly(mask, polygon, 1)
    if radius:
        mask = cv2.dilate(mask, np.ones((2 * radius + 1, 2 * radius + 1), np.uint8))
    return mask.astype(bool)


def plane_statistics(xyz):
    center = xyz.mean(axis=0)
    _, singular_values, directions = np.linalg.svd(xyz - center, full_matrices=False)
    if singular_values[1] < 1e-8:
        raise ValueError('Недостаточно разнесённых точек глубины')
    normal = directions[-1]
    if normal[2] < 0:
        normal = -normal
    signed = (xyz - center) @ normal
    absolute = np.abs(signed)
    return dict(mean_depth_mm=float(xyz[:, 2].mean()),
                plane_mean_mm=float(absolute.mean()), plane_rms_mm=float(np.sqrt(np.mean(signed ** 2))),
                plane_p95_mm=float(np.percentile(absolute, 95)), plane_max_mm=float(absolute.max())), signed


def disparity_consistency(left, right, minimum_left, minimum_right):
    """Проверяет обратное соответствие без заполнения дыр интерполяцией"""
    rows, columns = np.indices(left.shape)
    matched_x = np.rint(columns - left).astype(np.int32)
    inside = (matched_x >= 0) & (matched_x < left.shape[1])
    safe_x = np.clip(matched_x, 0, left.shape[1] - 1)
    reverse = right[rows, safe_x]
    valid = inside & (left > minimum_left - 1) & (reverse > minimum_right - 1)
    valid &= np.abs(left + reverse) <= 1.0
    return valid, safe_x


def rectify_face_observations(pair, arrays, points):
    original_height, original_width = pair.primary.image.shape[:2]
    width = min(640, original_width)
    height = max(1, round(original_height * width / original_width))
    scale = np.array([width / original_width, height / original_height])
    images, rectified_points, valid_sources = [], [], []
    for role, suffix in (('primary', '1'), ('secondary', '2')):
        image = getattr(pair, role).image
        map_x, map_y = arrays[f'map{suffix}_x'], arrays[f'map{suffix}_y']
        rectified = cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
        gray = cv2.cvtColor(rectified, cv2.COLOR_BGR2GRAY)
        images.append(cv2.resize(gray, (width, height), interpolation=cv2.INTER_AREA))
        source_mask = ((map_x >= 0) & (map_x < original_width - 1)
                       & (map_y >= 0) & (map_y < original_height - 1)).astype(np.uint8)
        source_mask = cv2.resize(source_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        valid_sources.append(cv2.erode(source_mask, np.ones((5, 5), np.uint8)).astype(bool))
        coordinates = cv2.undistortPoints(points[role].reshape(-1, 1, 2), arrays['k' + suffix],
            arrays['d' + suffix], R=arrays['R' + suffix], P=arrays['P' + suffix])[:, 0]
        rectified_points.append((coordinates + .5) * scale - .5)
    return images, rectified_points, valid_sources, scale


def match_face_disparities(images, rectified_points):

    # Landmarks задают лишь диапазон поиска, не значения плотной карты
    coarse_disparity = rectified_points[0][:, 0] - rectified_points[1][:, 0]
    minimum = max(0, int(np.floor(coarse_disparity.min())) - 16)
    maximum = int(np.ceil(coarse_disparity.max())) + 16
    count = max(16, int(np.ceil((maximum - minimum + 1) / 16)) * 16)
    if minimum + count >= images[0].shape[1] - 5:
        raise ValueError('Недостаточно ширины изображения для диапазона StereoSGBM')
    right_minimum = -minimum - count + 1
    parameters = dict(numDisparities=count, blockSize=5, P1=8 * 25, P2=32 * 25,
                      uniquenessRatio=10, speckleWindowSize=50, speckleRange=2,
                      disp12MaxDiff=1, preFilterCap=31, mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY)
    match_started = time.perf_counter()
    left_disparity = cv2.StereoSGBM_create(minDisparity=minimum, **parameters).compute(*images).astype(np.float32) / 16
    right_disparity = cv2.StereoSGBM_create(minDisparity=right_minimum, **parameters).compute(*images[::-1]).astype(np.float32) / 16
    match_ms = (time.perf_counter() - match_started) * 1000
    settings = dict(min_disparity=minimum, right_min_disparity=right_minimum,
                    num_disparities=count, matching_ms=match_ms, sgbm_parameters=parameters)
    return left_disparity, right_disparity, settings


def measure_dense_depth(pair, arrays, points, limits):
    started = time.perf_counter()
    projections = (arrays['P1'], arrays['P2'])
    if (not np.allclose(projections[0][:, :3], projections[1][:, :3])
            or not np.allclose(projections[0][1:], projections[1][1:])):
        raise ValueError('StereoSGBM требует горизонтальную ректификацию с общей матрицей камеры')
    focal_baseline = float(projections[0][0, 3] - projections[1][0, 3])
    if focal_baseline <= 0:
        raise ValueError('Для StereoSGBM нужен положительный параллакс primary относительно secondary')

    images, rectified_points, valid_sources, scale = rectify_face_observations(pair, arrays, points)
    height, width = images[0].shape
    left_disparity, right_disparity, matching = match_face_disparities(images, rectified_points)
    minimum = matching['min_disparity']
    right_minimum = matching['right_min_disparity']
    count = matching['num_disparities']
    valid, matched_x = disparity_consistency(left_disparity, right_disparity, minimum, right_minimum)
    rows, columns = np.indices((height, width))
    face = region_mask((height, width), rectified_points[0]) & valid_sources[0]
    right_face = region_mask((height, width), rectified_points[1]) & valid_sources[1]
    valid &= face & right_face[rows, matched_x]
    valid &= (left_disparity > minimum + .5) & (left_disparity < minimum + count - 1.5)

    # Однородную кожу нельзя считать надёжной глубиной только по цвету карты
    for image, is_right in ((images[0], False), (images[1], True)):
        values = image.astype(np.float32)
        variance = cv2.boxFilter(values ** 2, -1, (9, 9)) - cv2.boxFilter(values, -1, (9, 9)) ** 2
        texture = variance >= 25  # СКО яркости минимум 5 из 255
        valid &= texture[rows, matched_x] if is_right else texture

    disparity = left_disparity / scale[0] - (projections[0][0, 2] - projections[1][0, 2])
    depth = np.full((height, width), np.nan, dtype=np.float32)
    np.divide(focal_baseline, disparity, out=depth, where=disparity > 0)
    valid &= np.isfinite(depth) & (depth >= limits['min_depth_mm']) & (depth <= limits['max_depth_mm'])
    fraction = float(np.count_nonzero(valid) / max(1, np.count_nonzero(face)))
    result = dict(status='not_measurable', algorithm='sgbm_inner_face_v1', valid_fraction=fraction, valid_pixels=int(valid.sum()),
                  resolution=[width, height], block_size=5, texture_std_min=5, left_right_max_px=1,
                  roi='convex_hull_of_31_landmarks', minimum_valid_pixels=100, region_min_valid_pixels=10,
                  minimum_valid_fraction=.25, relief_display_range_mm=[-30, 30],
                  depth_display_range_mm=[limits['min_depth_mm'], limits['max_depth_mm']],
                  search_range_source='facial_landmarks', stationarity_verified=False, **matching)
    if fraction < .25 or valid.sum() < 100:
        result['reason'] = 'Недостаточно надёжных пикселей StereoSGBM в области лица'
        result['elapsed_seconds'] = time.perf_counter() - started
        return result, {}

    u = (columns[valid] + .5) / scale[0] - .5
    v = (rows[valid] + .5) / scale[1] - .5
    z = depth[valid]
    xyz = np.column_stack((((u - projections[0][0, 2]) * z - projections[0][0, 3]) / projections[0][0, 0],
                           ((v - projections[0][1, 2]) * z - projections[0][1, 3]) / projections[0][1, 1], z))
    metrics, signed = plane_statistics(xyz)
    nose = region_mask((height, width), rectified_points[0][14:19], radius=3)
    eyes = (region_mask((height, width), rectified_points[0][19:25], radius=3)
            | region_mask((height, width), rectified_points[0][25:31], radius=3))
    result['nose_valid_pixels'] = int(np.count_nonzero(nose & valid))
    result['eyes_valid_pixels'] = int(np.count_nonzero(eyes & valid))
    if min(result['nose_valid_pixels'], result['eyes_valid_pixels']) < 10:
        result['reason'] = 'Недостаточно пикселей глубины носа или глаз'
        result['elapsed_seconds'] = time.perf_counter() - started
        return result, {}
    metrics['nose_eye_plane_difference_mm'] = float(abs(np.median(signed[nose[valid]]) - np.median(signed[eyes[valid]])))
    result.update(status='measured', metrics=metrics, elapsed_seconds=time.perf_counter() - started)
    depth_colors = np.zeros((height, width), np.uint8)
    depth_colors[valid] = np.clip((z - limits['min_depth_mm']) / (limits['max_depth_mm'] - limits['min_depth_mm']) * 255, 0, 255)
    relief_colors = np.zeros((height, width), np.uint8)
    relief_colors[valid] = np.clip((signed + 30) / 60 * 255, 0, 255)
    previews = {}
    for name, colors in (('dense_depth', depth_colors), ('dense_relief', relief_colors)):
        colored = cv2.applyColorMap(colors, cv2.COLORMAP_TURBO)
        colored[~valid] = 0
        previews[name] = encode_preview(colored)
    return result, previews
