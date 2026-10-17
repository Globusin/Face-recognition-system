import cv2
import os
import sys
import time
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_debug, log_warning


_camera_sources_cache = None


def _apply_camera_resolution(cap, camera_config):
    resolution = camera_config.get('resolution', {})
    if not resolution:
        return

    width = resolution.get('width', 1280)
    height = resolution.get('height', 720)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    log_debug(f"Установлено разрешение камеры: {width}x{height}")


def _open_camera(source, camera_config):
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        cap.release()
        return None

    _apply_camera_resolution(cap, camera_config)
    return cap


def _camera_returns_frames(source, camera_config):
    cap = _open_camera(source, camera_config)
    if cap is None:
        return False

    try:
        for _ in range(5):
            success, frame = cap.read()
            if success and frame is not None and frame.size > 0:
                return True
        return False
    finally:
        cap.release()


def _camera_by_paths():
    by_id_dir = Path('/dev/v4l/by-id')
    if not by_id_dir.exists():
        return []

    # Такой формат потому что в linux по пути '/dev/v4l/by-id' храняться наименования камер
    # например usb-Foxlink_HP_HD_Camera_200901010001-video-index1
    return [str(path) for path in sorted(by_id_dir.glob('*-video-index0'))]


def _source_device_identity(source):
    if isinstance(source, int):
        # /dev/videoN — стандартный путь Linux к видеоустройствам
        return str(Path(f'/dev/video{source}').resolve())
    return str(Path(source).resolve())


def discover_camera_sources(force_refresh=False):
    """Возвращает источники доступных камер"""
    global _camera_sources_cache

    if _camera_sources_cache is not None and not force_refresh:
        return list(_camera_sources_cache)

    config = load_config()
    camera_config = config.get('camera', {})
    auto_detect = camera_config.get('auto_detect', True)
    required_count = max(1, int(camera_config.get('required_count', 2)))
    configured_sources = camera_config.get('sources', [])

    if configured_sources:
        candidates = list(configured_sources)
    elif not auto_detect:
        candidates = [camera_config.get('index', 0)]
    else:
        candidates = _camera_by_paths()
        scan_max_index = max(1, int(camera_config.get('scan_max_index', 10)))
        candidates.extend(range(scan_max_index))

    detected_sources = []
    detected_device_ids = set()
    for source in candidates:
        device_id = _source_device_identity(source)
        if device_id in detected_device_ids:
            continue

        if _camera_returns_frames(source, camera_config):
            detected_sources.append(source)
            detected_device_ids.add(device_id)
            log_info(f"Обнаружена камера: {source}")
            if auto_detect and len(detected_sources) >= required_count:
                break

    expected_count = required_count if auto_detect else len(candidates)
    if len(detected_sources) < expected_count:
        log_warning(
            f"Обнаружено камер: {len(detected_sources)}, ожидалось: {expected_count}"
        )

    _camera_sources_cache = detected_sources
    return list(_camera_sources_cache)


def _open_detected_cameras():
    config = load_config()
    camera_config = config.get('camera', {})
    # Данные из конфига
    auto_detect = camera_config.get('auto_detect', True)
    required_count = max(1, int(camera_config.get('required_count', 2)))
    opened_cameras = []

    for source in discover_camera_sources():
        cap = _open_camera(source, camera_config)
        if cap is not None:
            opened_cameras.append((source, cap))
        else:
            log_warning(f"Камера стала недоступна: {source}")

    if opened_cameras and (not auto_detect or len(opened_cameras) >= required_count):
        return opened_cameras

    # USB-камера могла получить другой video index после переподключения.
    _release_cameras(opened_cameras)
    opened_cameras = []
    for source in discover_camera_sources(force_refresh=True):
        cap = _open_camera(source, camera_config)
        if cap is not None:
            opened_cameras.append((source, cap))

    return opened_cameras


def _load_face_cascade():
    face_cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + 'haarcascade_frontalface_default.xml'
    )
    if face_cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        return None
    return face_cascade


def _release_cameras(cameras):
    """Освобождает все открытые видеоустройства и ресурсы OpenCV"""
    for _, cap in cameras:
        # Без release() камера может остаться занятой для следующих обращений
        cap.release()

    # Закрывает окна OpenCV, если они создавались в процессе работы
    cv2.destroyAllWindows()


def _find_frame_with_face(cameras, face_cascade, timeout):
    start_time = time.time()

    while time.time() - start_time < timeout:
        for source, cap in cameras:
            success, frame = cap.read()
            if not success:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) > 0:
                return source, cap, frame

    return None, None, None


def capture_image(output_path=None, timeout=10):
    cameras = _open_detected_cameras()
    if not cameras:
        log_error("Не найдено ни одной доступной камеры")
        return False

    face_cascade = _load_face_cascade()
    if face_cascade is None:
        _release_cameras(cameras)
        return False

    log_debug(f"Поиск изображения с лицом на {len(cameras)} камерах (таймаут: {timeout}с)")

    try:
        source, _, best_frame = _find_frame_with_face(cameras, face_cascade, timeout)
    finally:
        _release_cameras(cameras)

    if best_frame is None:
        log_error("Не удалось получить изображение с лицом ни с одной камеры")
        return False

    if output_path is None:
        data_dir = Path(__file__).parent.parent / 'data'
        data_dir.mkdir(exist_ok=True)
        output_path = str(data_dir / 'current_image.jpg')

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    if not cv2.imwrite(output_path, best_frame):
        log_error(f"Не удалось сохранить изображение '{output_path}'")
        return False

    log_info(f"Изображение с камеры {source} сохранено '{output_path}'")
    return True


def capture_images(output_paths, timeout=10, frame_delay=0.15):
    """Выбирает камеру с лицом и захватывает с неё серию кадров."""
    if not output_paths:
        return []

    cameras = _open_detected_cameras()
    if not cameras:
        log_error("Не найдено ни одной доступной камеры")
        return []

    face_cascade = _load_face_cascade()
    if face_cascade is None:
        _release_cameras(cameras)
        return []

    captured_paths = []
    source = None
    log_debug(f"Выбор камеры с лицом среди {len(cameras)} камер")

    try:
        source, selected_cap, first_frame = _find_frame_with_face(
            cameras, face_cascade, timeout
        )
        if first_frame is None:
            log_error("Лицо не найдено ни на одной камере")
            return []

        log_info(f"Для серии кадров выбрана камера: {source}")
        frame = first_frame
        start_time = time.time()

        while time.time() - start_time < timeout and len(captured_paths) < len(output_paths):
            if frame is None:
                success, frame = selected_cap.read()
                if not success:
                    log_warning(f"Ошибка чтения выбранной камеры: {source}")
                    break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.3, 5)
            if len(faces) > 0:
                output_path = output_paths[len(captured_paths)]
                output_dir = os.path.dirname(output_path)
                if output_dir:
                    os.makedirs(output_dir, exist_ok=True)

                if cv2.imwrite(output_path, frame):
                    captured_paths.append(output_path)
                    log_debug(f"Изображение серии сохранено '{output_path}'")

                    if frame_delay > 0 and len(captured_paths) < len(output_paths):
                        time.sleep(frame_delay)

            frame = None
    finally:
        _release_cameras(cameras)

    if not captured_paths:
        log_error(f"Не удалось получить серию изображений с камеры {source}")

    return captured_paths
