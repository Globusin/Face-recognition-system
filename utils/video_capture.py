import os
import time
import threading
from pathlib import Path

import cv2

from utils.camera_manager import (
    CameraError,
    get_camera_manager,
)
from utils.logger import log_error, log_info
from utils.timing import measure_time

_face_cascade = None
_cascade_lock = threading.Lock()


def _load_face_cascade():
    global _face_cascade
    with _cascade_lock:
        if _face_cascade is None:
            cascade = cv2.CascadeClassifier(
                cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
            )
            if cascade.empty():
                log_error("Не удалось загрузить каскад для обнаружения лиц")
                return None
            _face_cascade = cascade
        return _face_cascade


@measure_time("Детекция лица: Хаар")
def detect_faces(frame, cascade=None):
    """Возвращает прямоугольники (x, y, w, h) на исходном кадре"""
    if cascade is None:
        cascade = _load_face_cascade()
    if cascade is None:
        raise CameraError("Не удалось загрузить детектор лиц")
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    with _cascade_lock:
        faces = cascade.detectMultiScale(gray, 1.3, 5)
    return [tuple(int(value) for value in face) for face in faces]


def _has_face(frame, cascade):
    return bool(detect_faces(frame, cascade))


def wait_for_face(stop_event, check_interval=0.5, on_wait=None):
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

        if _has_face(frame.image, cascade):
            return True

        if on_wait is not None:
            on_wait()
        stop_event.wait(check_interval)

    return False


@measure_time("JPEG: кодирование и запись")
def _save_frame(path, frame):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    return cv2.imwrite(path, frame)


@measure_time("Захват серии: ожидание и отбор кадров")
def capture_face_frames(frames_count, timeout=10, frame_delay=0.15):
    """Возвращает пары (копия BGR-кадра, прямоугольник единственного лица)"""
    if frames_count <= 0:
        return []

    manager = get_camera_manager()
    cascade = _load_face_cascade()
    if cascade is None:
        return []

    frames = []
    deadline = time.monotonic() + timeout
    last_captured_at = None

    try:
        # Не смешиваем кадры двух одновременных попыток распознавания
        with manager.capture_lock:
            # Начинаем после текущего кадра, чтобы не использовать старое изображение
            last_sequence = manager.get_last_sequence('primary')
            while time.monotonic() < deadline and len(frames) < frames_count:
                remaining = deadline - time.monotonic()
                with measure_time("Захват: ожидание свежего кадра"):
                    camera_frame = manager.get_frame(
                        role='primary',
                        after_sequence=last_sequence,
                        timeout=min(1.0, remaining),
                    )
                if camera_frame is None:
                    continue

                # Не принимаем один и тот же кадр повторно даже при сбое источника
                if camera_frame.sequence <= last_sequence:
                    continue
                last_sequence = camera_frame.sequence
                captured_at = camera_frame.timestamp_ns / 1_000_000_000

                if last_captured_at is not None and captured_at - last_captured_at < frame_delay:
                    continue
                faces = detect_faces(camera_frame.image, cascade)
                if len(faces) != 1:
                    continue

                # Копия не зависит от дальнейшего использования буфера камеры
                frames.append((camera_frame.image.copy(), faces[0]))
                last_captured_at = captured_at
    except CameraError as error:
        log_error(f"Ошибка камеры: {error}")
        return []

    if len(frames) < frames_count:
        log_error(f"Получено кадров: {len(frames)} из {frames_count}")

    return frames


def capture_frames(frames_count, timeout=10, frame_delay=0.15):
    """Возвращает BGR-массивы для вызовов, которым не нужны координаты"""
    return [image for image, _ in capture_face_frames(frames_count, timeout, frame_delay)]


def capture_image(output_path=None, timeout=10):
    """Сохраняет свежий кадр с лицом от основной камеры"""
    if output_path is None:
        data_dir = Path(__file__).parent.parent / 'data'
        data_dir.mkdir(exist_ok=True)
        output_path = str(data_dir / 'current_image.jpg')

    captured_paths = capture_images([output_path], timeout, frame_delay=0)
    if not captured_paths:
        log_error("На основной камере не найдено лицо")
        return False

    log_info(f"Изображение сохранено '{output_path}'")
    return True


def capture_images(output_paths, timeout=10, frame_delay=0.15):
    """Сохраняет серию свежих кадров основной камеры"""
    frames = capture_frames(len(output_paths), timeout, frame_delay)
    saved_paths = []
    for path, frame in zip(output_paths, frames):
        if not _save_frame(path, frame):
            log_error(f"Не удалось сохранить изображение '{path}'")
            return []
        saved_paths.append(path)
    return saved_paths
