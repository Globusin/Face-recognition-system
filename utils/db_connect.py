import psycopg
import numpy as np
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.config_loader import load_config
from utils.logger import log_info, log_debug, log_error

def create_connection():
    config = load_config()
    db_config = config.get('database', {})
    
    host = db_config.get('host', 'localhost')
    port = db_config.get('port', 5433)
    dbname = db_config.get('name', 'face-recognition')
    user = db_config.get('user', 'postgres')
    password = db_config.get('password', 'fID3P8zg')
    
    connection_string = f"host={host} port={port} dbname={dbname} user={user} password={password}"
    return psycopg.connect(connection_string)

def initialize_pgvector():
    """Устанавливает расширение pgvector в базе данных"""
    with create_connection() as conn:
        with conn.cursor() as cur:
            # Устанавливаем расширение pgvector
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            log_debug("Расширение pgvector установлено")

def create_embeddings_table():
    initialize_pgvector()
    
    with create_connection() as conn:
        with conn.cursor() as cur:
            # Проверяем, существует ли таблица
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'embeddings'
                );
            """)
            
            table_exists = cur.fetchone()[0]
            
            if table_exists:
                log_debug("Таблица embeddings уже существует")
                return
            
            cur.execute("""
                CREATE TABLE embeddings (
                    id SERIAL PRIMARY KEY,
                    embedding vector(128),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            conn.commit()
            log_debug("Таблица embeddings")

def add_user_embedding(embedding):
    with create_connection() as conn:
        with conn.cursor() as cur:
            embedding_str = embedding_to_string(embedding)
            
            cur.execute("""
                INSERT INTO embeddings (embedding)
                VALUES (%s)
                RETURNING id
            """, (embedding_str,))
            
            user_id = cur.fetchone()[0]
            conn.commit()
            log_info(f"Эмбэддинг успешно добавлен с ID: {user_id}")
            return user_id

def find_similar_embeddings(target_embedding, limit=1):
    """Находит наиболее похожие эмбэддинги в базе данных"""
    with create_connection() as conn:
        with conn.cursor() as cur:
            target_embedding_str = embedding_to_string(target_embedding)
            
            cur.execute("""
                SELECT id, embedding <=> %s AS distance
                FROM embeddings
                ORDER BY distance
                LIMIT %s
            """, (target_embedding_str, limit))
            
            return cur.fetchall()

def embedding_to_string(embedding):
    """Преобразуем целевой эмбэддинг в строку"""
    return '[' + ','.join(map(str, embedding)) + ']' if isinstance(embedding, (list, np.ndarray)) else str(embedding)

if __name__ == "__main__":
    log_debug("Создание таблицы embeddings, если она не существует.")
    
    try:
        create_embeddings_table()
        log_debug("База данных успешно инициализирована!")
    except Exception as e:
        log_error(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)
