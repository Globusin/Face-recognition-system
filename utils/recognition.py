import face_recognition
import os
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.video_capture import capture_image
from utils.db_connect import add_user_embedding, find_similar_embeddings
from utils.config_loader import load_config

config = load_config()

def create_embeddings_from_camera():
    # Захватываем изображение с камеры
    camera_image_path = os.path.join('data', 'tmp_image.jpg')
    success = capture_image(camera_image_path)
    
    if not success:
        logging.error("Не удалось получить изображение с камеры для создания эмбэддингов")
        return None
    
    # Загружаем изображение
    image = face_recognition.load_image_file(camera_image_path)
    
    # Получаем эмбэддинги лиц на изображении
    embeddings = face_recognition.face_encodings(image)
    
    if len(embeddings) == 0:
        logging.warning("На изображении с камеры не найдено лиц")
        return None
    
    return embeddings

def save_embedding(embedding):
    add_user_embedding(embedding)

def check_face_exist_in_db_by_embedding(embedding):
    id, distance = find_similar_embeddings(embedding)[0]
    similarity = config.get('similarity', 0.15)
    if (distance < similarity):
        return True
    return False
