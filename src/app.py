# app.py - Основное приложение
from flask import Flask, Response, jsonify, request
import os
import sys
import hmac
from functools import wraps
from pathlib import Path

import cv2

sys.path.append(str(Path(__file__).parent.parent))

from utils.recognition import create_embeddings_from_camera, save_embedding, add_new_user_with_embedding
from utils.db_connect import get_all_users, delete_user_by_id
from utils.camera_manager import CameraError, get_camera_manager, get_public_camera_status
from utils.maintenance import maintenance
from utils.stereo_calibration import calibration_session
from utils.config_loader import load_config
from utils.face_detection_preview import face_detection_preview

app = Flask(__name__)
app.secret_key = os.urandom(24)


def calibration_admin(view):
    @wraps(view)
    def protected(*args, **kwargs):
        token = os.environ.get('CALIBRATION_ADMIN_TOKEN') or load_config().get('stereo_calibration', {}).get('admin_token', '')
        if not isinstance(token, str) or not token:
            return jsonify(message='Калибровка отключена: не задан токен администратора'), 503
        supplied = request.headers.get('X-Calibration-Token', '')
        if not hmac.compare_digest(supplied.encode(), token.encode()):
            return jsonify(message='Неверный токен администратора'), 401
        try:
            return view(*args, **kwargs)
        except CameraError:
            return jsonify(message='Камеры недоступны'), 503
        except (ValueError, RuntimeError) as error:
            return jsonify(message=str(error)), 409
        except (cv2.error, OSError):
            return jsonify(message='Ошибка расчёта или сохранения калибровки'), 500
    return protected


@app.get('/api/calibration/status')
@calibration_admin
def calibration_status():
    return jsonify(calibration_session.status())


@app.post('/api/calibration/frame/<role>')
@calibration_admin
def calibration_frame(role):
    data = request.get_json(silent=True) or {}
    image = calibration_session.download_frame(data.get('session_id'), data.get('observation_id'), role)
    response = Response(image, mimetype='image/png')
    response.headers['Content-Disposition'] = f'attachment; filename="calibration_{role}.png"'
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.post('/api/calibration/<action>')
@calibration_admin
def calibration_action(action):
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(message='Неверный формат запроса'), 400
    if action == 'start':
        if data.get('mounting_confirmed') is not True:
            return jsonify(message='Подтвердите крепление камер и размеры доски'), 400
        return jsonify(calibration_session.start(data.get('square_mm', 45.0)))
    if action == 'observe':
        rotation = data.get('rotation', 0)
        if type(rotation) is not int or rotation not in range(4):
            return jsonify(message='Недопустимый поворот сетки'), 400
        return jsonify(calibration_session.observe(data.get('session_id'), rotation))
    if action == 'capture':
        return jsonify(calibration_session.save_pair(
            data.get('session_id'), data.get('observation_id'),
            data.get('validation') is True, data.get('orientation_confirmed'),
        ))
    if action == 'calculate':
        return jsonify(calibration_session.calculate(data.get('session_id')))
    if action == 'review':
        return jsonify(calibration_session.review(data.get('session_id'), data.get('pair_index')))
    if action == 'verify':
        return jsonify(calibration_session.verify_observation(
            data.get('session_id'), data.get('observation_id'), data.get('calibration_id'),
            data.get('orientation_confirmed'), data.get('mounting_confirmed')))
    if action == 'quality':
        return jsonify(calibration_session.measure_quality(
            data.get('session_id'), data.get('observation_id'), data.get('calibration_id'),
            data.get('orientation_confirmed'), data.get('mounting_confirmed'), data.get('stationary')))
    if action == 'face':
        response = jsonify(calibration_session.measure_face(
            data.get('session_id'), data.get('calibration_id'), data.get('mounting_confirmed'),
            data.get('consent_confirmed'), data.get('sample_type'), data.get('lighting'), data.get('distance_cm')))
        response.headers['Cache-Control'] = 'no-store'
        return response
    if action == 'finish':
        return jsonify(calibration_session.finish(data.get('session_id')))
    return jsonify(message='Неизвестная команда'), 404


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
    if role == 'primary' and request.args.get('haar') == '1':
        face_detection_preview.enable()
        image = face_detection_preview.render(frame)
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
    
    try:
        with maintenance.recognition():
            is_authenticated, user_id, distance = recognize_face_from_camera()
    except RuntimeError as error:
        return jsonify(status='error', message=str(error)), 409
    
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
    try:
        with maintenance.recognition():
            embeddings = create_embeddings_from_camera()
    except RuntimeError as error:
        return jsonify(status='error', message=str(error)), 409
        
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
