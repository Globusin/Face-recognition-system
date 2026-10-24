# app.py - Основное приложение
from flask import Flask, Response, jsonify, request
import os
import sys
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import create_embeddings_from_camera, save_embedding, add_new_user_with_embedding
from utils.db_connect import get_all_users, delete_user_by_id
from utils.camera_manager import CameraError, get_camera_manager, get_public_camera_status

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.route('/api/cameras/status', methods=['GET'])
def camera_status():
    """Возвращает безопасную телеметрию камер без кадров и device paths"""
    return jsonify(get_public_camera_status())


@app.route('/api/cameras/<role>/frame', methods=['GET'])
def camera_frame(role):
    """Возвращает свежий уменьшенный кадр камеры"""
    if role not in ('primary', 'secondary'):
        return jsonify({'status': 'error', 'message': 'Неизвестная камера'}), 404

    try:
        frame = get_camera_manager().get_latest_frame(role, timeout=1.0)
    except CameraError as error:
        return jsonify({'status': 'error', 'message': str(error)}), 503

    if frame is None:
        return jsonify({'status': 'error', 'message': 'Кадр не получен'}), 503

    image = frame.image
    max_width = 640
    if image.shape[1] > max_width:
        scale = max_width / image.shape[1]
        size = (max_width, round(image.shape[0] * scale))
        image = cv2.resize(image, size, interpolation=cv2.INTER_AREA)

    encoded, jpeg = cv2.imencode(
        '.jpg',
        image,
        [cv2.IMWRITE_JPEG_QUALITY, 70],
    )
    if not encoded:
        return jsonify({'status': 'error', 'message': 'Не удалось подготовить кадр'}), 500

    response = Response(jpeg.tobytes(), mimetype='image/jpeg')
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.route('/api/authenticate', methods=['POST'])
def authenticate():
    """API endpoint для аутентификации пользователя по лицу"""
    from utils.recognition import recognize_face_from_camera
    
    is_authenticated, user_id, distance = recognize_face_from_camera()
    
    if is_authenticated:
        # API подтверждает личность, но не управляет физическим замком
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
    try:
        success = delete_user_by_id(user_id)
        if success:
            return jsonify({'status': 'success', 'message': 'Пользователь удален'})
        else:
            return jsonify({'status': 'error', 'message': 'Пользователь не найден'}), 404
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
