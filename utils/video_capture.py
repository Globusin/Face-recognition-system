import cv2
import os
import sys
import time
from pathlib import Path
import numpy as np

sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_error, log_debug

def add_padding(frame, face_box):
    if face_box is not None:
        x, y, w, h = face_box
        # Отступы вокруг лица 10%
        padding_x = int(w * 0.1)
        padding_y = int(h * 0.1)
        x = max(0, x - padding_x)
        y = max(0, y - padding_y)
        w = min(frame.shape[1] - x, w + 2 * padding_x)
        h = min(frame.shape[0] - y, h + 2 * padding_y)
        return frame[y:y+h, x:x+w]
    
    return frame

def is_overexposed(frame, face_box=None, threshold=250, max_percent=0.15):
    roi = add_padding(frame, face_box)
    
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    overexposed_pixels = np.sum(gray > threshold)
    total_pixels = gray.shape[0] * gray.shape[1]
    
    return (overexposed_pixels / total_pixels) > max_percent

def is_underexposed(frame, face_box=None, threshold=30, max_percent=0.15):
    roi = add_padding(frame, face_box)
    
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    underexposed_pixels = np.sum(gray < threshold)
    total_pixels = gray.shape[0] * gray.shape[1]
    
    return (underexposed_pixels / total_pixels) > max_percent

def is_blurry(frame, face_box=None, threshold=80.0):
    if face_box is not None:
        x, y, w, h = face_box
        roi = frame[y:y+h, x:x+w]
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    else:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    return laplacian_var < threshold

def capture_image(output_path=None, camera_index=None, timeout=10, min_quality=0.1):
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
    
    try:
        cap.set(cv2.CAP_PROP_AUTO_EXPOSURE, 1)  # Ручной режим
        cap.set(cv2.CAP_PROP_AUTO_WB, 0)  # Отключаение авто баланса белого
        log_debug("Автоматические настройки камеры отключены")
    except:
        log_debug("Не удалось отключить автоматические настройки камеры")
    
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    if face_cascade.empty():
        log_error("Не удалось загрузить каскад для обнаружения лиц")
        cap.release()
        return False

    best_frame = None
    best_quality = 0
    start_time = time.time()
    
    log_info(f"Поиск лучшего изображения (таймаут: {timeout}с, мин. качество: {min_quality})")
    
    while time.time() - start_time < timeout:
        ret, frame = cap.read()
        if not ret:
            print(2)
            log_error("Ошибка захвата кадра")
            break

        # Поиск лиц
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = face_cascade.detectMultiScale(gray, 1.3, 5)
        
        if len(faces) == 0:
            continue

        # Анализ лиц
        for (x, y, w, h) in faces:
            face_box = (x, y, w, h)
            
            if is_overexposed(frame, face_box):
                continue
                
            if is_underexposed(frame, face_box):
                continue
                
            if is_blurry(frame, face_box):
                continue
            
            
            best_frame = frame.copy()
            break
        
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
        
        if best_quality >= min_quality:
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
        log_info(f"Изображение сохранено как '{output_path}' с качеством {best_quality:.2f}")
        
        return True
    else:
        log_error(f"Не удалось получить качественное изображение с камеры {camera_index}")    
        return False