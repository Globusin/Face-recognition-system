"""Приближённая поза головы для диагностики, не критерий живости"""

import cv2
import numpy as np


# Обобщённая модель: нос, подбородок, центры глаз и углы рта
# Оси: X вправо по изображению, Y вниз, Z от камеры
FACE_MODEL = np.array([
    [0, 0, 0],         # Кончик носа, начало координат
    [0, 65, -15],      # Подбородок
    [-32, -30, -25],   # Центр глаза слева на изображении
    [32, -30, -25],    # Центр глаза справа на изображении
    [-25, 30, -20],    # Угол рта слева на изображении
    [25, 30, -20],     # Угол рта справа на изображении
], dtype=np.float64)


def estimate_head_pose(face, image_size):
    """solvePnP с приближённой камерой, без гарантии точности градусов"""
    try:
        eye_centers = [
            np.mean(face['left_eye'], axis=0),
            np.mean(face['right_eye'], axis=0),
        ]
        mouth_corners = [face['top_lip'][0], face['top_lip'][6]]

        # Порядок точек должен совпадать с FACE_MODEL: сначала левая по кадру
        eye_centers = sorted(eye_centers, key=lambda point: point[0])
        mouth_corners = sorted(mouth_corners, key=lambda point: point[0])

        image_points = np.asarray([
            face['nose_tip'][2],
            face['chin'][8],
            *eye_centers,
            *mouth_corners,
        ], dtype=np.float64)

        width, height = image_size
        if image_points.shape != (6, 2) or not np.isfinite(image_points).all():
            raise ValueError('Неполные точки для оценки позы')
        if np.any(image_points < 0) or np.any(image_points >= [width, height]):
            raise ValueError('Точки позы вне кадра')

        # Это приближение, не калибровка: фокус равен ширине кадра в пикселях
        # Оптический центр принимаем в середине, искажения объектива не учитываем
        camera_matrix = np.array([
            [width, 0, width / 2],
            [0, width, height / 2],
            [0, 0, 1],
        ], dtype=float)
        distortion_coefficients = np.zeros(5)

        # Подбираем поворот и смещение 3D-модели относительно камеры
        success, rotation_vector, translation_vector = cv2.solvePnP(
            FACE_MODEL,
            image_points,
            camera_matrix,
            distortion_coefficients,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not success:
            raise ValueError('Не удалось оценить позу')

        # Rodrigues переводит вектор поворота в матрицу для преобразования точек
        rotation_matrix, _ = cv2.Rodrigues(rotation_vector)
        camera_points = (rotation_matrix @ FACE_MODEL.T + translation_vector).T

        # В системе камеры положительная Z означает, что точка перед объективом
        if not np.isfinite(camera_points).all() or np.any(camera_points[:, 2] <= 0):
            raise ValueError('Некорректная поза головы')

        # Проецируем модель обратно в кадр и сравниваем с найденными точками
        projected_points, _ = cv2.projectPoints(
            FACE_MODEL,
            rotation_vector,
            translation_vector,
            camera_matrix,
            distortion_coefficients,
        )
        pixel_differences = projected_points[:, 0] - image_points
        squared_distances = np.sum(pixel_differences ** 2, axis=1)
        reprojection_rms_px = float(np.sqrt(np.mean(squared_distances)))

        # Разложение матрицы даёт углы вокруг X, Y, Z в градусах
        pitch, yaw, roll = cv2.RQDecomp3x3(rotation_matrix)[0]

        # 10 пикселей — предварительный фильтр, а не доказанная точность углов
        if not np.isfinite([pitch, yaw, roll, reprojection_rms_px]).all() or reprojection_rms_px > 10:
            raise ValueError('Недостоверная оценка позы: ошибка репроекции')

        return dict(status='estimated', yaw_deg=float(yaw), pitch_deg=float(pitch), roll_deg=float(roll),
                    reprojection_rms_px=reprojection_rms_px, method='solvepnp_generic_face_approx_camera_v1',
                    calibrated=False, ground_truth=False)

    except (KeyError, IndexError, TypeError, ValueError, cv2.error) as error:
        return dict(status='not_measurable', reason=str(error), calibrated=False, ground_truth=False)
