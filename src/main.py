import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import create_embeddings_from_camera, check_face_exist_in_db_by_embedding

def main():
    embeddings = create_embeddings_from_camera()
    if (check_face_exist_in_db_by_embedding(embeddings[0])):
        print('Лицо есть в базе')

if __name__ == '__main__':
    main()
