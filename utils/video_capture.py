import cv2
import os
import sys
import time
from pathlib import Path
import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_error

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
        log_info(f"Установлено разрешение камеры: {width}x{height}")
    
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        cap.release()
        return False

    best_frame = None
    start_time = time.time()
    
    log_info(f"Поиск лучшего изображения (таймаут: {timeout}с)")
    
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