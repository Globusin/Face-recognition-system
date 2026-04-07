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

def create_embeddings_tables():
    initialize_pgvector()
    
    create_embeddings_table()
    create_users_table()
    create_users_to_embeddings_table()

def create_embeddings_table():
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

def create_users_table():
    with create_connection() as conn:
        with conn.cursor() as cur:
            # Проверяем, существует ли таблица
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'users'
                );
            """)
            
            table_exists = cur.fetchone()[0]
            
            if table_exists:
                log_debug("Таблица users уже существует")
                return
            
            cur.execute("""
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            conn.commit()
            log_debug("Таблица users успешно создана")


def create_users_to_embeddings_table():
    with create_connection() as conn:
        with conn.cursor() as cur:
            # Проверяем, существует ли таблица
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'users_to_embeddings'
                );
            """)
            
            table_exists = cur.fetchone()[0]
            
            if table_exists:
                log_debug("Таблица users_to_embeddings уже существует")
                return
            
            cur.execute("""
                CREATE TABLE users_to_embeddings (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    embedding_id INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (id)
                );
            """)
            
            conn.commit()
            log_debug("Таблица users_to_embeddings успешно создана")


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

def save_user_with_embedding(username: str, embedding_id: int):
    with create_connection() as conn:
        with conn.cursor() as cur:
            try:
                # Вставляем или игнорируем, если пользователь уже существует
                cur.execute("""
                    INSERT INTO users (username)
                    VALUES (%s)
                    RETURNING id;
                """, (username,))
                
                result = cur.fetchone()
                if result:
                    user_id = result[0]
                else:
                    return
                
                # Добавляем запись в users_to_embeddings
                cur.execute("""
                    INSERT INTO users_to_embeddings (user_id, embedding_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING;
                """, (user_id, embedding_id))
                
                conn.commit()
                log_debug(f"Пользователь {user_id} успешно связан с эмбеддингом {embedding_id}")
                
            except Exception as e:
                conn.rollback()
                log_error(f"Ошибка при сохранении пользователя с эмбеддингом: {e}")
                raise


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

def get_all_users():
    """Возвращает всех пользователей из базы данных"""
    with create_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.created_at
                FROM users u
                ORDER BY u.id
            """)
            users = cur.fetchall()
            
            # Преобразуем результаты в список словарей
            result = []
            for user in users:
                result.append({
                    'id': user[0],
                    'name': user[1],
                    'date_registered': user[2].strftime('%Y-%m-%d') if user[2] else None
                })
            
            return result

def get_user_by_embedding_id(embedding_id: int):
    """Получает пользователя по embedding_id"""
    with create_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT u.id, u.username, u.created_at
                FROM users u
                JOIN users_to_embeddings ute ON u.id = ute.user_id
                WHERE ute.embedding_id = %s
            """, (embedding_id,))
            
            result = cur.fetchone()
            
            if result is None:
                log_debug(f"Пользователь для embedding_id={embedding_id} не найден.")
                return None
            
            return {
                'id': result[0],
                'name': result[1],
                'date_registered': result[2].strftime('%Y-%m-%d') if result[2] else None
            }


if __name__ == "__main__":
    log_debug("Создание таблиц.")
    
    try:
        create_embeddings_tables()
        log_debug("База данных успешно инициализирована!")
    except Exception as e:
        log_error(f"Ошибка при инициализации базы данных: {e}")
        sys.exit(1)
