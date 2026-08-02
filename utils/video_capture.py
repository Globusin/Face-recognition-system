import cv2
import os
import sys
import time
from pathlib import Path
import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_debug

def capture_image(output_path=None, timeout=10):
    config = load_config()

    camera_index = config.get('camera', {}).get('index', 0)
    cap = cv2.VideoCapture(camera_index)
    
    resolution = config.get('camera', {}).get('resolution', {})
    if resolution:
        width = resolution.get('width', 1280)
        height = resolution.get('height', 720)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        log_debug(f"Установлено разрешение камеры: {width}x{height}")
    
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        cap.release()
        return False

    best_frame = None
    start_time = time.time()
    
    log_debug(f"Поиск лучшего изображения (таймаут: {timeout}с)")
    
    while time.time() - start_time < timeout:
        ret, frame = cap.read()
        if not ret:
            log_error("Ошибка захвата кадра")
            break

        # Поиск лиц
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        if len(faces) == 0:
            continue

        best_frame = frame.copy()
        break
    
    cv2.destroyAllWindows()
    cap.release()
    
    if best_frame is not None:
        if output_path is None:
            base_dir = Path(__file__).parent.parent
            data_dir = base_dir / 'data'
            data_dir.mkdir(exist_ok=True)
            output_path = str(data_dir / 'current_image.jpg')
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        cv2.imwrite(output_path, best_frame)
        log_info(f"Изображение сохранено '{output_path}'")
        
        return True
    else:
        log_error(f"Не удалось получить качественное изображение с камеры {camera_index}")    
        return False

def capture_images(output_paths, timeout=10, frame_delay=0.15):
    """Захватывает несколько кадров с лицом за одно открытие камеры."""
    config = load_config()

    camera_index = config.get('camera', {}).get('index', 0)
    cap = cv2.VideoCapture(camera_index)
    
    resolution = config.get('camera', {}).get('resolution', {})
    if resolution:
        width = resolution.get('width', 1280)
        height = resolution.get('height', 720)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        log_debug(f"Установлено разрешение камеры: {width}x{height}")
    
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        cap.release()
        return []

    captured_paths = []
    start_time = time.time()
    
    log_debug(f"Захват серии изображений (таймаут: {timeout}с)")
    
    while time.time() - start_time < timeout and len(captured_paths) < len(output_paths):
        ret, frame = cap.read()
        if not ret:
            log_error("Ошибка захвата кадра")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        if len(faces) == 0:
            continue

        output_path = output_paths[len(captured_paths)]
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        cv2.imwrite(output_path, frame)
        captured_paths.append(output_path)
        log_debug(f"Изображение серии сохранено '{output_path}'")

        if frame_delay > 0 and len(captured_paths) < len(output_paths):
            time.sleep(frame_delay)
    
    cv2.destroyAllWindows()
    cap.release()
    
    if not captured_paths:
        log_error(f"Не удалось получить серию изображений с камеры {camera_index}")
    
    return captured_paths
