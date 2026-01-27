#!/usr/bin/env python3
"""
Скрипт для добавления нового пользователя в базу данных
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from utils.recognition import create_embeddings_from_camera, save_embedding


def main():
    try:
        embeddings = create_embeddings_from_camera()
        
        if embeddings:
            if len(embeddings) > 1:
                print(f"Обнаружено несколько лиц ({len(embeddings)}). Будет сохранено первое лицо.")
            
            save_embedding(embeddings[0])
            print("Новое лицо успешно добавлено в базу данных!")
        else:
            print("Не удалось обнаружить лицо. Попробуйте еще раз.")
            sys.exit(1)
            
    except Exception as e:
        print(f"Ошибка при добавлении пользователя: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("Добавление нового пользователя в базу данных.")
    print("Пожалуйста, встаньте перед камерой.")
    input("Нажмите Enter для захвата изображения.")

    main()