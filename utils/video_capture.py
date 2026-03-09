import cv2
import logging
import os
import sys
from pathlib import Path

# Добавляем путь к директории utils для правильного импорта
sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_error

def capture_image(output_path=None, camera_index=None):
    config = load_config()

    if camera_index is None:
        camera_index = config.get('camera', {}).get('index', 0)
    
    cap = cv2.VideoCapture(camera_index)
    
    resolution = config.get('camera', {}).get('resolution', {})
    if resolution:
        width = resolution.get('width', 1280)
        height = resolution.get('height', 720)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        log_info(f"Установлено разрешение камеры: {width}x{height}")
    
    ret, frame = cap.read()

    if ret:
        if output_path is None:
            os.makedirs('data', exist_ok=True)
            output_path = os.path.join('data', 'current_image.jpg')
        
        cv2.imwrite(output_path, frame)
        log_info(f"Изображение сохранено как '{output_path}' с камеры {camera_index}")
        cap.release()
        return True
    else:
        log_error(f"Не удалось получить изображение с камеры {camera_index}")
        cap.release()
        return False

if __name__ == "__main__":
    capture_image()
