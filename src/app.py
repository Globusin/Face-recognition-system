# app.py - Основное приложение
from flask import Flask, jsonify, request
import os
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import create_embeddings_from_camera, save_embedding, add_new_user_with_embedding
from utils.db_connect import get_all_users

app = Flask(__name__)
app.secret_key = os.urandom(24)

@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    """API endpoint для аутентификации пользователя по лицу"""
    from utils.recognition import recognize_face_from_camera
    
    is_authenticated, user_id, distance = recognize_face_from_camera()
    
    if is_authenticated:
        # Лицо распознано, предоставляем доступ
        return jsonify({
            'status': 'success', 
            'message': 'Аутентификация прошла успешно',
            'user_id': user_id,
            'distance': distance
        })
    else:
        # Лицо не распознано, возвращаем ошибку
        return jsonify({
            'status': 'error', 
            'message': 'Лицо не распознано или не найдено в базе данных'
        })

@app.route('/api/add_user', methods=['POST'])
def add_user():
    name = request.args.get('name')
    embeddings = create_embeddings_from_camera()
        
    if embeddings:
        if len(embeddings) > 0:
            embeddings_id = save_embedding(embeddings[0])
            add_new_user_with_embedding(name, embeddings_id)
        else:
            return jsonify({'status': 'not success', 'message': 'error'})
    else:
        return jsonify({'status': 'not success', 'message': 'error'})
    
    return jsonify({'status': 'success', 'message': 'User added'})

@app.route('/api/get_users', methods=['GET'])
def get_users():
    try:
        users = get_all_users()
        return jsonify(users)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/delete_user/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    from utils.db_connect import delete_user_by_id
    try:
        success = delete_user_by_id(user_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Пользователь удален'})
        else:
            return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
