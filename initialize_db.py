import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent))

from utils.db_connect import create_embeddings_table
from utils.logger import log_info, log_error


def main():
    log_info("Создание таблицы embeddings, если она не существует.")
    
    try:
        create_embeddings_table()
        log_info("База данных успешно инициализирована!")
    except Exception as e:
        log_error(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
