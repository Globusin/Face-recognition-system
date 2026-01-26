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
user_image_path = os.path.join(config.get('image', {}).get('output_dir', 0), config.get('image', {}).get('filename', 0))

def recognition():
    if not os.path.exists(user_image_path):
        logging.info(f"Эталонное изображение {user_image_path} не найдено.")

        success = capture_image(user_image_path)
        if success:
            logging.info(f"Создано эталонное изображение: {user_image_path}")
        else:
            logging.error("Не удалось создать эталонное изображение")
            return
    
    # Захватываем изображение с камеры для сравнения
    current_image_path = os.path.join('data', 'current_image.jpg')
    success = capture_image(current_image_path)
    
    if success:
        compare_faces(user_image_path, current_image_path)
    else:
        logging.error("Не удалось получить изображение для сравнения")

def compare_faces(known_face_img_path, check_face_img_path):
    known_image = face_recognition.load_image_file(known_face_img_path)
    check_image = face_recognition.load_image_file(check_face_img_path)
    
    # Получаем кодировки лиц на изображениях
    known_encodings = face_recognition.face_encodings(known_image)
    check_encodings = face_recognition.face_encodings(check_image)
    
    if len(known_encodings) == 0:
        logging.error("На эталонном изображении не найдено лиц")
        return
    
    if len(check_encodings) == 0:
        logging.error("На проверяемом изображении не найдено лиц")
        return
    
    results = face_recognition.compare_faces(known_encodings, check_encodings[0])
    
    if True in results:
        print("Лица совпадают!")
    else:
        print("Лица не совпадают!")

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

def main():
    embeddings = create_embeddings_from_camera()
    # save_embedding(embeddings[0])
    print(find_similar_embeddings(embeddings[0]))

if __name__ == '__main__':
    main()
