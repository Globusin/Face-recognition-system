import numpy as np
import os
from sklearn.datasets import fetch_lfw_people
import sys
from pathlib import Path
import cv2

# Добавляем путь к utils
sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import get_embeddings_from_image, save_embedding, check_for_similar_embeddings_in_db
from utils.logger import log_debug


def test_recognition(images_path):
    total_recognized = 0
    total_images = 0
    
    for folder in os.listdir(images_path):
        folder_path = os.path.join(images_path, folder)

        recognized = 0 
        sum = 0
        expected_user_id = None  # Инициализируем переменную для хранения ожидаемого ID пользователя
        
        for i, image in enumerate(os.listdir(folder_path)):
            image_path = os.path.join(folder_path, image)
            embeddings = get_embeddings_from_image(image_path)

            sum += 1

            if embeddings == None:
                continue

            if expected_user_id == None:
                # Сохраняем эмбеддинг и получаем ID пользователя
                expected_user_id = save_embedding(embeddings[0])
                sum -= 1
                continue

            is_known, user_id, distance = check_for_similar_embeddings_in_db(embeddings[0])

            # Проверяем, что пользователь известен и ID совпадает
            if is_known:
                if str(user_id) == str(expected_user_id):
                    recognized += 1
                else:
                    print(f'Ошибка распознования: неверный пользователь, расстояние: {distance}')
        
        print(f'Распознано {recognized} из {sum} => {recognized / sum * 100:.2f}%')
        
        # Обновляем общую статистику
        total_recognized += recognized
        total_images += sum
    
    if total_images > 0:
        average_recognition_rate = (total_recognized / total_images) * 100
        print(f'\nСредний процент распознавания: {average_recognition_rate:.2f}%')
    else:
        print('\nНе удалось вычислить средний процент распознавания: нет данных для проверки')

def save_lfw_image(image_array, output_path):
    """
    Специально для изображений из LFW (они в grayscale)
    """
    # LFW изображения обычно в формате (height, width)
    if len(image_array.shape) == 2:
        img = image_array.copy()
        
        # Масштабируем если нужно
        if img.max() <= 1.0:
            img = (img * 255).astype(np.uint8)
        else:
            img = img.astype(np.uint8)
        
        cv2.imwrite(output_path, img)
        print(f"LFW изображение сохранено: {img.shape} -> {output_path}")
        return True
    else:
        print(f"Ожидался 2D массив, получен {image_array.shape}")
        return False

def save_batch_lfw_images(lfw, output_dir):
    """
    Сохранение LFW изображений
    """
    images_array = lfw.images
    labels_array = lfw.target # id человека
    target_names = lfw.target_names # имена людей, соответсвуют id из lfw.target

    os.makedirs(output_dir, exist_ok=True)
    
    for i, (img, label) in enumerate(zip(images_array, labels_array)):
        person_name = target_names[label].replace(' ', '_')
            
        # Создаем папку для человека
        person_dir = os.path.join(output_dir, person_name)
        os.makedirs(person_dir, exist_ok=True)
        
        # Сохраняем изображение
        filename = f"{person_name}_{i}.jpg"
        filepath = os.path.join(person_dir, filename)
        
        save_lfw_image(img, filepath)


def run_tests():
    """
    Запуск всех тестов
    """
    log_debug("Запуск тестов качества распознавания на основе датасета LFW")
    
    try:
        # lfw = fetch_lfw_people(min_faces_per_person=100)
        # save_batch_lfw_images(lfw, 'images')

        test_recognition('images')
        log_debug("Все тесты пройдены успешно!")
    except Exception as e:
        log_debug(f"Ошибка при выполнении тестов: {e}")
        raise


if __name__ == "__main__":
    run_tests()