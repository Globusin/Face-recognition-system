import face_recognition
import os
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.video_capture import capture_image
from utils.db_connect import add_user_embedding, find_similar_embeddings
from utils.config_loader import load_config
from utils.logger import log_error, log_warning

config = load_config()

def create_embeddings_from_camera():
    # Захватываем изображение с камеры
    camera_image_path = os.path.join('data', 'tmp_image.jpg')
    success = capture_image(camera_image_path)
    
    if not success:
        log_error("Не удалось получить изображение с камеры для создания эмбэддингов")
        return None
    
    # Загружаем изображение
    image = face_recognition.load_image_file(camera_image_path)
    
    # Получаем эмбэддинги лиц на изображении
    embeddings = face_recognition.face_encodings(image)
    
    if len(embeddings) == 0:
        log_warning("На изображении с камеры не найдено лиц")
        return None
    
    return embeddings

def save_embedding(embedding):
    add_user_embedding(embedding)

def check_for_similar_embeddings_in_db(embedding):
    results = find_similar_embeddings(embedding)
    if not results:
        return False, None
    
    id, distance = results[0]
    similarity = config.get('similarity', 0.15)
    
    if distance < similarity:
        return True, id, distance
    return False, None, None

def recognize_face_from_camera():
    """Распознает лицо с камеры и проверяет его наличие в базе данных"""

    embeddings = create_embeddings_from_camera()
    
    if embeddings is None or len(embeddings) == 0:
        log_warning("Не удалось получить эмбэддинги с камеры")
        return False, None, None
    
    embedding = embeddings[0]
    is_known, user_id, distance = check_for_similar_embeddings_in_db(embedding)
    
    if is_known:
        return True, user_id, distance
            
    
    return False, None, None
