#!/usr/bin/env python3
"""Скрипт для инициализации базы данных"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from utils.db_connect import create_embeddings_table


def main():
    print("Создание таблицы embeddings, если она не существует.")
    
    try:
        create_embeddings_table()
        print("База данных успешно инициализирована!")
    except Exception as e:
        print(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()