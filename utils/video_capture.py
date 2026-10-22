import os
import time
from pathlib import Path

import cv2

from utils.camera_manager import (
    CameraError,
    get_camera_manager,
)
from utils.logger import log_debug, log_error, log_info


def _load_face_cascade():
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )
    if cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        return None
    return cascade


def _has_face(frame, cascade):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    faces = cascade.detectMultiScale(gray, 1.3, 5)
    return len(faces) > 0


def wait_for_face(stop_event, check_interval=0.5):
    """Проверяет по одному свежему кадру до появления лица или остановки"""
    cascade = _load_face_cascade()
    if cascade is None:
        raise CameraError("Не удалось загрузить детектор лиц")

    manager = get_camera_manager()
    last_sequence = manager.get_last_sequence('primary')

    while not stop_event.is_set():
        frame = manager.get_frame(
            role='primary', after_sequence=last_sequence, timeout=1.0,
        )
        if frame is None:
            raise CameraError("Основная камера не отдаёт свежие кадры")

        # Пропускаем накопленные кадры и проверяем последний доступный
        frame = manager.get_latest_frame('primary')
        if frame is None:
            raise CameraError("Основная камера не отдаёт кадры")
        last_sequence = frame.sequence

        image = frame.image
        if image.shape[1] > 640:
            scale = 640 / image.shape[1]
            image = cv2.resize(
                image, (640, round(image.shape[0] * scale)),
                interpolation=cv2.INTER_AREA,
            )
        if _has_face(image, cascade):
            return True

        stop_event.wait(check_interval)

    return False


def _save_frame(path, frame):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return cv2.imwrite(path, frame)


def _capture_face_images(output_paths, timeout, frame_delay):
    """Получает нужное количество свежих кадров с лицом"""
    if not output_paths:
        return []

    manager = get_camera_manager()
    cascade = _load_face_cascade()
    if cascade is None:
        return []

    captured_paths = []
    deadline = time.monotonic() + timeout
    last_saved_at = None

    try:
        # Не смешиваем кадры двух одновременных попыток распознавания
        with manager.capture_lock:
            # Начинаем после текущего кадра, чтобы не использовать старое изображение
            last_sequence = manager.get_last_sequence('primary')
            while time.monotonic() < deadline and len(captured_paths) < len(output_paths):
                remaining = deadline - time.monotonic()
                camera_frame = manager.get_frame(
                    role='primary',
                    after_sequence=last_sequence,
                    timeout=min(1.0, remaining),
                )
                if camera_frame is None:
                    continue

                last_sequence = camera_frame.sequence
                captured_at = camera_frame.timestamp_ns / 1_000_000_000

                if last_saved_at is not None and captured_at - last_saved_at < frame_delay:
                    continue
                if not _has_face(camera_frame.image, cascade):
                    continue

                output_path = output_paths[len(captured_paths)]
                if not _save_frame(output_path, camera_frame.image):
                    log_error(f"Не удалось сохранить изображение '{output_path}'")
                    return []

                captured_paths.append(output_path)
                last_saved_at = captured_at
                log_debug(f"Изображение сохранено '{output_path}'")
    except CameraError as error:
        log_error(f"Ошибка камеры: {error}")
        return []

    if len(captured_paths) < len(output_paths):
        log_error(f"Получено кадров: {len(captured_paths)} из {len(output_paths)}")

    return captured_paths


def capture_image(output_path=None, timeout=10):
    """Сохраняет свежий кадр с лицом от основной камеры"""
    if output_path is None:
        data_dir = Path(__file__).parent.parent / 'data'
        data_dir.mkdir(exist_ok=True)
        output_path = str(data_dir / 'current_image.jpg')

    captured_paths = _capture_face_images([output_path], timeout, frame_delay=0)
    if not captured_paths:
        log_error("На основной камере не найдено лицо")
        return False

    log_info(f"Изображение сохранено '{output_path}'")
    return True


def capture_images(output_paths, timeout=10, frame_delay=0.15):
    """Сохраняет серию свежих кадров основной камеры"""
    return _capture_face_images(output_paths, timeout, frame_delay)
