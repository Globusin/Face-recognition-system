import psycopg
import numpy as np

def create_connection():
    return psycopg.connect("host=localhost port=5433 dbname=face-recognition user=postgres password=fID3P8zg")

def initialize_pgvector():
    """Устанавливает расширение pgvector в базе данных"""
    with create_connection() as conn:
        with conn.cursor() as cur:
            # Устанавливаем расширение pgvector
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            conn.commit()
            print("Расширение pgvector установлено")

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
                print("Таблица embeddings уже существует")
                return
            
            cur.execute("""
                CREATE TABLE embeddings (
                    id SERIAL PRIMARY KEY,
                    embedding vector(128),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            conn.commit()
            print("Таблица embeddings")

def add_user_embedding(embedding):
    with create_connection() as conn:
        with conn.cursor() as cur:
            embedding_str = embedding_to_string(embedding)
            
            cur.execute("""
                INSERT INTO embeddings (embedding)
                VALUES (%s)
            """, (embedding_str,))
            
            conn.commit()
            print(f"Эмбэддинг успешно добавлен")

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
    create_embeddings_table()