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
from utils.db_connect import *


def test_recognition(images_path):
    # Общая статистика
    total_stats = {
        'total_images': 0,
        'total_processed': 0,
        'total_recognized': 0,
        'total_errors': 0,
        'total_unknown': 0,
        'by_person': {}  # Статистика по каждому человеку
    }
    
    for folder in os.listdir(images_path):
        folder_path = os.path.join(images_path, folder)
        person_name = folder
        
        # Статистика по текущему человеку
        person_stats = {
            'total': 0,
            'processed': 0,
            'recognized': 0,
            'errors': 0,
            'unknown': 0,
            'wrong_person': 0,
            'distances': []
        }
        
        expected_user_id = None
        
        for image in os.listdir(folder_path):
            image_path = os.path.join(folder_path, image)
            embeddings = get_embeddings_from_image(image_path)
            
            person_stats['total'] += 1
            
            if embeddings is None:
                person_stats['errors'] += 1
                continue
            
            if expected_user_id is None:
                embedding_id = add_user_embedding(embeddings[0])
                # Создаем пользователя и связываем с эмбеддингом
                save_user_with_embedding(person_name, embedding_id)
                
                user = get_user_by_embedding_id(embedding_id)
                expected_user_id = user['id']
                
                person_stats['total'] -= 1
                continue

            person_stats['processed'] += 1
            
            is_known, user_id, distance = check_for_similar_embeddings_in_db(embeddings[0])
            
            if is_known:
                if str(user_id) == str(expected_user_id):
                    person_stats['recognized'] += 1
                    person_stats['distances'].append(distance)
                else:
                    person_stats['wrong_person'] += 1
                    # Получаем имя неверного пользователя
                    wrong_user = get_user_by_embedding_id(user_id)
                    wrong_name = wrong_user['name'] if wrong_user else 'Unknown'
                    
                    print(f'Ошибка: {person_name} распознан как "{wrong_name}" (id {user_id}), '
                          f'правильный id {expected_user_id}, расстояние: {distance:.4f}')
            else:
                person_stats['unknown'] += 1
                print(f'Пользователь {person_name} не распознан, расстояние: {distance:.4f}')
        
        if person_stats['processed'] > 0:
            recognition_rate = (person_stats['recognized'] / person_stats['total']) * 100
            error_rate = (person_stats['wrong_person'] / person_stats['processed']) * 100
            unknown_rate = (person_stats['unknown'] / person_stats['processed']) * 100
            avg_distance = np.mean(person_stats['distances']) if person_stats['distances'] else 0
            
            print(f"\nСтатистика для {person_name}:")
            print(f"Всего изображений: {person_stats['total']}")
            print(f"Обработано: {person_stats['processed']}")
            print(f"Распознано верно: {person_stats['recognized']} ({recognition_rate:.2f}%)")
            print(f"Ошибки распознавания: {person_stats['wrong_person']} ({error_rate:.2f}%)")
            print(f"Не распознано: {person_stats['unknown']} ({unknown_rate:.2f}%)")
            print(f"Ошибки при загрузке: {person_stats['errors']}")
            print(f"Среднее расстояние: {avg_distance:.4f}")
        else:
            print(f"\nДля {person_name} нет обработанных изображений")
        
        # Обновляем общую статистику
        total_stats['total_images'] += person_stats['total']
        total_stats['total_processed'] += person_stats['processed']
        total_stats['total_recognized'] += person_stats['recognized']
        total_stats['total_errors'] += person_stats['errors']
        total_stats['total_unknown'] += person_stats['unknown']
        total_stats['by_person'][person_name] = person_stats
    
    # Общая статистика
    if total_stats['total_processed'] > 0:
        avg_recognition = (total_stats['total_recognized'] / total_stats['total_processed']) * 100
        avg_unknown = (total_stats['total_unknown'] / total_stats['total_processed']) * 100
        
        print("\n" + "="*50)
        print(f"Всего изображений: {total_stats['total_images']}")
        print(f"Успешно обработано: {total_stats['total_processed']}")
        print(f"Ошибки загрузки: {total_stats['total_errors']}")
        print(f"\nСредний процент верного распознавания: {avg_recognition:.2f}%")
        print(f"Средний процент неизвестных лиц: {avg_unknown:.2f}%")
    return total_stats


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
        print(f"Ожидался массив, получен {image_array.shape}")
        return False


def save_batch_lfw_images(lfw, output_dir):
    """
    Сохранение LFW изображений
    """
    images_array = lfw.images
    labels_array = lfw.target  # id человека
    target_names = lfw.target_names  # имена людей, соответствуют id из lfw.target

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


def cleanup_test_data():
    """Очищает тестовые данные из БД после тестирования"""

    log_debug("Очистка тестовых данных")
    
    try:
        users = get_all_users()
        
        for user in users:
            delete_user_by_id(user['id'])
            log_debug(f"Удален пользователь: {user['name']} (id: {user['id']})")
        
        log_debug("Тестовые данные успешно очищены")
    except Exception as e:
        log_debug(f"Ошибка при очистке тестовых данных: {e}")


if __name__ == "__main__":
    log_debug("Запуск теста на основе датасета LFW")
    
    try:
        create_embeddings_tables()

        lfw = fetch_lfw_people(min_faces_per_person=100)
        save_batch_lfw_images(lfw, 'images')

        test_recognition('images')
        cleanup_test_data()
        
        log_debug("Тест на основе датасета LFW пройден успешно")
    except Exception as e:
        log_debug(f"Ошибка при выполнении теста на основе датасета LFW: {e}")
        raise